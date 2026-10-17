import http.client
import importlib.util
from pathlib import Path
import tempfile
import threading
import unittest

ROOT = Path(__file__).resolve().parents[1]


class CompatibilityArtifactUploadTests(unittest.TestCase):
    def test_nonce_revocation_no_overwrite_and_path_refusal(self):
        spec = importlib.util.spec_from_file_location('compat_agent',ROOT/'tools/agent-server.py')
        agent = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(agent)
        with tempfile.TemporaryDirectory() as directory:
            agent.D = directory
            agent.EVENTS = str(Path(directory)/'events.jsonl')
            server = agent.Server(('127.0.0.1',0),agent.Handler)
            thread = threading.Thread(target=server.serve_forever)
            thread.start()
            def post(path, data=b'current bytes'):
                connection = http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=3)
                connection.request('POST',path,body=data)
                response = connection.getresponse()
                status = response.status
                response.read()
                connection.close()
                return status
            try:
                nonce = 'b'*32
                path = '/artifact-upload/'+nonce+'/systemkc'
                self.assertEqual(post(path),403)
                permit = Path(directory)/('compat-permit-'+nonce)
                permit.write_text(nonce)
                self.assertEqual(post(path),200)
                artifact = Path(directory)/'upload'/('compat-'+nonce)/'systemkc'
                self.assertEqual(artifact.read_bytes(),b'current bytes')
                self.assertEqual(post(path,b'replacement'),409)
                self.assertEqual(artifact.read_bytes(),b'current bytes')
                self.assertEqual(post('/artifact-upload/'+nonce+'/../../escape'),403)
                permit.unlink()
                self.assertEqual(post('/artifact-upload/'+nonce+'/metaltext'),403)
                self.assertFalse((artifact.parent/'metaltext').exists())
            finally:
                server.shutdown()
                thread.join()
                server.server_close()
