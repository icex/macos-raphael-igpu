#!/usr/bin/env python3
"""Container-side command relay with non-secret reachability telemetry."""
from datetime import datetime, timezone
import http.server
import json
import os


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
    server = Server(('0.0.0.0', 8888), Handler)
    record('server_started')
    server.serve_forever()
