#!/usr/bin/env node
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const html = fs.readFileSync(path.join(__dirname, '../Plugin/ui/calculator.html'), 'utf8');
// Exercise the pure accounting helpers from the shipped UI without a browser or live chats.
const helpers = ['usageChange', 'compareRank', 'groupProjects'].map(name => {
  const match = html.match(new RegExp('function ' + name + '\\([^]*?\\n\\}'));
  assert.ok(match, name + ' must be available in the UI');
  return match[0];
});
const { usageChange, groupProjects } = vm.runInNewContext(
  "let sortBy='tokens';\n" + helpers.join('\n') + '\n({usageChange,groupProjects})');
const usage = (total, complete=true) => ({tokens:{total},complete,missingAgents:complete?0:1});
function expect(current, previous, kind, percent) {
  const change = usageChange(usage(current), usage(previous));
  assert.equal(change.kind, kind);
  assert.equal(change.percent, percent);
}
expect(150, 100, 'up', 50);
expect(50, 100, 'down', -50);
expect(0, 100, 'down', -100);
expect(400, 100, 'up', 300);
expect(100, 100, 'unchanged', 0);
expect(0, 0, 'unchanged', null);
expect(100, 0, 'new', null);
assert.equal(usageChange(usage(100), null), null);
assert.equal(usageChange(usage(100, false), usage(100)).kind, 'unavailable');
assert.equal(usageChange(usage(100), usage(0, false)).kind, 'unavailable');
assert.ok(Math.abs(usageChange(usage(10001), usage(10000)).percent - .01) < 1e-10);

const chat = (id, projectKey, current, previous, updatedAt) => ({
  id, projectKey, project:'Same name', updatedAt,
  usage:usage(current), previousUsage:usage(previous)
});
const chats = [chat('a', '/project-a', 100, 50, 3), chat('b', '/project-a', 900, 900, 1),
               chat('c', '/project-b', 200, 100, 2)];
const projects = groupProjects(chats);
assert.equal(projects.length, 2);
assert.equal(projects[0].key, '/project-a');
assert.equal(projects[0].usage.tokens.total, 1000);
assert.equal(projects[0].previousUsage.tokens.total, 950);
// Compare aggregate totals: this is ~5.26%, not the 50% average of chat changes.
assert.ok(Math.abs(usageChange(projects[0].usage, projects[0].previousUsage).percent - 5.263157894736842) < 1e-10);
chats[1].previousUsage = usage(900, false);
const incomplete = groupProjects(chats)[0];
assert.equal(incomplete.previousUsage.missingAgents, 1);
assert.equal(usageChange(incomplete.usage, incomplete.previousUsage).kind, 'unavailable');
const allTime = groupProjects(chats.map(c => ({...c, previousUsage:null})));
assert.ok(allTime.every(p => usageChange(p.usage, p.previousUsage) === null));
console.log('PASS: percentage increases/decreases, 100% drops, zero baselines, equal totals, incomplete data, tiny changes, and weighted project comparisons');
