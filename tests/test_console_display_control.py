import importlib.util
import os
from pathlib import Path
import socket
import tempfile
import threading
import unittest

spec=importlib.util.spec_from_file_location('display_control',Path(__file__).resolve().parents[1]/'tools/console-display-control.py')
control=importlib.util.module_from_spec(spec);spec.loader.exec_module(control)

class ControlTests(unittest.TestCase):
    def exchange(self,reply,*,scale=2,width=2468,height=1484):
        with tempfile.TemporaryDirectory() as temporary:
            directory=Path(temporary).resolve();endpoint=directory/'control.sock'
            errors=[]
            with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as listener:
                listener.bind(str(endpoint));endpoint.chmod(0o600);listener.listen(1);listener.settimeout(3)
                def serve():
                    try:
                        with listener.accept()[0] as peer:
                            peer.settimeout(3);data=bytearray()
                            size=20 if scale==2 else 24
                            while len(data)<size:
                                chunk=peer.recv(min(3,size-len(data)))
                                if not chunk:raise EOFError('missing request')
                                data.extend(chunk)
                            values=(control.REQUEST if scale==2 else control.REQUEST_V2).unpack(data)
                            magic,version,sequence,w,h=values[:5]
                            self.assertEqual((magic,version,w,h),(control.MAGIC,1 if scale==2 else 2,width,height))
                            if scale==1:self.assertEqual(values[5],1)
                            response=reply(sequence)
                            # Split the wire reply to exercise partial reads.
                            peer.sendall(response[:7]);peer.sendall(response[7:])
                    except Exception as error:errors.append(error)
                thread=threading.Thread(target=serve);thread.start()
                try:return control.request(directory,width,height,scale=scale)
                finally:
                    thread.join(timeout=4)
                    self.assertFalse(thread.is_alive())
                    if errors:raise errors[0]

    def response(self,seq,status=0,width=2468,flags=3):
        return control.REPLY.pack(control.MAGIC,1,seq,status,123,width,1484,1234,742,flags)

    def test_real_unix_peer_fragmented_verified_reply(self):
        row=self.exchange(lambda seq:self.response(seq))
        self.assertTrue(row['passed']);self.assertTrue(row['dynamic_mode_added'])
        self.assertEqual((row['pixel_width'],row['pixel_height']),(2468,1484))

    def test_v2_odd_one_x_real_socket_exchange(self):
        row=self.exchange(lambda seq:control.REPLY.pack(control.MAGIC,2,seq,0,123,1235,743,1235,743,3),
                          scale=1,width=1235,height=743)
        self.assertTrue(row['passed'])
        self.assertEqual((row['width'],row['height']),(1235,743))

    def test_v2_refusal_can_report_unchanged_old_geometry(self):
        row=self.exchange(lambda seq:control.REPLY.pack(control.MAGIC,2,seq,2,123,1920,1080,960,540,0),
                          scale=1,width=1235,height=743)
        self.assertFalse(row['passed'])
        self.assertEqual(row['status'],2)

    def test_exact_logical_dimensions_required_for_both_versions(self):
        for scale,pw,ph,lw,lh in [(2,2468,1484,2468,1484),(2,2468,1484,1234,741),
                                 (1,1235,743,617,371),(1,1235,743,1235,742)]:
            with self.subTest(scale=scale,lw=lw,lh=lh),self.assertRaisesRegex(ValueError,'geometry'):
                self.exchange(lambda seq:control.REPLY.pack(control.MAGIC,1 if scale==2 else 2,seq,0,123,pw,ph,lw,lh,0),
                              scale=scale,width=pw,height=ph)

    def test_reply_version_must_match_request(self):
        for scale,reply_version in [(1,1),(2,2),(1,3)]:
            with self.subTest(scale=scale,version=reply_version),self.assertRaisesRegex(ValueError,'identity'):
                self.exchange(lambda seq:control.REPLY.pack(control.MAGIC,reply_version,seq,0,123,2468,1484,2468//scale,1484//scale,0),scale=scale)

    def test_scale_and_geometry_admission(self):
        control.geometry(1235,743,scale=1)
        for scale in (0,3,True,1.0,'1'):
            with self.subTest(scale=scale),self.assertRaises(ValueError):control.geometry(1235,743,scale=scale)
        for w,h in [(639,743),(1235,479),(3841,743),(1235,2161)]:
            with self.subTest(w=w,h=h),self.assertRaises(ValueError):control.geometry(w,h,scale=1)
        with self.assertRaises(ValueError):control.geometry(1235,743,scale=2)

    def test_refusal_is_not_success(self):
        row=self.exchange(lambda seq:self.response(seq,status=2))
        self.assertFalse(row['passed']);self.assertEqual(row['status'],2)

    def test_wrong_sequence(self):
        with self.assertRaisesRegex(ValueError,'identity'):
            self.exchange(lambda seq:self.response(seq^1))

    def test_wrong_geometry(self):
        with self.assertRaisesRegex(ValueError,'geometry'):
            self.exchange(lambda seq:self.response(seq,width=2560))

    def test_truncated_reply(self):
        with self.assertRaises(EOFError):self.exchange(lambda seq:self.response(seq)[:-1])

    def test_extra_reply(self):
        with self.assertRaisesRegex(ValueError,'extra'):
            self.exchange(lambda seq:self.response(seq)+b'x')

    def test_insecure_directory_refused_before_connect(self):
        with tempfile.TemporaryDirectory() as temporary:
            path=Path(temporary).resolve();path.chmod(0o755)
            with self.assertRaisesRegex(ValueError,'ownership'):
                control.request(path,2468,1484)

    def test_invalid_dimensions(self):
        for width,height in [(True,480),(639,480),(640,479),(3842,2160),(640,2162),(2467,1484)]:
            with self.subTest(width=width,height=height),self.assertRaises(ValueError):
                control.geometry(width,height)

if __name__=='__main__':unittest.main()
