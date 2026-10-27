#!/usr/bin/env python3
"""Development MCP Apps host for the independent Token Usage plugin."""
import argparse
import json
import os
from pathlib import Path
import queue
import secrets
import signal
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / 'build/marketplace/plugins/cost-calculator/bin/cost-calculator'
URI = 'ui://cost-calculator/calculator-v1.html'


class MCP:
    def __init__(self):
        self.process = subprocess.Popen([str(SERVER)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        stderr=subprocess.DEVNULL, text=True, env=os.environ.copy())
        self.pending = {}
        self.stopped = False
        self.lock = threading.Lock()
        self.ident = 0
        threading.Thread(target=self.read, daemon=True).start()
        self.request('initialize', {'protocolVersion': '2025-06-18', 'capabilities': {},
                                   'clientInfo': {'name': 'cost-calculator-preview', 'version': '1'}})
        self.html = self.request('resources/read', {'uri': URI})['contents'][0]['text']

    def read(self):
        for line in self.process.stdout:
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            with self.lock:
                waiting = self.pending.get(item.get('id'))
            if waiting is not None:
                waiting.put(item)
        with self.lock:
            self.stopped = True
            waiting = list(self.pending.values())
        for response in waiting:
            response.put(None)

    def request(self, method, params):
        with self.lock:
            if self.stopped:
                raise RuntimeError('The native plugin process stopped.')
            self.ident += 1
            ident = self.ident
            response = queue.Queue()
            self.pending[ident] = response
            try:
                self.process.stdin.write(json.dumps({'jsonrpc': '2.0', 'id': ident,
                                                    'method': method, 'params': params}) + '\n')
                self.process.stdin.flush()
            except Exception:
                self.pending.pop(ident, None)
                raise
        try:
            item = response.get(timeout=90)
            if item is None:
                raise RuntimeError('The native plugin process stopped.')
            if 'error' in item:
                raise RuntimeError(item['error']['message'])
            return item['result']
        finally:
            with self.lock:
                self.pending.pop(ident, None)

    def close(self):
        self.process.stdin.close()
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.terminate()
            self.process.wait(timeout=5)


HOST = '''<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Token Usage — live preview</title>
<style>
:root{color-scheme:light dark}*{box-sizing:border-box}body{margin:0;background:#edf1ed;color:#68736d;font:12px -apple-system,BlinkMacSystemFont,sans-serif;padding:22px}
iframe{display:block;width:100%;max-width:960px;min-height:510px;margin:auto;border:1px solid #dce4dd;border-radius:12px;background:#fafbf9}
@media(prefers-color-scheme:dark){body{background:#101411;color:#9aa79f}iframe{border-color:#303b34;background:#151a18}}
@media(max-width:500px){body{padding:10px}}
</style>
<iframe id="dashboard" title="Token Usage" sandbox="allow-scripts allow-same-origin" src="__BASE__/ui"></iframe>
<script>
const frame = document.getElementById('dashboard');
const reply = value => frame.contentWindow.postMessage({jsonrpc:'2.0',...value}, location.origin);
window.addEventListener('message', async event => {
  if (event.source !== frame.contentWindow || event.origin !== location.origin || event.data?.jsonrpc !== '2.0') return;
  const {id,method,params} = event.data;
  if (method === 'ui/notifications/size-changed') { frame.style.height = Math.min(1100,Math.max(480,Number(params?.height)||480))+2+'px'; return; }
  if (id === undefined) return;
  try {
    if (method === 'ui/initialize') {
      reply({id,result:{protocolVersion:'2026-01-26',hostInfo:{name:'Local plugin preview',version:'1'},hostCapabilities:{serverTools:{}},hostContext:{theme:matchMedia('(prefers-color-scheme:dark)').matches?'dark':'light',displayMode:'inline'}}});
    } else if (method === 'tools/call') {
      const response = await fetch('__BASE__/rpc',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({method,params})});
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || 'The local preview could not refresh.');
      reply({id,result});
    } else reply({id,error:{code:-32601,message:'This preview does not support '+method}});
  } catch (error) { reply({id,error:{code:-32603,message:error.message}}); }
});
matchMedia('(prefers-color-scheme:dark)').addEventListener('change', event => reply({method:'ui/notifications/host-context-changed',params:{theme:event.matches?'dark':'light'}}));
</script></html>'''


def main():
    parser = argparse.ArgumentParser(description='Independent Token Usage preview')
    parser.add_argument('--port', type=int, default=61960, help='Loopback preview port (default: 61960)')
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error('--port must be between 1 and 65535')
    if not SERVER.exists():
        parser.error('Build the plugin first with ./build.sh')
    client = MCP()
    base = '/' + secrets.token_urlsafe(24)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def respond(self, status, content, mime='application/json'):
            data = content.encode()
            self.send_response(status)
            self.send_header('Content-Type', mime + '; charset=utf-8')
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.send_header('Content-Security-Policy', "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; frame-src 'self'; connect-src 'self'; frame-ancestors 'self'; base-uri 'none'; form-action 'none'")
            self.end_headers()
            self.wfile.write(data)

        def valid_host(self):
            return self.headers.get('Host') == f'127.0.0.1:{self.server.server_port}'

        def do_GET(self):
            if not self.valid_host():
                self.respond(403, '{"error":"Invalid host"}')
            elif self.path == base + '/':
                self.respond(200, HOST.replace('__BASE__', base), 'text/html')
            elif self.path == base + '/ui':
                self.respond(200, client.html, 'text/html')
            else:
                self.respond(404, '{"error":"Not found"}')

        def do_POST(self):
            origin = f'http://127.0.0.1:{self.server.server_port}'
            if not self.valid_host() or self.path != base + '/rpc' or self.headers.get('Origin') != origin:
                self.respond(403, '{"error":"Invalid origin or endpoint"}')
                return
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 < length <= 65536 or self.headers.get_content_type() != 'application/json':
                    raise ValueError('Invalid request body')
                body = json.loads(self.rfile.read(length))
                params = body.get('params', {})
                if body.get('method') != 'tools/call' or params.get('name') not in {'show_calculator', 'list_usage', 'read_usage_detail', 'read_allowance'}:
                    raise ValueError('Only the Token Usage tool is available')
                if not isinstance(params.get('arguments', {}), dict):
                    raise ValueError('Arguments must be an object')
                result = client.request('tools/call', params)
                self.respond(200, json.dumps(result))
            except (ValueError, TypeError, AttributeError) as error:
                self.respond(400, json.dumps({'error': str(error)}))
            except Exception as error:
                self.respond(502, json.dumps({'error': str(error)}))

    try:
        with ThreadingHTTPServer(('127.0.0.1', args.port), Handler) as http:
            print(f'http://127.0.0.1:{http.server_port}{base}/', flush=True)
            def stop(signum, frame):
                raise KeyboardInterrupt
            signal.signal(signal.SIGTERM, stop)
            http.serve_forever()
    except KeyboardInterrupt:
        pass
    except OSError as error:
        parser.exit(1, f'Could not start Token Usage on port {args.port}: {error}. Choose another port with --port. No existing server was changed.\n')
    finally:
        client.close()


if __name__ == '__main__':
    main()
