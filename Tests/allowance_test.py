#!/usr/bin/env python3
"""Exercise the packaged account reader with a fake Codex process, never real auth."""
import json
import os
from pathlib import Path
import queue
import subprocess
import tempfile
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / 'build/marketplace/plugins/cost-calculator/bin/cost-calculator'


class Client:
    def __init__(self, env):
        self.p = subprocess.Popen([str(SERVER)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE, text=True, env=env)
        self.ident = 0
        self.messages = queue.Queue()
        threading.Thread(target=self.read, daemon=True).start()
        self.call('initialize', {'clientInfo': {'name': 'test', 'version': '1'}})

    def read(self):
        for line in self.p.stdout:
            self.messages.put(json.loads(line))

    def send(self, method, params):
        self.ident += 1
        self.p.stdin.write(json.dumps(dict(jsonrpc='2.0', id=self.ident, method=method, params=params))+'\n')
        self.p.stdin.flush()
        return self.ident

    def call(self, method, params):
        ident = self.send(method, params)
        item = self.messages.get(timeout=22)
        assert item['id'] == ident, item
        return item

    def allowance(self, **args):
        result = self.call('tools/call', dict(name='read_allowance', arguments=args))['result']
        assert not result['isError']
        value = result['structuredContent']
        assert json.loads(result['content'][0]['text']) == value
        assert value['scope'] == 'account' and value['source'] == 'codex-app-server'
        assert 'SECRET' not in json.dumps(value)
        return value

    def close(self):
        self.p.stdin.close()
        assert self.p.wait(timeout=4) == 0, self.p.stderr.read()


with tempfile.TemporaryDirectory(prefix='token-allowance-', dir='/private/tmp') as directory:
    root = Path(directory)
    script = root / 'codex'
    script.write_text('''#!/usr/bin/env python3
import json, sys, time
from pathlib import Path
root=Path(__file__).parent
config=json.loads((root/'response.json').read_text())
with (root/'starts').open('a') as f: f.write('start\\n')
assert sys.argv[1:]==['app-server','--listen','stdio://']
if config.get('exit'): sys.exit(1)
for line in sys.stdin:
    m=json.loads(line)
    with (root/'requests').open('a') as f: f.write(json.dumps(m)+'\\n')
    method=m.get('method')
    if method=='initialize':
        print(json.dumps(dict(id=m['id'],result={})),flush=True)
    elif method=='initialized': pass
    elif method=='account/rateLimits/read':
        if config.get('hang'): time.sleep(60)
        time.sleep(config.get('delay',0))
        if config.get('error'):
            print(json.dumps(dict(id=m['id'],error=dict(code=-32000,message='SECRET raw auth details'))),flush=True)
        else:
            print(json.dumps(dict(id=900,method='untrusted/action',params={})),flush=True)
            print(json.dumps(dict(id=m['id'],result=config.get('result',{}))),flush=True)
    elif method is not None: raise AssertionError(method)
''')
    script.chmod(0o755)
    env = dict(os.environ, CODEX_HOME=directory, COST_CALCULATOR_CODEX_BIN=str(script))

    def configure(**value):
        (root / 'response.json').write_text(json.dumps(value))

    def starts():
        return len((root / 'starts').read_text().splitlines())

    configure(result={'rateLimits': {'primary': {'usedPercent': 99}}, 'rateLimitsByLimitId': {
        'codex': {'primary': {'usedPercent': 29, 'windowDurationMins': 10080, 'resetsAt': 1900000000}, 'secondary': None},
        'another': {'limitName': 'Another model', 'primary': {'usedPercent': 0, 'windowDurationMins': 300},
                    'secondary': {'usedPercent': None, 'resetsAt': 1900000100}}
    }, 'accountId': 'SECRET', 'credits': {'balance': 'SECRET'}})
    client = Client(env)
    first = client.allowance()
    assert first['status'] == 'available'
    assert [w['remainingPercent'] for w in first['windows']] == [71, 100, None]
    assert first['windows'][0]['windowDurationMins'] == 10080
    assert first['windows'][1]['resetsAt'] is None
    assert first['windows'][2]['windowDurationMins'] is None
    assert starts() == 1

    configure(error=True)
    assert client.allowance() == first and starts() == 1  # Cached, even if the network would fail.
    stale = client.allowance(refresh=True)
    assert stale['status'] == 'stale' and stale['windows'] == first['windows']
    assert stale['observedAt'] == first['observedAt'] and starts() == 2
    assert client.allowance() == stale and starts() == 2

    configure(result={'rateLimits': {'limitId': 'codex', 'primary': {'usedPercent': 120, 'windowDurationMins': 300},
                                    'secondary': {'usedPercent': -3, 'windowDurationMins': 10080}}})
    normalized = client.allowance(refresh=True)
    assert normalized['status'] == 'available'
    assert [w['remainingPercent'] for w in normalized['windows']] == [0, 100]

    configure(result={'rateLimits': {'primary': {'usedPercent': True, 'windowDurationMins': -1, 'resetsAt': False},
                                    'secondary': {'usedPercent': '30', 'windowDurationMins': 0, 'resetsAt': -10}}})
    missing = client.allowance(refresh=True)
    assert missing['status'] == 'unavailable'
    assert all(w['remainingPercent'] is None and w['resetsAt'] is None and w['windowDurationMins'] is None for w in missing['windows'])
    configure(result={'rateLimits': {'primary': None, 'secondary': None}})
    absent = client.allowance(refresh=True)
    assert absent['status'] == 'unavailable' and absent['windows'] == []
    for arguments in ({'refresh': 1}, {'refresh': 'true'}, {'range': 'day'}, {'refresh': None}):
        assert client.call('tools/call', dict(name='read_allowance', arguments=arguments))['error']['code'] == -32602

    configure(delay=1, result={'rateLimits': {'primary': {'usedPercent': 100, 'windowDurationMins': 300}}})
    allowance_id = client.send('tools/call', dict(name='read_allowance', arguments={'refresh': True}))
    local_id = client.send('tools/call', dict(name='list_usage', arguments={'range': 'day'}))
    local = client.messages.get(timeout=2)
    assert local['id'] == local_id and local['result']['structuredContent']['groups'] == []
    remote = client.messages.get(timeout=3)
    assert remote['id'] == allowance_id
    assert remote['result']['structuredContent']['windows'][0]['remainingPercent'] == 0

    configure(exit=True)
    assert client.allowance(refresh=True)['status'] == 'stale'
    configure(hang=True)
    start = time.monotonic()
    timeout = client.allowance(refresh=True)
    assert timeout['status'] == 'stale' and 'did not respond' in timeout['message']
    assert 14 <= time.monotonic()-start < 19
    client.close()
    requests = [json.loads(line) for line in (root / 'requests').read_text().splitlines()]
    assert {r.get('method') for r in requests if 'method' in r} == {'initialize', 'initialized', 'account/rateLimits/read'}
    assert any(r.get('id') == 900 and r.get('error', {}).get('code') == -32601 for r in requests)

    unavailable = Client(dict(env, COST_CALCULATOR_CODEX_BIN=str(root / 'missing-codex')))
    assert unavailable.allowance()['status'] == 'unavailable'
    assert unavailable.allowance()['windows'] == []
    unavailable.close()

print('PASS: account windows, percentage math, missing/invalid data, multiple limits, cache, stale readings, timeout/exit cleanup, concurrent token reads, and read-only protocol')
