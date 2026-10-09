import importlib.util
from pathlib import Path
import unittest
from unittest.mock import Mock

ROOT=Path(__file__).resolve().parents[1]
def load(name,path):
    s=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
wrapper=load('event_manager',ROOT/'tools/console-manager-cadence.py')
token=load('event_token',ROOT/'tools/console-token.py')
producer=load('event_producer',ROOT/'tools/spice-refresh-smoke.py')
NONCE='0344034403440344'

class EventVerdictTests(unittest.TestCase):
    def verdict(self,mode='roi',split=False,unique=10,invalid=0,errors=(),exit=0):
        return producer.event_control_passed(mode,split,20,unique,invalid,errors,exit)
    def test_positive_rejects_any_corruption_and_static_token(self):
        self.assertTrue(self.verdict())
        self.assertFalse(self.verdict(invalid=1));self.assertFalse(self.verdict(unique=1))
    def test_negative_requires_corruption_not_multiple_valid_ids(self):
        self.assertTrue(self.verdict(split=True,unique=0,invalid=1))
        self.assertFalse(self.verdict(split=True,unique=100,invalid=0))
    def test_count_only_has_no_pixel_oracle(self):
        self.assertTrue(self.verdict(mode='count-only',unique=0))
    def test_process_or_observer_failure_never_passes(self):
        for mode in ('roi','count-only'):
            self.assertFalse(self.verdict(mode=mode,errors=['callback failure']))
            self.assertFalse(self.verdict(mode=mode,exit=-15))

class EventObserverTests(unittest.TestCase):
    def create(self,sample=None):
        self.display=object();self.channel=object();self.handlers={};self.records=[];self.errors=[];self.removed=[]
        def connect(obj,signal,callback):
            self.handlers[signal]=callback;return signal
        self.observer=wrapper.EventObserver(self.display,self.channel,connect,
            lambda obj,id:self.removed.append(id),sample,self.records.append,self.errors.append)
        return self.observer
    def test_trailing_silence_is_included_without_another_callback(self):
        self.assertEqual(wrapper.stale_bound(.05,10.,110.),100.)
        self.assertEqual(wrapper.stale_bound(12.,109.,110.),12.)
        self.assertEqual(wrapper.stale_bound(0.,None,110.),0.)
    def test_count_only_no_decoder_required_and_draw_not_consumed(self):
        o=self.create()
        for n in range(3):self.handlers['display-invalidate'](self.channel,n,0,20,10)
        self.assertFalse(self.handlers['draw'](self.display,None))
        self.assertEqual(o.summary()['invalidate_callbacks'],3)
        self.assertEqual(o.summary()['widget_draw_callbacks'],1)
        self.assertEqual(len(self.records),6);self.assertFalse(self.errors)
        o.close();o.close();self.assertCountEqual(self.removed,['draw','display-invalidate'])
        o.invalidate(self.channel,0,0,1,1);self.assertEqual(len(self.records),6)
    def test_synchronous_roi_copies_before_producer_reuses_buffer(self):
        sequence=[1];seen=[]
        roi=Mock()
        def snapshot(display,scale):
            self.assertEqual(scale,1);width,height=640,480;raw=bytearray(width*height*4)
            band=producer.band(token,NONCE,sequence[0]);off=64*width*4;raw[off:off+len(band)]=band
            return dict(pixels=bytes(raw),width=width,height=height,stride=width*4,channels=4,surface_width=width,surface_height=height)
        roi.snapshot.side_effect=snapshot
        def sample(display,trigger):
            self.assertEqual(trigger,'display-invalidate')
            seen.append(wrapper.sample_display(display,token,NONCE,roi)['sequence'])
        o=self.create(sample)
        for n in [1,2,2,4]:
            sequence[0]=n;o.invalidate(self.channel,16,64,304,96)
            sequence[0]=999  # Subsequent decoder/producer operation after callback.
        self.assertEqual(seen,[1,2,2,4]);self.assertEqual(o.invalidations,4)
        self.assertFalse(self.errors);self.assertGreater(o.callback_seconds,0)
    def test_changed_channel_refused(self):
        sample=Mock();o=self.create(sample);o.invalidate(object(),0,0,1,1)
        sample.assert_not_called();self.assertEqual(len(self.errors),1);self.assertEqual(o.invalidations,0)
    def test_reentrant_callback_is_rejected_without_double_completion(self):
        o=self.create(lambda *_:self.observer.invalidate(self.channel,0,0,1,1))
        o.invalidate(self.channel,0,0,1,1)
        self.assertEqual(o.invalidations,1);self.assertEqual(o.completed_callbacks,1)
        self.assertEqual(len(self.errors),1);self.assertFalse(o.active)
    def test_malformed_rectangle_refused(self):
        sample=Mock();o=self.create(sample);o.invalidate(self.channel,0,0,0,1)
        sample.assert_not_called();self.assertEqual(len(self.errors),1)
    def test_close_during_decode_does_not_write_closed_stream(self):
        o=self.create(lambda *_:self.observer.close());o.invalidate(self.channel,0,0,1,1)
        self.assertEqual([x['event'] for x in self.records],['display-invalidate']);self.assertTrue(o.closed)
    def test_partial_attach_failure_disconnects_first_handler(self):
        removed=[]
        def connect(obj,name,cb):
            if name=='draw':raise RuntimeError('draw unavailable')
            return 12
        with self.assertRaisesRegex(RuntimeError,'draw unavailable'):
            wrapper.EventObserver(object(),object(),connect,lambda obj,i:removed.append(i),None,Mock(),Mock())
        self.assertEqual(removed,[12])
    def test_exact_existing_channel_selection_and_ambiguity(self):
        class Channel:
            def __init__(self,id):self.id=id
            def get_property(self,name):return self.id
        chosen=Channel(4);session=Mock();session.get_channels.return_value=[Channel(0),chosen,object()]
        display=Mock();display.get_property.side_effect=lambda name:session if name=='session' else 4
        self.assertIs(wrapper.matching_display_channel(display,Channel),chosen)
        session.get_channels.return_value=[chosen,Channel(4)]
        with self.assertRaisesRegex(ValueError,'exactly one'):wrapper.matching_display_channel(display,Channel)
        session.get_channels.return_value=[]
        with self.assertRaises(ValueError):wrapper.matching_display_channel(display,Channel)

if __name__=='__main__':unittest.main()
