#!/usr/bin/env python3
"""Container-side command relay with non-secret reachability telemetry."""
from datetime import datetime, timezone
import http.server
import json
import os
from pathlib import Path
import re
import tempfile


D = "/run/vm"
CMD, OUT, SEQ = f"{D}/cmd.txt", f"{D}/out.txt", f"{D}/seq.txt"
EVENTS = f"{D}/agent-server-events.jsonl"

AGENT = r"""
while :; do
  c=$(curl -s --max-time 5 http://10.0.2.2:8888/cmd)
  if [ -n "$c" ]; then
    { eval "$c"; } > /tmp/agent.out 2>&1
    curl -s --max-time 20 -X POST --data-binary @/tmp/agent.out http://10.0.2.2:8888/out
  fi
  sleep 1
done
"""


def record(event, **fields):
    row = {'time': datetime.now(timezone.utc).isoformat(), 'event': event, **fields}
    with open(EVENTS, 'a') as stream:
        stream.write(json.dumps(row, sort_keys=True)+'\n')
        stream.flush()
        os.fsync(stream.fileno())


class Handler(http.server.BaseHTTPRequestHandler):
    def _send(self, body=b'', code=200):
        self.send_response(code)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == '/compatibility-upload-version':
            return self._send(b'1')
        if os.environ.get('RGPU_ARTIFACT_ONLY') == '1':
            return self._send(b'artifact receiver only', 404)
        if self.path == '/agent':
            record('guest_agent_script_requested')
            return self._send(AGENT.encode())
        if self.path == '/cmd':
            try:
                with open(CMD) as stream:
                    command = stream.read()
                os.remove(CMD)
            except FileNotFoundError:
                command = ''
            record('guest_command_poll', command_available=bool(command))
            return self._send(command.encode())
        if self.path == '/health':
            return self._send(b'healthy')
        self._send(b'ok')

    def do_POST(self):
        artifact = re.fullmatch(r'/artifact-upload/([0-9a-f]{32})/(systemkc|bootkc|metaltext|vatext|shutdown)', self.path)
        if artifact:
            nonce, key = artifact.groups()
            permit = Path(D) / ('compat-permit-'+nonce)
            def permitted():
                try:
                    return permit.read_text() == nonce
                except FileNotFoundError:
                    return False
            try:
                size = int(self.headers.get('Content-Length', '-1'))
            except ValueError:
                return self._send(b'invalid length', 400)
            if not permitted() or size < 1 or size > 512*1024*1024:
                return self._send(b'no active compatibility permit or invalid size', 403)
            directory = Path(D) / 'upload' / ('compat-'+nonce)
            directory.mkdir(parents=True, exist_ok=True)
            target = directory / key
            if target.exists():
                return self._send(b'identity artifact already exists', 409)
            temporary = None
            try:
                with tempfile.NamedTemporaryFile(dir=directory, delete=False) as stream:
                    temporary = Path(stream.name)
                    remaining = size
                    while remaining:
                        if not permitted():
                            return self._send(b'permit revoked', 403)
                        chunk = self.rfile.read(min(1024*1024, remaining))
                        if not chunk:
                            return self._send(b'truncated artifact', 400)
                        stream.write(chunk)
                        remaining -= len(chunk)
                    stream.flush()
                    os.fsync(stream.fileno())
                if not permitted() or target.exists():
                    return self._send(b'permit revoked or artifact exists', 409)
                # Atomic no-overwrite publication: overlapping requests cannot
                # replace an artifact already bound to this observation nonce.
                try:
                    os.link(temporary, target)
                except FileExistsError:
                    return self._send(b'identity artifact already exists', 409)
                record('compatibility_artifact', nonce=nonce, key=key, bytes=size)
                return self._send(b'stored')
            finally:
                if temporary is not None:
                    temporary.unlink(missing_ok=True)
        if self.path.startswith('/artifact-upload'):
            return self._send(b'invalid artifact identity', 403)
        if os.environ.get('RGPU_ARTIFACT_ONLY') == '1':
            return self._send(b'artifact receiver only', 404)
        size = int(self.headers.get('Content-Length') or 0)
        body = self.rfile.read(size)
        with open(OUT, 'wb') as stream:
            stream.write(body)
        with open(SEQ, 'w') as stream:
            stream.write(str(int(os.path.getmtime(OUT))))
        record('guest_command_result', bytes=len(body))
        self._send(b'ok')

    def log_message(self, *args):
        pass


class Server(http.server.ThreadingHTTPServer):
    allow_reuse_address = True


if __name__ == '__main__':
    server = Server(('0.0.0.0', int(os.environ.get('RGPU_AGENT_PORT', '8888'))), Handler)
    record('server_started')
    server.serve_forever()
