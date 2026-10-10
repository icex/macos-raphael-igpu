import importlib.util
import json
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('pipeline',Path(__file__).resolve().parents[1]/'tools/qemu-spice-pipeline-analysis.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

class PipelineTiming(unittest.TestCase):
    def test_complete_records_and_reject_malformed(self):
        line='2026-date qemu_spice_diff_timing qid=0 start_us=1000000 w=3840 h=2160 changed=1 diff_us=3'
        self.assertEqual(m.parse_trace(line)[0]['host_seconds'],1.0)
        for text in (line.replace('diff_us=3',''),line.replace('diff_us=3','diff_us=-3'),line.replace('changed=1','changed=2'),'unrelated log'):
            with self.assertRaises(ValueError):m.parse_trace(text)

    def fixture(self, scale=1):
        logical='3840x2160' if scale==1 else '1920x1080'
        source=f'TOKEN nonce=437a0123456789ab duration=60 logical={logical} scale={scale}.0\n'
        source+='MIXED_PHASE index=0 kind=localized first_completed_draw=1\n'
        source+='MIXED_PHASE index=1 kind=full-field first_completed_draw=21\n'
        source+=''.join(f'DRAW {seq} {seq+500}.0\n' for seq in range(1,41))
        records=[dict(event='start',nonce='437a0123456789ab'),dict(event='sample',valid=False,error='no token')]
        trace=[]
        for seq in range(1,41):
            records.append(dict(event='sample',valid=True,sequence=seq,scale=scale,width=3840,height=2160,host_monotonic=1000+seq))
            t=(1000+seq)*1000000
            trace.extend([f'qemu_spice_diff_timing qid=0 start_us={t} w=3840 h=2160 changed=1 diff_us=3',
                          f'qemu_spice_copy_timing qid=0 start_us={t} w=3840 h=2160 alloc_us=2 mirror_us=5 bitmap_us=7',
                          f'qemu_spice_refresh_timing qid=0 start_us={t} hw_us=4 create_us=17 busy=0',
                          f'qemu_spice_command_dequeue qid=0 at_us={t} w=3840 h=2160'])
        records.append(dict(event='finish',nonce='437a0123456789ab',reason='completed',invalid=1,duplicates=0))
        return '\n'.join(trace),'\n'.join(json.dumps(row) for row in records),source

    def test_separate_guest_clock_retina_and_phase_interiors(self):
        for scale in (1,2):
            rows=m.analyze(*self.fixture(scale))
            self.assertEqual(len(rows),2)
            self.assertEqual(rows[1]['kind'],'full-field')
            self.assertEqual(rows[1]['event_counts']['copy_timing'],17)
            self.assertEqual(rows[1]['excluded_interval_crossing'],3)
            self.assertEqual(rows[1]['queue_busy'],0)
            self.assertEqual(rows[1]['timings']['mirror_us']['mean_us'],5)

    def test_post_start_corruption_and_geometry_rejected(self):
        trace,cadence,source=self.fixture()
        for bad in (cadence.replace('"sequence": 10','"sequence": 100'),cadence.replace('"valid": true, "sequence": 10','"valid": false, "sequence": 10'),cadence.replace('"scale": 1','"scale": 2')):
            with self.assertRaises(ValueError):m.analyze(trace,bad,source)

if __name__=='__main__':unittest.main()
