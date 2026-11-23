'use strict';
const { test } = require('node:test');
const assert = require('node:assert/strict');
const { EventEmitter } = require('node:events');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const vm = require('node:vm');
const core = require('../src/core');

test('pet remains 80px and the open chat follows during drag without resizing', async (t) => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'editing-coach-window-'));
  t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
  core.saveConfig({ ...core.DEFAULTS, setupDone: true, editor: 'DaVinci Resolve', mascotX: 900, mascotY: 400 }, path.join(dir, 'config.json'));
  const windows = [];
  class Win extends EventEmitter {
    constructor(o) {
      super();
      this.opts = o;
      this.bounds = { x: o.x ?? 0, y: o.y ?? 0, width: o.width, height: o.height };
      this.webContents = { send() {} };
      this.visible = false;
      windows.push(this);
    }
    isDestroyed() { return false; }
    isVisible() { return this.visible; }
    loadFile() {}
    focus() {}
    setAlwaysOnTop() {}
    setVisibleOnAllWorkspaces() {}
    show() { this.visible = true; }
    getBounds() { return { ...this.bounds }; }
    getPosition() { return [this.bounds.x, this.bounds.y]; }
    getSize() { return [this.bounds.width, this.bounds.height]; }
    setPosition(x, y) { Object.assign(this.bounds, { x, y }); }
    setBounds(bounds) { Object.assign(this.bounds, bounds); }
  }
  const ipc = new EventEmitter();
  ipc.handle = () => {};
  const app = new EventEmitter();
  const ready = Promise.resolve();
  Object.assign(app, { commandLine: { appendSwitch() {} }, setPath() {}, getPath: () => dir,
    requestSingleInstanceLock: () => true, whenReady: () => ready });
  const screen = new EventEmitter();
  const display = { workArea: { x: 0, y: 0, width: 1920, height: 1200 } };
  let point = { x: 930, y: 430 };
  Object.assign(screen, { getDisplayMatching: () => display, getPrimaryDisplay: () => display, getCursorScreenPoint: () => point });
  const electron = { app, ipcMain: ipc, BrowserWindow: Win, screen, Menu: { setApplicationMenu() {} },
    session: { defaultSession: { setPermissionRequestHandler() {} } } };
  const file = path.join(__dirname, '../src/main.js');
  vm.runInNewContext(fs.readFileSync(file, 'utf8'), { __dirname: path.dirname(file), process,
    require: (id) => id === 'electron' ? electron : id === './core' ? core : require(id) });
  await ready;
  const [pet, chat] = windows;
  const emit = (win, name, ...args) => ipc.emit(name, { sender: win.webContents }, ...args);
  emit(pet, 'mascot:click');
  const originalChat = { ...chat.getBounds() };
  const petSize = pet.getSize();
  // Simulate an unexpected compositor/window size change prior to dragging.
  pet.setBounds({ ...pet.getBounds(), width: 160, height: 160 });
  emit(chat, 'panel:resize', 'start');
  emit(pet, 'mascot:drag-start');
  emit(chat, 'panel:resize', 'move', 100, 100);
  point = { x: 1100, y: 540 };
  emit(pet, 'mascot:drag-move');
  emit(pet, 'mascot:drag-end', true);
  assert.deepEqual(pet.getPosition(), [1070, 510]);
  assert.deepEqual(pet.getSize(), petSize);
  assert.deepEqual(petSize, [80, 80]);
  assert.deepEqual(chat.getSize(), [originalChat.width, originalChat.height]);
  // The panel tracks the pet, staying on its original side until it would hit an edge.
  const expected = core.panelPosition(pet.getBounds(), { width: originalChat.width, height: originalChat.height }, display.workArea, 8, 8, 'right');
  assert.deepEqual(chat.getPosition(), [expected.x, expected.y]);
  assert.notDeepEqual(chat.getPosition(), [originalChat.x, originalChat.y]);
  emit(chat, 'panel:resize', 'start');
  emit(chat, 'panel:resize', 'move', 50, 40);
  emit(chat, 'panel:resize', 'end');
  assert.deepEqual(chat.getSize(), [originalChat.width + 50, originalChat.height + 40]);
  assert.deepEqual(pet.getSize(), petSize);
});
