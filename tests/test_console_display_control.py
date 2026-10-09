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
    def exchange(self,reply):
        with tempfile.TemporaryDirectory() as temporary:
            directory=Path(temporary).resolve();endpoint=directory/'control.sock'
            errors=[]
            with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as listener:
                listener.bind(str(endpoint));endpoint.chmod(0o600);listener.listen(1);listener.settimeout(3)
                def serve():
                    try:
                        with listener.accept()[0] as peer:
                            peer.settimeout(3);data=bytearray()
                            while len(data)<20:
                                chunk=peer.recv(20-len(data))
                                if not chunk:raise EOFError('missing request')
                                data.extend(chunk)
                            magic,version,sequence,w,h=control.REQUEST.unpack(data)
                            self.assertEqual((magic,version,w,h),(control.MAGIC,1,2468,1484))
                            response=reply(sequence)
                            # Split the wire reply to exercise partial reads.
                            peer.sendall(response[:7]);peer.sendall(response[7:])
                    except Exception as error:errors.append(error)
                thread=threading.Thread(target=serve);thread.start()
                try:return control.request(directory,2468,1484)
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
