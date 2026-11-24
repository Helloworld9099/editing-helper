'use strict';
const { test } = require('node:test');
const assert = require('node:assert/strict');
const core = require('../src/core');
const { EventEmitter } = require('node:events');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { pathToFileURL } = require('node:url');

test('screenshots require HTTPS even without a bearer token', async () => {
  const r = await core.postScreenAnalysis({ baseUrl: 'http://example.org', editor: 'Kdenlive',
    image: 'test', mime_type: 'image/png' });
  assert.equal(r.kind, 'config');
  assert.match(r.message, /HTTPS/);
});

test('capture IPC restricts senders and source selection and restores visibility on capture failure', async () => {
  let win;
  class Window extends EventEmitter {
    constructor() {
      super();
      this.webContents = new EventEmitter();
      this.webContents.mainFrame = {};
      this.webContents.session = { setPermissionRequestHandler() {}, setPermissionCheckHandler() {} };
      this.visible = true;
      win = this;
    }
    static getAllWindows() { return [win]; }
    loadFile(file) { this.webContents.mainFrame.url = pathToFileURL(file).href; }
    getMediaSourceId() { return 'window:self'; }
    hide() { this.visible = false; }
    showInactive() { this.visible = true; }
    isVisible() { return this.visible; }
    isDestroyed() { return false; }
    isMinimized() { return false; }
  }
  let requests = 0;
  const handlers = new Map();
  const electron = {
    ipcMain: { handle: (key, handler) => handlers.set(key, handler) },
    BrowserWindow: Window,
    screen: { getAllDisplays: () => [{ id: 1, size: { width: 1600, height: 900 }, scaleFactor: 1 }] },
    desktopCapturer: { getSources: async ({ thumbnailSize }) => {
      requests++;
      if (!thumbnailSize.width) return [{ id: 'window:11', name: 'Editor' }, { id: 'window:self', name: 'Review' }];
      assert.equal(win.visible, false);
      throw new Error('OS capture denied');
    } },
  };
  const filename = path.resolve(__dirname, '../src/capture.js');
  const mod = { exports: {} };
  vm.runInNewContext(fs.readFileSync(filename, 'utf8'), { __dirname: path.dirname(filename),
    process: { platform: 'linux', env: {} }, require: id => id === 'electron' ? electron : id === './core' ? core : require(id),
    module: mod, AbortController, setTimeout, clearTimeout });
  mod.exports.createCaptureTool(() => ({ baseUrl: core.DEFAULT_API_URL }))();
  const event = { sender: win.webContents, senderFrame: win.webContents.mainFrame };
  const call = (name, arg, e = event) => handlers.get('capture:' + name)(e, arg);
  assert.match((await call('list', 'window', { ...event, senderFrame: {} })).error, /Not allowed/);
  assert.match((await call('take', 'window:11')).error, /Choose a source/);
  assert.equal(requests, 0);
  assert.equal((await call('list', 'window')).sources.length, 1);
  assert.match((await call('take', 'window:11')).error, /permission/);
  assert.equal(win.visible, true);
  assert.match((await call('take', 'window:11')).error, /Choose a source/);
  assert.equal(requests, 2);
  win.emit('closed');
  assert.match((await call('list', 'window')).error, /Not allowed/);
});
