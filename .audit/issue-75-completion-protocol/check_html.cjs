// Throwaway executable walkthrough check. No browser, stores, or persistence.
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const path = require('node:path');
const html = fs.readFileSync(path.join(__dirname, 'prototype.html'), 'utf8');
const script = html.match(/<script>([\s\S]*?)<\/script>/)[1];
new vm.Script(script); // Parse the whole page's JavaScript, including DOM shell.
const context = vm.createContext({});
vm.runInContext(script.split('const labels=')[0], context);
const scenarios = [
  ['late receipt', ['commit', 'ack', 'pause', 'receipt', 'crash'], true],
  ['crash before observation', ['commit', 'crash', 'pause', 'backfill'], false],
  ['crash after observation', ['commit', 'ack', 'crash', 'backfill'], false],
  ['pause before observation', ['commit', 'pause', 'ack', 'backfill'], false],
  ['cutoff equality', ['commit', 'equal', 'ack', 'backfill'], false],
  ['interrupted receipt', ['commit', 'ack', 'failed_receipt', 'crash', 'backfill'], false],
  ['receipt deletion', ['commit', 'ack', 'receipt', 'delete', 'backfill'], false],
  ['corrupt graph', ['commit', 'ack', 'receipt', 'corrupt'], false],
];
for (const [name, actions, expected] of scenarios) {
  let state = vm.runInContext('initial()', context);
  for (const action of actions) {
    context.input = state;
    context.action = action;
    state = vm.runInContext('transition(input, action)', context);
  }
  const qualified = !!(state.receipt && state.selection === state.receipt.selection &&
    state.receipt.observedAt < 10);
  assert.equal(qualified, expected, name);
}
console.log(JSON.stringify({html_walkthroughs: scenarios.length, passed: true,
  limit: 'Pure reducer and full-script syntax checked; browser rendering not checked'}));
