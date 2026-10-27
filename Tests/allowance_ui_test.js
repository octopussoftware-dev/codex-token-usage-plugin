#!/usr/bin/env node
'use strict';
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const path=require('node:path');
const html=fs.readFileSync(path.join(__dirname,'../Plugin/ui/calculator.html'),'utf8');
const helpers=['allowanceWindowLabel','resetCountdown','allowanceWindowState'].map(name=>{
  const match=html.match(new RegExp('function '+name+'\\([^]*?\\n\\}'));
  assert.ok(match,name);return match[0];
});
const {allowanceWindowLabel:label,resetCountdown:reset,allowanceWindowState:state}=vm.runInNewContext(helpers.join('\n')+'\n({allowanceWindowLabel,resetCountdown,allowanceWindowState})');
assert.equal(label(10080),'Weekly');assert.equal(label(300),'5-hour');assert.equal(label(1440),'Daily');
assert.equal(label(15),'15-minute');assert.equal(label(2880),'2-day');
for(const missing of [null,undefined,0,-5,'300'])assert.equal(label(missing),'Usage window');
assert.equal(reset(1000+6*86400+2*3600,1000),'Resets in 6d 2h');
assert.equal(reset(1000+3661,1000),'Resets in 1h 2m');
assert.equal(reset(1001,1000),'Resets in 1m');
assert.equal(reset(1000,1000),'Reset due · awaiting update');
assert.equal(reset(900,1000),'Reset due · awaiting update');
for(const missing of [null,undefined,0,-5,'1000'])assert.equal(reset(missing,1000),'Reset time unavailable');
assert.equal(state({remainingPercent:71,resetsAt:2000},1000).remaining,71);
assert.equal(state({remainingPercent:0,resetsAt:2000},1000).remaining,0);
assert.equal(state({remainingPercent:100,resetsAt:1000},1000).remaining,null); // Never invent a post-reset allowance.
assert.equal(state({remainingPercent:71,resetsAt:1000},1000).expired,true);
assert.equal(state({remainingPercent:null,resetsAt:2000},1000).remaining,null);
assert.equal(state({remainingPercent:71,resetsAt:null},1000).remaining,71);
console.log('PASS: quota labels, reset countdowns, missing values, zero allowance, and expired-window handling');
