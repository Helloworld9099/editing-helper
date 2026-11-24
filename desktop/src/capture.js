'use strict';
const { BrowserWindow, desktopCapturer, ipcMain, screen, systemPreferences } = require('electron');
const path = require('node:path');
const { pathToFileURL } = require('node:url');
const core = require('./core');

const page = path.join(__dirname, '../renderer/capture.html');
const failure = 'Screen capture was canceled or unavailable. Check screen recording permissions or open a PNG or JPEG.';
const limit = 5 * 1024 * 1024;
const modes = new Set(['improve', 'effect', 'fix']);
const contentTypes = new Set(['auto', 'gaming', 'cinematic', 'documentary', 'advertisement', 'educational', 'social', 'custom']);
const wait = ms => new Promise(resolve => setTimeout(resolve, ms));

function createCaptureTool(getConnection, onAnswer) {
  let current;
  let nativeBusy = false;

  async function sources(type, size, hide) {
    if (nativeBusy) throw new Error(failure);
    nativeBusy = true;
    let timer;
    const visible = hide ? BrowserWindow.getAllWindows().filter(w => w.isVisible() && !w.isMinimized()) : [];
    try {
      for (const w of visible) w.hide();
      if (visible.length) await wait(180);
      return await Promise.race([
        desktopCapturer.getSources({ types: [type], thumbnailSize: { width: size, height: size } }),
        new Promise((_, reject) => { timer = setTimeout(() => reject(new Error(failure)), 30000); }),
      ]);
    } finally {
      clearTimeout(timer);
      nativeBusy = false;
      for (const w of visible.reverse()) if (!w.isDestroyed()) w.showInactive();
    }
  }

  function handle(channel, operation, fallback = failure) {
    ipcMain.handle('capture:' + channel, async (event, arg) => {
      const s = current;
      if (!s || event.sender !== s.win.webContents || event.senderFrame !== event.sender.mainFrame ||
          event.senderFrame.url !== pathToFileURL(page).href) return { error: 'Not allowed.' };
      if (s.busy) return { error: 'A capture operation is already running.' };
      s.busy = true;
      try { return await operation(s, arg); }
      catch { return { error: fallback }; }
      finally { s.busy = false; }
    });
  }

  function preview(source) {
    if (!source || source.thumbnail.isEmpty()) return { error: failure };
    return { preview: source.thumbnail.toDataURL() };
  }

  handle('list', async (s, type) => {
    s.ids.clear();
    if (!['screen', 'window'].includes(type)) return { error: 'Choose a display or window.' };
    if (process.platform === 'darwin' && systemPreferences.getMediaAccessStatus('screen') === 'denied')
      return { error: 'Allow Screen Recording in System Settings, or open a screenshot file.' };
    // PipeWire owns source selection. Use its single chosen frame without invoking the portal twice.
    const portal = process.platform === 'linux' && (process.env.XDG_SESSION_TYPE === 'wayland' || !!process.env.WAYLAND_DISPLAY);
    const ownWindows = new Set(BrowserWindow.getAllWindows().map(w => w.getMediaSourceId()));
    const found = (await sources(type, portal ? 2560 : 0, portal)).filter(source => !ownWindows.has(source.id));
    if (portal && found.length === 1) return preview(found[0]);
    s.type = type;
    for (const source of found) s.ids.set(source.id, source.display_id);
    if (!found.length) return { error: failure };
    return { sources: found.map(({ id, name }) => ({ id, name })) };
  });
  handle('take', async (s, id) => {
    if (!s.ids.has(id)) return { error: 'Choose a source from the current list.' };
    const displays = screen.getAllDisplays();
    const display = displays.find(d => String(d.id) === s.ids.get(id));
    const candidates = display ? [display] : displays;
    const size = Math.min(2560, Math.ceil(Math.max(...candidates.map(
      d => Math.max(d.size.width, d.size.height) * d.scaleFactor
    ))));
    s.ids.clear();
    const found = await sources(s.type, size, true);
    return preview(found.find(source => source.id === id));
  });
  handle('send', async (s, input) => {
    if (!input || !['image/png', 'image/jpeg'].includes(input.mime_type) ||
        typeof input.image !== 'string' || !input.image.length || input.image.length > 4 * Math.ceil(limit / 3))
      return { error: 'Invalid screenshot.' };
    const { mode, content_type, context, question } = input;
    if (!modes.has(mode) || !contentTypes.has(content_type) ||
        [context, question].some(value => typeof value !== 'string' || value.length > core.MAX_QUESTION_CHARS))
      return { error: 'Choose valid analysis options and keep each text field within 1000 characters.' };
    const connection = getConnection();
    if (connection.baseUrl !== s.destination) return { error: 'Server address changed. Close and reopen capture.' };
    const result = await core.postScreenAnalysis({ ...connection, signal: s.controller.signal,
      editor: s.editor, version: s.version, mode, content_type,
      context: core.sanitizeText(context).trim(), question: core.sanitizeText(question).trim(),
      image: input.image, mime_type: input.mime_type,
      onUpload: () => { if (!s.win.isDestroyed()) s.win.webContents.send('capture:uploaded'); },
    });
    if (s.controller.signal.aborted) return { error: 'Analysis canceled.' };
    if (!result.ok) return { error: result.message };
    onAnswer({ answer: result.answer, sources: result.sources });
    return { ok: true };
  }, 'Could not complete Screen Analysis. Try again.');
  handle('destination', s => ({ destination: s.destination, editor: s.editor, version: s.version }),
    'Could not load Screen Analysis settings. Close and reopen the window.');

  return function open() {
    if (current) { current.win.show(); return; }
    const win = new BrowserWindow({ width: 760, height: 700, minWidth: 360, minHeight: 380,
      title: 'Screen Analysis', autoHideMenuBar: true, backgroundColor: '#f5f7f4',
      webPreferences: { partition: 'screen-capture', sandbox: true, contextIsolation: true, nodeIntegration: false, spellcheck: false,
        preload: path.join(__dirname, 'capture-preload.js') } });
    win.webContents.session.setPermissionRequestHandler((_wc, _permission, callback) => callback(false));
    win.webContents.session.setPermissionCheckHandler(() => false);
    const { baseUrl: destination, editor, version } = getConnection();
    const s = { win, ids: new Map(), controller: new AbortController(), destination, editor, version };
    current = s;
    win.on('closed', () => { s.controller.abort(); s.ids.clear(); current = null; });
    win.webContents.on('render-process-gone', () => { if (!win.isDestroyed()) win.destroy(); });
    win.loadFile(page);
  };
}

module.exports = { createCaptureTool };
