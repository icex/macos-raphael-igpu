import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
import wave
import subprocess
from unittest.mock import patch

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

    def no_op_restore(self,after_first=None,persistent=False):
        self.route.start()
        original=self.backend.pulse;attempts=[]
        def pulse(*args):
            if args[0]=='move-sink-input':
                attempts.append(args)
                if len(attempts)==1 or persistent:
                    self.backend.calls.append(args)
                    if after_first:after_first()
                    return ''
            return original(*args)
        self.backend.pulse=pulse
        return attempts
    def test_successful_noop_reissues_once_with_durable_results(self):
        attempts=self.no_op_restore();self.route.restore()
        self.assertEqual(len(attempts),2);self.assertTrue(self.route.state['restored'])
        rows=json.loads(self.route.path.read_text())['restore_attempts']
        self.assertEqual([r['status'] for r in rows],['observed-still-owned','observed-original'])
        self.assertEqual([r['command']['returncode'] for r in rows],[0,0])
        self.assertTrue(all(r['end']>=r['start'] for r in rows))
    def test_persistent_noop_refuses_without_unloading(self):
        attempts=self.no_op_restore(persistent=True)
        with self.assertRaisesRegex(RuntimeError,'bounded reissue'):self.route.restore()
        self.assertEqual(len(attempts),2);self.assertFalse(self.route.state['restored'])
        self.assertFalse(any(c[0]=='unload-module' for c in self.backend.calls))
    def test_retry_revalidates_all_foreign_and_route_guards(self):
        def mutate(kind):
            d=self.backend.data
            if kind=='foreign':
                row=copy.deepcopy(d['inputs'][0]);row['index']=99;d['inputs'].append(row)
            elif kind=='third':d['inputs'][0]['sink']=99
            elif kind=='stream':d['inputs'][0]['properties']['object.serial']='new'
            elif kind=='client':d['clients'][0]['properties']=dict(d['clients'][0]['properties'],**{'object.serial':'new'})
            elif kind=='default':d['defaults'][0]='changed'
            elif kind=='sink':d['sinks'][0]['properties']['object.serial']='new'
            elif kind=='module':d['modules'][-1]['argument']='changed'
            elif kind=='mute':d['inputs'][0]['mute']=True
            elif kind=='vm':self.backend.vm_ok=False
        for kind in ('foreign','third','stream','client','default','sink','module','mute','vm'):
            with self.subTest(kind=kind):
                self.backend=FakeBackend();self.route=tool.Route(self.backend,IDENTITY,Path(self.tmp.name)/'route.json')
                attempts=self.no_op_restore(lambda:mutate(kind))
                with self.assertRaises(RuntimeError):self.route.restore()
                self.assertEqual(len(attempts),1)
                self.assertFalse(any(c[0]=='unload-module' for c in self.backend.calls))
    def test_changed_default_refuses_before_first_restore_move(self):
        self.route.start();self.backend.calls=[];self.backend.data['defaults'][0]='changed'
        with self.assertRaisesRegex(RuntimeError,'defaults changed'):self.route.restore()
        self.assertEqual(self.backend.calls,[])
    def test_restore_deadline_applies_without_capture_alarm(self):
        self.route.start();self.backend.calls=[]
        with patch.object(tool.time,'monotonic',return_value=100):
            with self.assertRaises(TimeoutError):self.route.restore(deadline=99)
        self.assertFalse(self.backend.calls);self.assertIsNone(self.backend.cleanup_deadline)
    def test_elapsed_deadline_prevents_reissue(self):
        clock=[100.0]
        attempts=self.no_op_restore(lambda:clock.__setitem__(0,116.0))
        with patch.object(tool.time,'monotonic',side_effect=lambda:clock[0]):
            with self.assertRaises(TimeoutError):self.route.restore()
        self.assertEqual(len(attempts),1)
        self.assertFalse(any(c[0]=='unload-module' for c in self.backend.calls))
        self.assertEqual(self.route.state['restore_attempts'][0]['error_type'],'TimeoutError')
    def test_failed_move_is_recorded_and_never_reissued(self):
        self.route.start();self.backend.calls=[]
        def failed(*args):
            self.backend.calls.append(args)
            self.backend.last_command_result=dict(outcome='returned',returncode=1,stdout='',stderr='move refused')
            raise subprocess.CalledProcessError(1,['pactl',*map(str,args)],'', 'move refused')
        self.backend.pulse=failed
        with self.assertRaises(subprocess.CalledProcessError):self.route.restore()
        self.assertEqual(len(self.backend.calls),1)
        record=json.loads(self.route.path.read_text())['restore_attempts'][0]
        self.assertEqual(record['command']['returncode'],1)
        self.assertEqual(record['command']['stderr'],'move refused')
        self.assertEqual(record['status'],'refused')

    def test_backend_commands_use_remaining_deadline_and_retain_result(self):
        backend=tool.Backend();backend.cleanup_deadline=101
        result=subprocess.CompletedProcess(['pactl'],0,'result','notice')
        with patch.object(tool.time,'monotonic',return_value=100),patch.object(tool.subprocess,'run',return_value=result) as run:
            self.assertEqual(backend.pulse('move-sink-input',31,'original'),'result')
        self.assertEqual(run.call_args.kwargs['timeout'],1)
        self.assertEqual(backend.last_command_result['stderr'],'notice')
        with patch.object(tool.time,'monotonic',return_value=102),patch.object(tool.subprocess,'run') as run:
            with self.assertRaises(TimeoutError):backend.pulse('unload-module',50)
            run.assert_not_called()


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


