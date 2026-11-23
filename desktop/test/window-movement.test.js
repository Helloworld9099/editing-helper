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
      this.focusCalls = 0;
      this.positionCalls = 0;
      this.fullBoundsCalls = [];
      windows.push(this);
    }
    isDestroyed() { return false; }
    isVisible() { return this.visible; }
    loadFile() {}
    focus() { this.focusCalls++; }
    setAlwaysOnTop() {}
    setVisibleOnAllWorkspaces() {}
    show() { this.visible = true; }
    getBounds() { return { ...this.bounds }; }
    getPosition() { return [this.bounds.x, this.bounds.y]; }
    getSize() { return [this.bounds.width, this.bounds.height]; }
    setPosition(x, y) {
      this.positionCalls++;
      // Stand in for the observed Linux growth when position is updated alone.
      // A follow gesture must not use this API for the chat.
      if (this === windows[1]) {
        this.bounds.width += 30;
        this.bounds.height += 25;
      }
      Object.assign(this.bounds, { x, y });
    }
    setBounds(bounds) {
      if (this === windows[1]) this.fullBoundsCalls.push({ ...bounds });
      Object.assign(this.bounds, bounds);
    }
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
  let contextMenu;
  const electron = { app, ipcMain: ipc, BrowserWindow: Win, screen, Menu: {
    setApplicationMenu() {},
    buildFromTemplate(items) { contextMenu = items; return { popup() {} }; },
  }, session: { defaultSession: { setPermissionRequestHandler() {} } } };
  const file = path.join(__dirname, '../src/main.js');
  vm.runInNewContext(fs.readFileSync(file, 'utf8'), { __dirname: path.dirname(file), process,
    require: (id) => id === 'electron' ? electron : id === './core' ? core : require(id) });
  await ready;
  const [pet, chat] = windows;
  const emit = (win, name, ...args) => ipc.emit(name, { sender: win.webContents }, ...args);
  emit(pet, 'mascot:click');
  const originalChat = { ...chat.getBounds() };
  const petSize = pet.getSize();
  const focusOnOpen = chat.focusCalls;
  assert.deepEqual(chat.getSize(), [380, 520]);
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
  assert.equal(chat.positionCalls, 0, 'following the pet must never call setPosition on the chat');
  assert.equal(chat.focusCalls, focusOnOpen, 'dragging must never focus the chat');
  // The panel tracks the pet, staying on its original side until it would hit an edge.
  const expected = core.panelPosition(pet.getBounds(), { width: originalChat.width, height: originalChat.height }, display.workArea, 8, 8, 'right');
  assert.deepEqual(chat.getPosition(), [expected.x, expected.y]);
  assert.notDeepEqual(chat.getPosition(), [originalChat.x, originalChat.y]);
  // Simulate a compositor resizing the panel between pointer events. The next
  // movement must restore the saved size rather than compounding the growth.
  chat.bounds.width = 900;
  chat.bounds.height = 750;
  point = { x: 1160, y: 560 };
  emit(pet, 'mascot:drag-start');
  emit(pet, 'mascot:drag-move');
  emit(pet, 'mascot:drag-end', true);
  assert.deepEqual(chat.getSize(), [originalChat.width, originalChat.height]);
  assert.equal(chat.focusCalls, focusOnOpen);
  // The pet can traverse to the opposite edge without rescaling the chat.
  point = { x: 1160, y: 560 };
  emit(pet, 'mascot:drag-start');
  point = { x: 1750, y: 500 };
  emit(pet, 'mascot:drag-move');
  emit(pet, 'mascot:drag-end', true);
  assert.deepEqual(chat.getSize(), [originalChat.width, originalChat.height]);
  const b = chat.getBounds();
  assert.ok(b.x >= 8 && b.x + b.width <= 1920 - 8);
  assert.ok(b.y >= 8 && b.y + b.height <= 1200 - 8);
  emit(chat, 'panel:resize', 'start');
  emit(chat, 'panel:resize', 'move', 50, 40);
  emit(chat, 'panel:resize', 'end');
  assert.deepEqual(chat.getSize(), [originalChat.width + 50, originalChat.height + 40]);
  assert.deepEqual(pet.getSize(), petSize);
  // Repositioning never persists a larger size in the config file.
  const saved = core.loadConfig(path.join(dir, 'config.json'));
  assert.deepEqual([saved.panelWidth, saved.panelHeight], [430, 560]);
  emit(pet, 'mascot:menu');
  const sizes = contextMenu.find((item) => item.label === 'Chat size').submenu;
  sizes.find((item) => item.label.startsWith('Compact')).click();
  assert.deepEqual(chat.getSize(), [320, 400]);
  assert.deepEqual(core.loadConfig(path.join(dir, 'config.json')).panelWidth, 320);
  sizes.find((item) => item.label.startsWith('Default')).click();
  assert.deepEqual(chat.getSize(), [380, 520]);
  assert.deepEqual(pet.getSize(), petSize);
  assert.equal(chat.focusCalls, focusOnOpen, 'size presets must not steal focus');
});
