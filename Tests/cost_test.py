#!/usr/bin/env python3
"""Accounting fixtures: no live chats are started or modified."""
import json, os, sqlite3, subprocess, tempfile, shutil
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
SERVER=ROOT/'build/marketplace/plugins/cost-calculator/bin/cost-calculator'
IDS=[f'{i:08d}-1111-4111-8111-111111111111' for i in range(1,10)]

def usage(i,c,o,w=0,r=0): return dict(input_tokens=i,cached_input_tokens=c,cache_write_input_tokens=w,output_tokens=o,reasoning_output_tokens=r,total_tokens=i+o)
def event(typ,p,t='2026-10-26T13:00:00.000Z'): return dict(timestamp=t,type=typ,payload=p)
def record(tid,rid,u,turn='turn-a'):return event('token_usage_record',dict(thread_id=tid,response_id=rid,turn_id=turn,usage=u,thread_token_usage=usage(99999999,0,999999)))
def context(model,turn='turn-a',effort='high'):return event('turn_context',dict(model=model,effort=effort,turn_id=turn))

class Client:
 def __init__(self,home):
  self.p=subprocess.Popen([str(SERVER)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True,env=dict(os.environ,CODEX_HOME=str(home)));self.i=0;self.call('initialize',{})
 def call(self,method,params):
  self.i+=1;self.p.stdin.write(json.dumps(dict(jsonrpc='2.0',id=self.i,method=method,params=params))+'\n');self.p.stdin.flush();r=json.loads(self.p.stdout.readline());assert r['id']==self.i;return r
 def tool(self,name,args={}):
  r=self.call('tools/call',dict(name=name,arguments=args));assert not r.get('error') and not r['result'].get('isError'),r;return r['result']['structuredContent']
 def close(self):self.p.stdin.close();assert self.p.wait(timeout=5)==0

def fixture(home):
 (home/'sessions').mkdir()
 db=sqlite3.connect(home/'state_5.sqlite')
 db.executescript('CREATE TABLE threads(id TEXT PRIMARY KEY,rollout_path TEXT,title TEXT,cwd TEXT,model TEXT,reasoning_effort TEXT,source TEXT,thread_source TEXT,agent_nickname TEXT,created_at INTEGER,updated_at INTEGER,tokens_used INTEGER,archived INTEGER); CREATE TABLE thread_spawn_edges(parent_thread_id TEXT,child_thread_id TEXT);')
 paths={}
 def chat(n,title,events,source='vscode',kind='user',model='gpt-6-astra',archived=0):
  tid=IDS[n];p=home/'sessions'/f'{tid}.jsonl';paths[n]=p
  db.execute('insert into threads values(?,?,?,?,?,?,?,?,?,?,?,?,?)',(tid,str(p),title,'/tmp/Cost Calculator',model,'high',source,kind,title if kind=='subagent' else '',1793016000,1793019600-n,100,archived))
  if events is not None:p.write_text(''.join(json.dumps(e)+'\n' for e in events))
 root=IDS[0];u=usage(1000000,200000,100000,100000,40000)
 chat(0,'Build the cost dashboard',[event('session_meta',dict(id=root)),context('gpt-6-astra'),event('event_msg',dict(type='task_started',turn_id='turn-a')),record(root,'r1',u),record(root,'r1',u),event('event_msg',dict(type='token_count',info=dict(total_token_usage=usage(9999999,0,999999),last_token_usage=u))),context('gpt-6-luna','turn-b','low'),record(root,'r2',usage(1000,0,100),'turn-b'),event('response_item',dict(type='message',role='assistant',channel='analysis',content=[dict(text='SECRET_DO_NOT_EXPOSE_REASONING')])),event('response_item',dict(type='message',role='assistant',phase='commentary',content=[dict(text='Checking the token accounting and parent totals.')])),event('response_item',dict(type='function_call',name='exec_command',arguments='SECRET_DO_NOT_EXPOSE_ARGUMENTS')),event('event_msg',dict(type='task_complete'))])
 source=json.dumps(dict(subagent=dict(thread_spawn=dict(parent_thread_id=root))))
 chat(1,'Usage reader',[event('session_meta',dict(id=IDS[1],parent_thread_id=root)),context('gpt-6-sol',effort='medium'),record(IDS[1],'child',usage(10000,8000,1000)),event('event_msg',dict(type='task_complete',last_agent_message='Validated cached-token accounting.'))],source,'subagent','gpt-6-sol',1)
 chat(2,'Nested helper',[context('gpt-5.6-sol'),record(IDS[2],'grandchild',usage(1000,0,100))],json.dumps(dict(subagent='review')),'subagent','gpt-5.6-sol')
 db.execute('insert into thread_spawn_edges values(?,?)',(IDS[1],IDS[2]))
 chat(3,'Forked follow-up',[event('session_meta',dict(id=IDS[3],forked_from_id=root)),context('gpt-6-astra'),record(root,'copied',u),event('event_msg',dict(type='token_count',info=dict(total_token_usage=u,last_token_usage=u)),'2026-10-25T13:00:00.000Z'),record(IDS[3],'fork-own',usage(100,0,10))])
 chat(4,'Unknown model',[context('unknown-model'),record(IDS[4],'unknown',usage(100,0,10))],model='unknown-model')
 chat(5,'Missing usage',None)
 chat(6,'Unlinked subagent',[context('gpt-6-astra'),record(IDS[6],'orphan',usage(1,0,1))],json.dumps(dict(subagent='review')),'subagent')
 chat(7,'System approval helper',[context('gpt-6-astra'),record(IDS[7],'internal',u)],'vscode','guardian_review')
 legacy=usage(100,50,10)
 chat(8,'Legacy usage',[context('gpt-6-sol'),event('event_msg',dict(type='token_count',info=dict(total_token_usage=legacy,last_token_usage=legacy))),event('event_msg',dict(type='token_count',info=dict(total_token_usage=legacy,last_token_usage=legacy))),context('gpt-6-sol','turn-b'),event('event_msg',dict(type='token_count',info=dict(total_token_usage=legacy,last_token_usage=legacy)))],model='gpt-6-sol')
 db.execute('ALTER TABLE threads ADD COLUMN name TEXT');db.execute('UPDATE threads SET name=?,title=? WHERE id=?',('Build the cost dashboard','Raw original prompt',IDS[0]));db.commit();db.close();return paths

if __name__=='__main__':
 with tempfile.TemporaryDirectory(prefix='cost-test-',dir='/private/tmp') as tmp:
  home=Path(tmp);paths=fixture(home)
  # Group by the full project folder, not its display name. Child folders
  # do not change which project owns a parent chat's rolled-up usage.
  db=sqlite3.connect(home/'state_5.sqlite')
  for tid,cwd in [(IDS[0],'/tmp/work/client-app/'),(IDS[3],'/tmp/work/client-app'),(IDS[4],'/tmp/personal/client-app'),(IDS[5],''),(IDS[8],'/tmp/legacy')]:
   db.execute('UPDATE threads SET cwd=? WHERE id=?',(cwd,tid))
  db.commit();db.close()
  zstd=shutil.which('zstd');assert zstd, 'zstd is required for the compressed-fixture test'
  subprocess.run([zstd,'-q',str(paths[1]),'-o',str(paths[1])+'.zst'],check=True)
  paths[1].unlink()
  client=Client(home)
  try:
   data=client.tool('list_usage');groups={g['id']:g for g in data['groups']}
   assert len(groups)==5 and IDS[1] not in groups and IDS[2] not in groups and IDS[7] not in groups
   assert data['unlinkedSubagents']==1
   group=groups[IDS[0]];assert group['subagentCount']==2 and group['title']=='Build the cost dashboard'
   assert group['project']=='client-app' and group['projectKey']==groups[IDS[3]]['projectKey']
   assert groups[IDS[4]]['project']=='client-app' and groups[IDS[4]]['projectKey']!=group['projectKey']
   assert groups[IDS[5]]['project']=='Other chats' and groups[IDS[5]]['projectKey']==''
   assert group['usage']['complete']
   assert group['usage']['tokens']==dict(input=1012000,cached=208000,cacheWrite=100000,output=101200,reasoning=40000,total=1113200)
   assert group['usage']['tokens']['total']==1113200,group['usage']
   detail=client.tool('read_usage_detail',dict(thread_id=IDS[0]))['groups'][0]
   assert [a['depth'] for a in detail['agents']]==[0,1,2]
   assert detail['projectKey']==group['projectKey']
   assert sum(a['usage']['tokens']['total'] for a in detail['agents'])==group['usage']['tokens']['total']
   parent=detail['agents'][0];assert parent['model']=='gpt-6-luna' and parent['effort']=='low'
   assert parent['summary']=='Checking the token accounting and parent totals.' and parent['status']=='Finished'
   assert len(parent['models'])==2 and parent['usage']['tokens']['reasoning']==40000
   assert 'SECRET_DO_NOT_EXPOSE' not in json.dumps(detail)
   assert groups[IDS[3]]['usage']['tokens']['total']==110,groups[IDS[3]]
   assert groups[IDS[4]]['usage']['tokens']['total']==110 and groups[IDS[4]]['usage']['complete']
   assert data['total']['tokens']['total']==1113530
   def check_no_prices(value):
    if isinstance(value,dict):
     assert not set(value).intersection({'usd','pricing','cost','pricedTokens','unpricedTokens','components'}),value
     for child in value.values():check_no_prices(child)
    elif isinstance(value,list):
     for child in value:check_no_prices(child)
   check_no_prices(data);check_no_prices(detail)
   assert groups[IDS[5]]['usage']['missingAgents']==1 and not groups[IDS[5]]['usage']['complete']
   assert groups[IDS[8]]['usage']['tokens']['total']==110
   assert client.tool('list_usage',dict(query='Forked',limit=1))['loadedCount']==1
   assert client.tool('list_usage',dict(query='client-app'))['loadedCount']==3
   assert client.tool('list_usage',dict(limit=1))['matchingCount']==5
   # Appended data is counted once; an unfinished JSON line waits for its newline.
   addition=json.dumps(record(IDS[3],'incremental',usage(100,0,10)))
   with paths[3].open('a') as f:f.write(addition[:30])
   assert client.tool('read_usage_detail',dict(thread_id=IDS[3]))['groups'][0]['usage']['tokens']['total']==110
   with paths[3].open('a') as f:f.write(addition[30:]+'\n')
   assert client.tool('read_usage_detail',dict(thread_id=IDS[3]))['groups'][0]['usage']['tokens']['total']==220
   assert client.tool('read_usage_detail',dict(thread_id=IDS[3]))['groups'][0]['usage']['tokens']['total']==220
   paths[3].write_text(json.dumps(context('gpt-6-luna'))+'\n'+json.dumps(record(IDS[3],'reset',usage(10,0,1)))+'\n')
   assert client.tool('read_usage_detail',dict(thread_id=IDS[3]))['groups'][0]['usage']['tokens']['total']==11
  finally:client.close()
 print('PASS: project identity, duplicate folder names, projectless chats, nested rollups, compressed logs, archived descendants, response deduplication, model changes, exact token categories, no cache/reasoning double count, fork isolation, legacy deduplication, missing logs, unknown models, no price dependency, activity filtering, incremental updates and truncation')