class ModuleInventoryTests(unittest.TestCase):
    def test_realistic_multiline_and_empty_arguments(self):
        value='1\tlibpipewire-module-rt\t{\n nice.level = -11\n\t}\t\n536870912\tmodule-always-sink\t\t\n'
        self.assertEqual(tool.parse_modules_short(value),[
            dict(index=1,name='libpipewire-module-rt',argument='{\n nice.level = -11\n\t}'),
            dict(index=536870912,name='module-always-sink',argument='')])
    def test_owned_module_id_is_not_position_or_object_id(self):
        self.assertEqual(tool.parse_modules_short('536870919\tmodule-null-sink\tsink_name=rgpu_audio_abc format=s16le\t0')[0]['index'],536870919)
    def test_same_name_distinct_id_is_preserved_for_ownership_checks(self):
        rows=tool.parse_modules_short('12\tmodule-null-sink\tsink_name=x\t\n13\tmodule-null-sink\tsink_name=x\t')
        with self.assertRaisesRegex(RuntimeError,'ambiguous'):
            tool.unique(rows,lambda m:m['argument']=='sink_name=x','owned module')
    def test_malformed_and_duplicate_refuse(self):
        for value in ('x\tmodule-null-sink\t\t','1\tmodule-null-sink\t',
                      '1\tmodule-null-sink\t\t\n1\tmodule-null-sink\t\t',
                      '4294967296\tmodule-null-sink\t\t',
                      '1\tmodule-null-sink\t\tbad',
                      '1\tmodule-null-sink\t{\n2\tmodule-fake\tx\t\n}\t'):
            with self.subTest(value=value),self.assertRaises(RuntimeError):tool.parse_modules_short(value)
    def test_backend_uses_short_inventory_with_trailing_tabs(self):
        class ReadOnly(tool.Backend):
            def command(self,args):
                if args==['pactl','list','short','modules']:return '9\tmodule-null-sink\tsink_name=x\t'
                if args[1:3]==['-f','json']:return '[]'
                if args[1] in ('get-default-sink','get-default-source'):return 'default'
                raise AssertionError(args)
        self.assertEqual(ReadOnly().snapshot()['modules'][0]['index'],9)
