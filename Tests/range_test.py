#!/usr/bin/env python3
"""Rolling windows use response timestamps, including nested agents and legacy logs."""
import json
import os
import sqlite3
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from cost_test import Client, context, event, record, usage

DAY = 86400


def run(home):
    now = time.time()
    (home / 'sessions').mkdir()
    db = sqlite3.connect(home / 'state_5.sqlite')
    db.executescript('''
        CREATE TABLE threads(id TEXT PRIMARY KEY, rollout_path TEXT, title TEXT,
          cwd TEXT, model TEXT, reasoning_effort TEXT, source TEXT, thread_source TEXT,
          agent_nickname TEXT, created_at INTEGER, updated_at INTEGER, tokens_used INTEGER);
        CREATE TABLE thread_spawn_edges(parent_thread_id TEXT, child_thread_id TEXT);
    ''')
    paths = {}

    def ident(n):
        return f'{n:08d}-1111-4111-8111-111111111111'

    def timestamp(age):
        return datetime.fromtimestamp(now - age, timezone.utc).isoformat().replace('+00:00', 'Z')

    def response(n, key, amount, age):
        value = record(ident(n), key, usage(amount, amount // 2, amount // 10))
        value['timestamp'] = timestamp(age)
        return value

    def chat(n, title, events, parent=None, updated=60):
        path = home / 'sessions' / f'{ident(n)}.jsonl'
        paths[n] = path
        db.execute('INSERT INTO threads VALUES(?,?,?,?,?,?,?,?,?,?,?,?)', (
            ident(n), str(path), title, '/tmp/Timeline', 'gpt-6-sol', 'high',
            'vscode', 'subagent' if parent else 'user', '', now - 100 * DAY, now - updated, 100))
        if parent:
            db.execute('INSERT INTO thread_spawn_edges VALUES(?,?)', (ident(parent), ident(n)))
        if events is not None:
            path.write_text(''.join(json.dumps(e) + '\n' for e in [context('gpt-6-sol'), *events]))
            os.utime(path, (now - updated, now - updated))

    # The latest duplicate belongs to the original response's time, not its update time.
    chat(1, 'Project timeline', [response(1, 'today', 100, DAY / 2),
        response(1, 'week', 200, 3 * DAY), response(1, 'month', 300, 10 * DAY),
        response(1, 'old', 400, 40 * DAY), response(1, 'old', 400, 600)])
    chat(2, 'Child', [response(2, 'today', 50, DAY / 4), response(2, 'month', 60, 15 * DAY)], parent=1)
    chat(3, 'Grandchild', [response(3, 'week', 70, 5 * DAY)], parent=2)
    chat(4, 'Child-led work', [response(4, 'old', 1000, 40 * DAY)], updated=40 * DAY)
    chat(5, 'Recent child', [response(5, 'today', 70, 600)], parent=4)
    chat(6, 'Old chat', [response(6, 'old', 300, 40 * DAY)], updated=40 * DAY)

    undated = response(7, 'undated', 10, 0)
    del undated['timestamp']
    invalid = response(7, 'invalid', 20, 0)
    invalid['timestamp'] = 'not-a-date'
    chat(7, 'Undated usage', [undated, invalid, response(7, 'today', 30, 60)])
    chat(8, 'Future timestamp', [response(8, 'future', 50, -DAY)])
    chat(9, 'Missing log', None)

    def legacy(amount, total, age):
        return event('event_msg', dict(type='token_count', info=dict(
            total_token_usage=usage(total, 0, total // 10),
            last_token_usage=usage(amount, 0, amount // 10))), timestamp(age))

    chat(10, 'Legacy timeline', [legacy(100, 100, 3 * DAY),
        context('gpt-6-sol', 'later-turn'), legacy(100, 100, 600), legacy(200, 300, 300)])
    # Every cutoff has a response just inside and just outside the window.
    chat(11, 'Window boundaries', [response(11, str(index), amount, age)
        for index, (amount, age) in enumerate([(10, DAY - 60), (20, DAY + 60),
            (30, 7 * DAY - 60), (40, 7 * DAY + 60),
            (50, 30 * DAY - 60), (60, 30 * DAY + 60)])])
    # New metadata alone does not imply tokens were used within the chosen period.
    chat(12, 'Batched old first', [response(12, 'old', 100, 40 * DAY)], updated=10)
    chat(13, 'Batched old second', [response(13, 'old', 100, 40 * DAY)], updated=20)
    chat(14, 'Batched recent first', [response(14, 'today', 100, 7200)], updated=7200)
    chat(15, 'Batched recent second', [response(15, 'today', 200, 10800)], updated=10800)
    chat(16, 'Batched previous only', [response(16, 'previous-day', 500, 1.5 * DAY)], updated=1.5 * DAY)
    chat(17, 'Dormant parent', [response(17, 'old', 1000, 90 * DAY)], updated=90 * DAY)
    chat(18, 'Previous-window child', [response(18, 'previous-day', 80, 1.5 * DAY)], parent=17, updated=1.5 * DAY)
    db.commit()
    db.close()

    client = Client(home)
    try:
        expected = {'day': (165, 220, 11), 'week': (462, 330, 66),
                    'month': (858, 330, 165), 'all': (1298, 330, 231)}
        expected_previous = {'day': (0, 0, 22), 'week': (330, 0, 44), 'month': (440, 0, 66)}
        for period in ['all', 'day', 'week', 'month', 'all', 'day']:
            data = client.tool('list_usage', dict(range=period, limit=200))
            groups = {g['id']: g for g in data['groups']}
            assert data['period']['id'] == period
            assert data['period']['end'] == data['observedAt']
            if period == 'all':
                assert data['period']['start'] is None
                assert data['previousPeriod'] is None and data['previousTotal'] is None
                assert all(g['previousUsage'] is None for g in groups.values())
            else:
                seconds = {'day': DAY, 'week': 7 * DAY, 'month': 30 * DAY}[period]
                assert abs(data['period']['end'] - data['period']['start'] - seconds) < .001
                previous_period = data['previousPeriod']
                assert previous_period['end'] == data['period']['start']
                assert abs(previous_period['end'] - previous_period['start'] - seconds) < .001
                assert previous_period['endExclusive'] and not data['period']['endExclusive']
                assert ident(8) not in groups
                for n in (6, 12, 13):
                    assert (ident(n) in groups) == (period == 'month')
                    if period == 'month':
                        assert groups[ident(n)]['usage']['tokens']['total'] == 0
                        assert groups[ident(n)]['previousUsage']['tokens']['total'] > 0
                for n, previous_total in zip((1, 10, 11), expected_previous[period]):
                    assert groups[ident(n)]['previousUsage']['tokens']['total'] == previous_total
                assert data['previousTotal']['tokens']['total'] == sum(g['previousUsage']['tokens']['total'] for g in groups.values())
                assert not groups[ident(7)]['previousUsage']['complete']
                assert not groups[ident(9)]['previousUsage']['complete']
                if period == 'day':
                    for n, previous_total in [(16, 550), (17, 88)]:
                        assert groups[ident(n)]['usage']['tokens']['total'] == 0
                        assert groups[ident(n)]['previousUsage']['tokens']['total'] == previous_total
            assert groups[ident(1)]['usage']['tokens']['total'] == expected[period][0]
            assert groups[ident(10)]['usage']['tokens']['total'] == expected[period][1]
            assert groups[ident(11)]['usage']['tokens']['total'] == expected[period][2]
            assert groups[ident(4)]['usage']['tokens']['total'] == (1177 if period == 'all' else 77)
            missing = groups[ident(9)]['usage']
            assert missing['tokens']['total'] == 0 and missing['missingAgents'] == 1
            undated_usage = groups[ident(7)]['usage']
            assert undated_usage['tokens']['total'] == (66 if period == 'all' else 33)
            assert undated_usage['complete'] == (period == 'all')
            assert data['total']['tokens']['total'] == sum(g['usage']['tokens']['total'] for g in groups.values())
            detail = client.tool('read_usage_detail', dict(thread_id=ident(1), range=period))['groups'][0]
            assert [a['depth'] for a in detail['agents']] == [0, 1, 2]
            assert detail['usage'] == groups[ident(1)]['usage']
            assert sum(a['usage']['tokens']['total'] for a in detail['agents']) == expected[period][0]
            assert detail['previousUsage'] == groups[ident(1)]['previousUsage']
            if period == 'all':
                assert all(a['previousUsage'] is None for a in detail['agents'])
            else:
                assert sum(a['previousUsage']['tokens']['total'] for a in detail['agents']) == expected_previous[period][0]
            assert detail['agents'][0]['model'] == 'gpt-6-sol' and detail['agents'][0]['effort'] == 'high'

        page = client.tool('list_usage', dict(query='Batched', range='day', limit=1))
        assert page['matchingCount'] == 3 and page['loadedCount'] == 1
        assert page['groups'][0]['id'] == ident(14) and page['total']['tokens']['total'] == 110
        assert page['previousTotal']['tokens']['total'] == 0
        page = client.tool('list_usage', dict(query='Batched', range='day', limit=2))
        assert page['loadedCount'] == 2 and page['total']['tokens']['total'] == 330
        assert page['previousTotal']['tokens']['total'] == 0
        page = client.tool('list_usage', dict(query='Batched', range='day', limit=3))
        assert page['loadedCount'] == 3 and page['total']['tokens']['total'] == 330
        assert page['previousTotal']['tokens']['total'] == 550
        assert client.tool('list_usage', dict(query='No such chat', range='day'))['groups'] == []
        zero = client.tool('read_usage_detail', dict(thread_id=ident(6), range='day'))['groups'][0]
        assert zero['usage']['tokens']['total'] == 0 and zero['usage']['complete']
        undated_detail = client.tool('read_usage_detail', dict(thread_id=ident(7), range='day'))['groups'][0]
        assert 'timestamps are missing' in undated_detail['agents'][0]['note']
        for bad_range in ['year', '', None, True, 7, []]:
            for name, args in [('list_usage', {}), ('read_usage_detail', dict(thread_id=ident(1)))]:
                result = client.call('tools/call', dict(name=name, arguments=dict(args, range=bad_range)))
                assert result['error']['code'] == -32602, result

        # Cached parsing still counts appended usage exactly once in every selected period.
        with paths[1].open('a') as log:
            log.write(json.dumps(response(1, 'appended', 40, 1)) + '\n')
        for period, total in [('day', 209), ('all', 1342), ('day', 209)]:
            detail = client.tool('read_usage_detail', dict(thread_id=ident(1), range=period))['groups'][0]
            assert detail['usage']['tokens']['total'] == total
    finally:
        client.close()


if __name__ == '__main__':
    with tempfile.TemporaryDirectory(prefix='token-period-test-', dir='/private/tmp') as tmp:
        run(Path(tmp))
    print('PASS: adjacent day/week/month comparisons, previous-only chats and descendants, matching loaded cohorts, cutoff boundaries, all-time compatibility, nested rollups, original response timestamps, legacy deduplication, undated and future records, filtering before pagination, detail totals, range validation and incremental reads')
