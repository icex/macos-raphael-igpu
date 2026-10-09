import importlib.util,pathlib,tempfile,time,http.client,socket,unittest
p=pathlib.Path(__file__).resolve().parents[1]/'tools/vbox-root-relay.py';s=importlib.util.spec_from_file_location('relay',p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
class RelayTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.ok=True
  self.r=m.Relay(self.tmp.name,'a'*32,time.monotonic()+15,lambda:self.ok,port=0);self.r.start();self.port=self.r.server_port
 def tearDown(self):self.r.close();self.tmp.cleanup()
 def req(self,method,path,body=None,headers={}):
  c=http.client.HTTPConnection('127.0.0.1',self.port,timeout=4);c.request(method,path,body,headers);r=c.getresponse();v=(r.status,r.read());c.close();return v
 def test_once_and_success(self):
  self.assertEqual(self.req('GET','/foreign')[0],404)
  a=self.req('GET','/cmd');self.assertEqual(a,(200,m.payload('a'*32)))
  self.assertEqual(self.req('GET','/cmd'),(200,b''))
  b=('RGPU_BEGIN '+'a'*32+'\n0\nboot\nRGPU_END '+'a'*32+'\n').encode()
  self.assertEqual(self.req('POST','/out',b)[0],200);self.assertEqual(self.req('POST','/out',b)[0],403)
  self.assertEqual((pathlib.Path(self.tmp.name)/'relay-result.txt').read_bytes(),b)
 def test_refusal_paths(self):
  self.assertEqual(self.req('POST','/out',b'bad')[0],403)
  self.req('GET','/cmd');self.assertEqual(self.req('POST','/wrong',b'bad')[0],404)
  self.assertEqual(self.req('POST','/out',b'bad')[0],422)
  self.assertEqual(self.req('POST','/out',b'',{'Content-Length':str(m.MAX+1)})[0],413)
  self.ok=False;self.assertEqual(self.req('POST','/out',b'bad')[0],403)
 def test_expired_and_scope_changed(self):
  self.ok=False;self.assertEqual(self.req('GET','/cmd')[0],403);self.assertFalse(self.r.sent)
  self.ok=True;self.r.deadline=time.monotonic()-1;self.assertFalse(self.r.valid())
 def test_collision_and_nonce(self):
  with self.assertRaises(OSError):m.Relay(self.tmp.name,'a'*32,time.monotonic()+2,lambda:True,port=self.port)
  with self.assertRaises(ValueError):m.payload('bad;cmd')
