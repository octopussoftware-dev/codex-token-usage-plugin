#!/usr/bin/env python3
"""Smoke-test the independent packaged plugin without reading app data."""
import json
import os
import tempfile
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / 'build/marketplace/plugins/cost-calculator'
SERVER = PACKAGE / 'bin/cost-calculator'
URI = 'ui://cost-calculator/calculator-v1.html'
requests = [
    ('tools/list', {}),
    ('initialize', {'protocolVersion': '2025-06-18', 'capabilities': {}, 'clientInfo': {'name': 'test', 'version': '1'}}),
    ('tools/list', {}),
    ('resources/list', {}),
    ('resources/read', {'uri': URI}),
    ('tools/call', {'name': 'show_calculator', 'arguments': {}}),
    ('tools/call', {'name': 'list_agents', 'arguments': {}}),
    ('tools/call', {'name': 'show_calculator', 'arguments': {'unexpected': 1}}),
    ('tools/call', {'name': 'show_calculator', 'arguments': []}),
    ('resources/read', {'uri': 'file:///etc/passwd'}),
    ('ping', {}),
]
wire = ''.join(json.dumps({'jsonrpc': '2.0', 'id': index, 'method': method, 'params': params}) + '\n'
               for index, (method, params) in enumerate(requests))
with tempfile.TemporaryDirectory(prefix='cost-mcp-', dir='/private/tmp') as home:
    process = subprocess.run([str(SERVER)], input=wire, capture_output=True, text=True, timeout=10, check=True, env=dict(os.environ, CODEX_HOME=home))
responses = [json.loads(line) for line in process.stdout.splitlines()]
assert [r['id'] for r in responses] == list(range(len(requests)))
assert responses[0]['error']['code'] == -32000
assert responses[1]['result']['serverInfo'] == {'name': 'cost-calculator', 'version': '0.7.8'}
tools = responses[2]['result']['tools']
assert [tool['name'] for tool in tools] == ['show_calculator', 'list_usage', 'read_usage_detail', 'read_allowance']
assert tools[-1]['annotations']['readOnlyHint'] and tools[-1]['annotations']['openWorldHint']
assert tools[0]['annotations']['readOnlyHint']
assert tools[0]['_meta']['ui']['resourceUri'] == URI
assert responses[3]['result']['resources'][0]['uri'] == URI
assert responses[4]['result']['contents'][0]['text'] == (PACKAGE / 'ui/calculator.html').read_text()
data = responses[5]['result']['structuredContent']
assert data['groups'] == []
assert data['previousTotal'] is None and data['previousPeriod'] is None
assert set(data['total']) == {'tokens', 'missingAgents', 'complete'}
assert 'pricing' not in data
html = responses[4]['result']['contents'][0]['text']
assert 'Token Usage' in html and 'How tokens are counted' in html
assert 'USD' not in html and 'currency' not in html
for index in (6, 7, 8):
    assert responses[index]['error']['code'] == -32602
assert responses[9]['error']['code'] == -32002
assert responses[10]['result'] == {}
assert set(json.loads((PACKAGE / 'mcp.json').read_text())['mcpServers']) == {'cost_calculator'}
assert json.loads((PACKAGE / 'plugin.json').read_text())['name'] == 'cost-calculator'
print('PASS: independent plugin identity, MCP negotiation, token UI, tool/resource isolation, input validation, clean shutdown')
