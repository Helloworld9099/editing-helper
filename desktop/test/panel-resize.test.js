'use strict';
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

test('chat grip only sends resize deltas while its pointer is captured', () => {
  class Element {
    constructor() { this.events = new Map(); }
    addEventListener(name, fn) { this.events.set(name, fn); }
    setPointerCapture(id) { this.captured = id; }
    querySelector() { return { querySelector: () => ({}) }; }
    emit(name, extra) { this.events.get(name)?.({ button: 0, pointerId: 1, screenX: 300, screenY: 300, ...extra }); }
  }
  const elements = new Map();
  const doc = new Element();
  doc.getElementById = (id) => {
    if (!elements.has(id)) elements.set(id, new Element());
    return elements.get(id);
  };
  const calls = [];
  const coach = {
    getConfig: async () => ({}), on: () => {}, closePanel: () => {}, openSettings: () => {},
    resizePanel: (...args) => calls.push(args),
  };
  const source = fs.readFileSync(path.join(__dirname, '../renderer/panel.js'), 'utf8');
  vm.runInNewContext(source, { document: doc, window: { coach } });
  const grip = doc.getElementById('resize');
  grip.emit('pointerdown');
  grip.emit('pointerup');
  assert.deepEqual(calls.splice(0), [['start'], ['end']]);
  grip.emit('pointerdown');
  assert.equal(grip.captured, 1);
  grip.emit('pointermove', { pointerId: 2, screenX: 999 });
  grip.emit('pointermove', { screenX: 342, screenY: 330 });
  grip.emit('pointermove', { screenX: 285, screenY: 277 });
  grip.emit('pointermove');
  grip.emit('lostpointercapture');
  grip.emit('pointermove', { screenX: 500 });
  assert.deepEqual(calls, [['start'], ['move', 42, 30], ['move', -15, -23], ['move', 0, 0], ['end']]);
});
