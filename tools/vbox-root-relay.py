#!/usr/bin/env python3
"""One fixed read-only root-agent probe; nonce association is not authentication."""
import hashlib,http.server,json,os,re,socket,threading,time
from pathlib import Path
MAX=8*1024*1024

def payload(nonce):
    if not re.fullmatch('[0-9a-f]{32}',nonce):raise ValueError('invalid nonce')
    return (f"printf 'RGPU_BEGIN {nonce}\\n'; /usr/bin/id -u; /usr/sbin/sysctl -n kern.bootsessionuuid; "
            "/usr/bin/sw_vers -buildVersion; /sbin/ifconfig -a; "
            "/usr/sbin/ioreg -r -c AppleVirtIONetwork -d 2 -w 0; "
            "/usr/sbin/ioreg -r -c IOFramebuffer -d 1 -w 0; "
            f"printf 'RGPU_END {nonce}\\n'\n").encode()

class Relay(http.server.HTTPServer):
    allow_reuse_address=False
    def __init__(self,home,nonce,deadline,verify,port=8888):
        self.home=Path(home);self.nonce=nonce;self.command=payload(nonce)
        self.deadline=deadline;self.verify=verify;self.sent=False;self.received=False
        self.closed=threading.Event()
        super().__init__(('127.0.0.1',port),Handler)
        self.timeout=.2
        self.thread=threading.Thread(target=self.loop,daemon=True)
    def loop(self):
        while not self.closed.is_set() and time.monotonic()<self.deadline:self.handle_request()
        self.server_close()
    def start(self):
        (self.home/'relay-scope.json').write_text(json.dumps(dict(nonce=self.nonce,payload_sha256=hashlib.sha256(self.command).hexdigest(),deadline=self.deadline,scope='fixed read-only probe; nonce association, not authentication'))+'\n')
        self.thread.start()
    def close(self):
        self.closed.set();self.thread.join(timeout=6);self.server_close()
    def valid(self):
        if time.monotonic()>=self.deadline:return False
        try:return bool(self.verify()) and time.monotonic()<self.deadline
        except Exception:return False

class Handler(http.server.BaseHTTPRequestHandler):
    def setup(self):
        super().setup();self.connection.settimeout(min(3,max(.01,self.server.deadline-time.monotonic())))
    def log_message(self,*args):pass
    def reply(self,code,body=b''):
        self.send_response(code);self.send_header('Content-Length',str(len(body)));self.end_headers()
        try:self.wfile.write(body)
        except (BrokenPipeError,ConnectionResetError):pass
    def do_GET(self):
        s=self.server
        if self.path!='/cmd':return self.reply(404)
        if not s.valid():return self.reply(403)
        if s.sent:return self.reply(200)
        s.sent=True # No retries after ambiguous delivery.
        self.reply(200,s.command)
    def do_POST(self):
        s=self.server
        if self.path!='/out':return self.reply(404)
        if not s.sent or s.received or not s.valid():return self.reply(403)
        sizes=self.headers.get_all('Content-Length',[])
        if len(sizes)!=1 or not re.fullmatch('[0-9]+',sizes[0]) or 'Transfer-Encoding' in self.headers:return self.reply(400)
        size=int(sizes[0])
        if size>MAX:return self.reply(413)
        chunks=[]; remaining=size; until=min(s.deadline,time.monotonic()+3)
        try:
            while remaining:
                left=until-time.monotonic()
                if left<=0:raise TimeoutError()
                self.connection.settimeout(left)
                chunk=self.rfile.read1(min(65536,remaining))
                if not chunk:break
                chunks.append(chunk);remaining-=len(chunk)
            body=b''.join(chunks)
        except (TimeoutError,socket.timeout):return self.reply(408)
        if len(body)!=size:return self.reply(400)
        if not body.startswith(f'RGPU_BEGIN {s.nonce}\n0\n'.encode()) or not body.endswith(f'RGPU_END {s.nonce}\n'.encode()):return self.reply(422)
        if not s.valid():return self.reply(403)
        fd=os.open(s.home/'relay-result.txt',os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
        with os.fdopen(fd,'wb') as f:f.write(body);f.flush();os.fsync(f.fileno())
        s.received=True
        self.reply(200,b'ok')
