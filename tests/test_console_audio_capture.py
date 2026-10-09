import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
import wave

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('audio_capture',ROOT/'tools/console-audio-capture.py')
tool=importlib.util.module_from_spec(spec);spec.loader.exec_module(tool)
RUN='a'*32;CID='b'*64
IDENTITY=dict(run_id=RUN,cid=CID,started_at='start',scope={},identity=dict(run_id=RUN,name='rgpu-'+RUN,pid=113,start_ticks=42))

class FakeBackend:
    def __init__(self):
        props={'application.name':'rgpu-'+RUN,'application.process.id':'113','application.process.host':CID[:12],'application.process.binary':'qemu-system-x86_64','media.name':'hda','object.serial':'31'}
        self.data=dict(inputs=[dict(index=31,client='30',sink=10,properties=props,volume={'left':100,'right':100},mute=False)],clients=[dict(index=30,properties=props)],sinks=[dict(index=10,name='original',properties={'object.serial':'10'},owner_module=1)],modules=[dict(index=1,name='existing',argument='')],defaults=['original','mic'])
        self.calls=[];self.fail_move=False;self.lost_create=False;self.vm_ok=True
    def snapshot(self):return copy.deepcopy(self.data)
    def verify_vm(self,identity):tool.require(identity==IDENTITY and self.vm_ok,'VM replaced')
    def pulse(self,*args):
        self.calls.append(args)
        if args[0]=='load-module':
            name=args[2].split('=',1)[1];self.data['modules'].append(dict(index=50,name=args[1],argument=' '.join(args[2:])))
            self.data['sinks'].append(dict(index=51,name=name,properties={'object.serial':'51'},owner_module=50))
            if self.lost_create:raise RuntimeError('lost create reply')
            return '50'
        if args[0]=='move-sink-input':
            sink=next(s for s in self.data['sinks'] if s['name']==args[2]);self.data['inputs'][0]['sink']=sink['index']
            if self.fail_move:raise RuntimeError('lost move reply')
            return ''
        if args[0]=='unload-module':
            self.data['modules']=[m for m in self.data['modules'] if m['index']!=args[1]]
            self.data['sinks']=[s for s in self.data['sinks'] if s.get('owner_module')!=args[1]];return ''
        raise AssertionError(args)

class AudioRouteTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.backend=FakeBackend();self.route=tool.Route(self.backend,IDENTITY,Path(self.tmp.name)/'route.json')
    def test_owned_route_restores_without_defaults_or_volume_writes(self):
        before=copy.deepcopy(self.backend.data);self.route.start();self.route.check();self.route.restore();self.route.restore()
        self.assertEqual(before,self.backend.data);self.assertTrue(self.route.state['restored'])
        self.assertEqual([c[0] for c in self.backend.calls],['load-module','move-sink-input','move-sink-input','unload-module'])
    def test_ambiguous_stream_refuses_before_mutation(self):
        self.backend.data['inputs'].append(copy.deepcopy(self.backend.data['inputs'][0]))
        with self.assertRaisesRegex(RuntimeError,'ambiguous'):self.route.start()
        self.assertFalse(self.backend.calls)
    def test_replaced_stream_is_not_moved_or_unloaded(self):
        self.route.start();self.backend.calls=[];self.backend.data['inputs'][0]['properties']['object.serial']='99'
        with self.assertRaises(RuntimeError):self.route.restore()
        self.assertFalse(self.backend.calls)
    def test_replaced_client_is_not_moved_or_unloaded(self):
        self.route.start();self.backend.calls=[]
        self.backend.data['clients'][0]['properties']=dict(self.backend.data['clients'][0]['properties'],**{'object.serial':'replacement'})
        with self.assertRaisesRegex(RuntimeError,'client replaced'):self.route.restore()
        self.assertFalse(self.backend.calls)
    def test_foreign_stream_on_owned_sink_refuses_cleanup(self):
        self.route.start();other=copy.deepcopy(self.backend.data['inputs'][0]);other['index']=99;self.backend.data['inputs'].append(other)
        self.backend.calls=[]
        with self.assertRaisesRegex(RuntimeError,'foreign'):self.route.restore()
        self.assertFalse(self.backend.calls)
    def test_original_sink_replaced_refuses_move(self):
        self.route.start();self.backend.data['sinks'][0]['properties']['object.serial']='replacement';self.backend.calls=[]
        with self.assertRaises(RuntimeError):self.route.restore()
        self.assertFalse(self.backend.calls)
    def test_lost_create_reply_reconciles_only_owned_module(self):
        self.backend.lost_create=True
        with self.assertRaises(RuntimeError):self.route.start()
        self.route.restore();self.assertTrue(self.route.state['restored']);self.assertEqual(len(self.backend.data['modules']),1)
    def test_lost_move_reply_restores_observed_actual_route(self):
        self.backend.fail_move=True
        with self.assertRaises(RuntimeError):self.route.start()
        self.backend.fail_move=False;self.route.restore();self.assertTrue(self.route.state['restored'])
    def test_replaced_vm_refuses_restore_mutation(self):
        self.route.start();self.backend.vm_ok=False;self.backend.calls=[]
        with self.assertRaises(RuntimeError):self.route.restore()
        self.assertFalse(self.backend.calls)
    def test_module_id_reuse_is_not_unloaded(self):
        self.route.start();self.backend.data['modules'][-1]['argument']='sink_name=other';self.backend.calls=[]
        with self.assertRaises(RuntimeError):self.route.restore()
        self.assertFalse(self.backend.calls)

class AudioAnalysisTests(unittest.TestCase):
    def fixture(self,kind):
        import numpy as np
        rate=48000;t=np.arange(rate*8)/rate;x=np.zeros((len(t),2))
        for lo,hi,channels in [(1,2,[0]),(2.5,3.5,[1]),(4,5,[0,1])]:
            take=(t>=lo)&(t<hi)
            for c in channels:x[take,c]=.02*np.sin(2*np.pi*([997,1499][c])*t[take])
        if kind=='swapped':x=x[:,::-1]
        if kind=='leak':x[:,1]+=x[:,0]*.5
        if kind=='silent':x[:]=0
        if kind=='noise':x+=.001
        path=Path(self.tmp.name)/(kind+'.wav')
        with wave.open(str(path),'wb') as w:
            w.setnchannels(2);w.setsampwidth(2);w.setframerate(rate);w.writeframes((x*32767).astype('<i2').tobytes())
        return path
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
    def test_correct_stereo_sequence_passes(self):self.assertTrue(tool.analyze(self.fixture('valid'))['passed'])
    def test_swapped_leaking_silent_or_noisy_capture_fails(self):
        for kind in ['swapped','leak','silent','noise']:
            with self.subTest(kind=kind),self.assertRaises(RuntimeError):tool.analyze(self.fixture(kind))
