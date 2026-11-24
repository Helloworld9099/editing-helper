'use strict';
const { app, BrowserWindow, Menu, ipcMain, screen, session } = require('electron');
const path = require('node:path');
const core = require('./core');

// Ubuntu defaults to Wayland, where apps cannot position their own windows or reliably stay
// on top. Running through XWayland (X11) makes dragging and always-on-top work. Set
// EDITING_COACH_NATIVE_WAYLAND=1 to opt out.
if (process.platform === 'linux' && !process.env.EDITING_COACH_NATIVE_WAYLAND) {
  app.commandLine.appendSwitch('ozone-platform', 'x11');
}
app.setPath('userData', path.join(app.getPath('appData'), 'editing-coach'));

const MASCOT_SIZE = 80;
const HIDE_MS = 10 * 60 * 1000;
const forceNormal = process.argv.includes('--normal-window');
const RENDERER = path.join(__dirname, '..', 'renderer');

let cfgFile;
let cfg = { ...core.DEFAULTS };
let normal = false;            // regular framed windows instead of the borderless pet
let mascot = null, panel = null, settingsWin = null;
let busy = false;
let quitting = false;
let drag = null, panelDrag = null;
let panelSide = null;
let hideTimer = null, moveTimer = null;
const PANEL_MARGIN = 8;
const BUBBLE_TOP_OFFSET = 16; // Rounded bubble begins below the clapperboard cap.
// Overlap only the pet's transparent window margin, so the pointer reaches its visible cheek.
const BUBBLE_GAP = -10;
const panelSizeForArea = (area) => ({
  width: Math.max(1, Math.min(cfg.panelWidth, area.width - PANEL_MARGIN * 2)),
  height: Math.max(1, Math.min(cfg.panelHeight, area.height - PANEL_MARGIN * 2 - BUBBLE_TOP_OFFSET)),
});

const alive = (w) => w && !w.isDestroyed();
const prefs = () => ({
  preload: path.join(__dirname, 'preload.js'),
  contextIsolation: true, nodeIntegration: false, sandbox: true, webSecurity: true, spellcheck: false,
});
const persist = () => {
  try { core.saveConfig(cfg, cfgFile); } catch (e) { console.error('Could not save settings:', e.message); }
};
const isFrom = (e, w) => alive(w) && e.sender === w.webContents;
const isOurs = (e) => isFrom(e, mascot) || isFrom(e, panel) || isFrom(e, settingsWin);
const publicConfig = () => ({ ...cfg, normal, supportedApps: core.SUPPORTED_APPS, upcomingApps: core.UPCOMING_APPS });

// ------------------------------------------------------------ mascot
function clampMascot(x, y, width, height, withChat = panelVisible()) {
  const m = { x, y, width, height };
  const area = screen.getDisplayMatching(m).workArea;
  return withChat
    ? core.mascotPositionForBubble(m, panelSizeForArea(area), area, BUBBLE_TOP_OFFSET, PANEL_MARGIN)
    : core.clampToArea(x, y, width, height, area, PANEL_MARGIN);
}

function createMascot() {
  const size = MASCOT_SIZE;
  const pos = cfg.mascotX == null || cfg.mascotY == null
    ? core.defaultMascotPosition(size, screen.getPrimaryDisplay().workArea)
    : clampMascot(cfg.mascotX, cfg.mascotY, size, size);

  mascot = new BrowserWindow({
    x: pos.x, y: pos.y, width: size, height: size, useContentSize: true,
    ...(!normal && { minWidth: size, maxWidth: size, minHeight: size, maxHeight: size }),
    title: 'Editing Coach',
    frame: normal, transparent: !normal, hasShadow: false,
    backgroundColor: normal ? '#1f3a4d' : '#00000000',
    resizable: false, maximizable: false, fullscreenable: false, minimizable: normal,
    skipTaskbar: !normal,
    focusable: normal,           // floating pet never takes keyboard focus from whatever app you're in
    alwaysOnTop: cfg.keepOnTop,
    show: false,
    webPreferences: prefs(),
  });
  if (cfg.keepOnTop) mascot.setAlwaysOnTop(true, 'floating');
  if (!normal) { try { mascot.setVisibleOnAllWorkspaces(true); } catch { /* unsupported */ } }
  mascot.loadFile(path.join(RENDERER, 'mascot.html'));
  mascot.once('ready-to-show', () => mascot.showInactive());

  if (normal) {
    mascot.on('close', () => quitApp());   // closing the only visible window = quit
    mascot.on('move', () => {              // normal-window fallback is moved by the window manager
      if (panelVisible()) placePanel(true);
      clearTimeout(moveTimer);
      moveTimer = setTimeout(savePosition, 600);
    });
  }
}

function savePosition() {
  if (!alive(mascot)) return;
  const [x, y] = mascot.getPosition();
  cfg.mascotX = x; cfg.mascotY = y;
  persist();
}

function showMascot() {
  clearTimeout(hideTimer); hideTimer = null;
  if (alive(mascot)) {
    mascot.showInactive();
    if (cfg.keepOnTop) mascot.setAlwaysOnTop(true, 'floating');
  } else if (alive(settingsWin)) {
    settingsWin.show(); settingsWin.focus();
  }
}

function hideForNow() {
  closePanel();
  if (alive(mascot)) mascot.hide();
  clearTimeout(hideTimer);
  hideTimer = setTimeout(showMascot, HIDE_MS);
}

// Offer explicit sizes so the chat can stay compact without imprecise dragging.
// A preset, like the resize grip, changes saved dimensions only by a user action.
function setChatSize(width, height) {
  const next = { ...cfg, panelWidth: width, panelHeight: height };
  try { core.saveConfig(next, cfgFile); }
  catch (err) { console.error('Could not save chat size:', err.message); return; }
  cfg = next;
  panelDrag = null;
  if (alive(panel) && alive(mascot)) placePanel();
}
function resetChatSize() {
  setChatSize(core.DEFAULTS.panelWidth, core.DEFAULTS.panelHeight);
}

function reclampMascot() {
  if (!alive(mascot) || normal) return;
  const [x, y] = mascot.getPosition();
  const [width, height] = mascot.getSize();
  const c = clampMascot(x, y, width, height);
  if (c.x !== x || c.y !== y) { mascot.setPosition(c.x, c.y); savePosition(); }
  if (panelVisible()) placePanel(true);
}

// ------------------------------------------------------------- panel
function createPanel() {
  panel = new BrowserWindow({
    width: cfg.panelWidth, height: cfg.panelHeight, show: false,
    title: 'Editing Coach',
    frame: normal, transparent: !normal, hasShadow: false,
    resizable: false, maximizable: false, fullscreenable: false, minimizable: normal,
    skipTaskbar: !normal,
    alwaysOnTop: cfg.keepOnTop,
    backgroundColor: normal ? '#f5f7f4' : '#00000000',
    webPreferences: prefs(),
  });
  panel.webContents.on?.('did-finish-load', () => {
    // The side event may have been sent before the renderer installed its listener.
    if (panelSide) panel.webContents.send('panel:side', panelSide);
    if (panelVisible()) panel.webContents.send('panel:shown');
  });
  panel.loadFile(path.join(RENDERER, 'panel.html'));
  panel.on('close', (e) => {            // Alt+F4 / window close = collapse, not quit
    if (!quitting) { e.preventDefault(); closePanel(); }
  });
}

// The saved panel size is authoritative. Reading getSize() on every move lets a
// compositor-induced resize become the new baseline, making the chat grow on
// each drag event (as observed on Ubuntu/XWayland). Keep a single fixed geometry.
function placePanel(followingDrag = false) {
  if (!alive(panel) || !alive(mascot)) return;
  let m = mascot.getBounds();
  const area = screen.getDisplayMatching(m).workArea;
  const { width, height } = panelSizeForArea(area);
  // Opening a tall bubble near the bottom must bring the pet into view, rather
  // than placing the bubble above it. During dragging clampMascot does this first.
  const anchored = core.mascotPositionForBubble(m, { width, height }, area, BUBBLE_TOP_OFFSET, PANEL_MARGIN);
  if (anchored.x !== m.x || anchored.y !== m.y) {
    if (normal) mascot.setPosition(anchored.x, anchored.y);
    else mascot.setBounds({ x: anchored.x, y: anchored.y, width: MASCOT_SIZE, height: MASCOT_SIZE });
    m = { ...m, x: anchored.x, y: anchored.y };
  }
  const { x, y, side } = core.panelPosition(
    m, { width, height }, area, BUBBLE_GAP, PANEL_MARGIN, followingDrag ? panelSide : null, BUBBLE_TOP_OFFSET
  );
  const sideChanged = side !== panelSide;
  panelSide = side;
  const current = panel.getBounds();
  if (current.x !== x || current.y !== y || current.width !== width || current.height !== height) {
    // Full bounds preserve the saved size even when the Linux WM moves the window.
    panel.setBounds({ x, y, width, height });
  }
  if (sideChanged) panel.webContents.send('panel:side', side);
}

function openPanel() {
  if (!alive(mascot)) return;
  if (!alive(panel)) createPanel();
  placePanel();
  panel.show();                          // user-initiated, so taking focus here is expected
  panel.focus();
  if (cfg.keepOnTop) panel.setAlwaysOnTop(true, 'floating');
  if (!panel.webContents.isLoadingMainFrame?.()) panel.webContents.send('panel:shown');
  mascot.webContents.send('mascot:badge', false);
}

function closePanel() {
  finishPanelResize();
  if (alive(panel)) panel.hide();
}

const panelVisible = () => alive(panel) && panel.isVisible();

function savePanelSize() {
  if (!alive(panel)) return;
  const [width, height] = panel.getSize();
  cfg.panelWidth = width;
  cfg.panelHeight = height;
  persist();
}

function finishPanelResize() {
  if (panelDrag?.changed) {
    savePanelSize();
    if (panelVisible()) placePanel(true);
  }
  panelDrag = null;
}

function resizePanelFrom(bounds, dx, dy) {
  const area = screen.getDisplayMatching(bounds).workArea;
  const size = core.panelResize(bounds, dx, dy, area);
  const [width, height] = panel.getSize();
  if (width === size.width && height === size.height) return false;
  panel.setBounds({ x: bounds.x, y: bounds.y, ...size });
  return true;
}

// ---------------------------------------------------------- settings
function openSettings(mode = 'settings') {
  if (alive(settingsWin)) { settingsWin.show(); settingsWin.focus(); return; }
  const isSetup = mode === 'setup';
  settingsWin = new BrowserWindow({
    width: 460, height: isSetup ? 380 : 560, useContentSize: true,
    title: isSetup ? 'Editing Coach: setup' : 'Editing Coach: settings',
    resizable: false, maximizable: false, minimizable: false, fullscreenable: false,
    autoHideMenuBar: true, backgroundColor: '#ffffff',
    alwaysOnTop: cfg.keepOnTop && !isSetup,
    webPreferences: prefs(),
  });
  settingsWin.loadFile(path.join(RENDERER, 'settings.html'), { query: { mode } });
  settingsWin.on('closed', () => {
    settingsWin = null;
    if (!cfg.setupDone) quitApp();       // closing setup without finishing quits
  });
}

// -------------------------------------------------------------- IPC
function registerIpc() {
  ipcMain.handle('config:get', (e) => (isOurs(e) ? publicConfig() : null));

  ipcMain.handle('config:save', (e, input) => {
    if (!isFrom(e, settingsWin)) return { ok: false, errors: { form: 'Not allowed.' } };
    input = input || {};
    const errors = {};
    const { url, error } = core.validateBaseUrl(input.apiBaseUrl ?? cfg.apiBaseUrl);
    if (error) errors.apiBaseUrl = error;
    if (!core.SUPPORTED_APPS.includes(input.editor)) errors.editor = 'Choose a supported video editor.';
    if (Object.keys(errors).length) return { ok: false, errors };

    const windowMode = input.windowMode === 'normal' ? 'normal' : input.windowMode === 'floating' ? 'floating' : cfg.windowMode;
    const wasSetup = !cfg.setupDone;
    const restartNeeded = !wasSetup && windowMode !== cfg.windowMode;
    const next = {
      ...cfg,
      editor: input.editor,
      editorVersion: core.sanitizeText(String(input.editorVersion ?? '')).trim().slice(0, 40),
      apiBaseUrl: url,
      keepOnTop: typeof input.keepOnTop === 'boolean' ? input.keepOnTop : cfg.keepOnTop,
      windowMode,
      setupDone: cfg.setupDone || (wasSetup && input.finishSetup === true),
    };
    // Do not report success or update live settings until the new config is persisted.
    try { core.saveConfig(next, cfgFile); }
    catch { return { ok: false, errors: { form: 'Could not save settings. Check file permissions and try again.' } }; }
    cfg = next;
    if (!wasSetup && alive(panel)) panel.webContents.send('panel:config-changed');
    if (wasSetup && cfg.setupDone) normal = forceNormal || cfg.windowMode === 'normal';
    for (const w of [mascot, panel]) if (alive(w)) w.setAlwaysOnTop(cfg.keepOnTop, 'floating');
    if (wasSetup && cfg.setupDone) { createMascot(); createPanel(); }   // before setup window closes
    return { ok: true, restartNeeded };
  });

  ipcMain.handle('coach:ask', async (e, question) => {
    if (!isFrom(e, panel)) return { ok: false, kind: 'unexpected', message: 'Not allowed.' };
    if (busy) return { ok: false, kind: 'busy', message: 'Still working on your last question.' };
    busy = true;
    if (alive(mascot)) mascot.webContents.send('mascot:busy', true);
    let result;
    try {
      const launchUrl = process.env.EDITING_HELPER_API;
      result = await core.postCoach({
        baseUrl: launchUrl || cfg.apiBaseUrl,
        accessToken: launchUrl ? process.env.EDITING_HELPER_ACCESS_TOKEN : '',
        question,
        editor: cfg.editor,
        version: cfg.editorVersion,
        timeoutMs: cfg.timeoutSeconds * 1000,
      });
    } catch {
      result = { ok: false, kind: 'unexpected', message: 'Unexpected problem while contacting the server.' };
    } finally {
      busy = false;
      if (alive(mascot)) mascot.webContents.send('mascot:busy', false);
    }
    // A reply never raises or focuses a window; if the panel is collapsed it just lights a dot.
    if (result.ok && !panelVisible() && alive(mascot)) mascot.webContents.send('mascot:badge', true);
    return result;
  });

  ipcMain.on('panel:resize', (e, action, dx, dy) => {
    if (!isFrom(e, panel) || !panelVisible()) return;
    if (action === 'end') { finishPanelResize(); return; }
    if (drag) return; // The pet and chat resize never own the pointer at the same time.
    if (action === 'start') {
      finishPanelResize();
      panelDrag = { bounds: panel.getBounds(), changed: false };
      return;
    }
    if (!Number.isFinite(dx) || !Number.isFinite(dy)) return;
    if (action === 'move' && panelDrag) {
      if (resizePanelFrom(panelDrag.bounds, dx, dy)) panelDrag.changed = true;
    } else if (action === 'key' && !panelDrag && Math.abs(dx) <= 16 && Math.abs(dy) <= 16) {
      if (resizePanelFrom(panel.getBounds(), dx, dy)) savePanelSize();
    }
  });

  ipcMain.on('panel:close', (e) => { if (isFrom(e, panel)) closePanel(); });
  ipcMain.on('app:open-settings', (e) => { if (isOurs(e)) openSettings('settings'); });
  ipcMain.on('app:quit', (e) => { if (isOurs(e)) quitApp(); });

  // Mascot: click toggles the panel; dragging moves the window (cursor position is read here,
  // in the same coordinate space as the window, so it behaves on scaled displays too).
  ipcMain.on('mascot:click', (e) => { if (isFrom(e, mascot)) (panelVisible() ? closePanel() : openPanel()); });
  ipcMain.on('mascot:drag-start', (e) => {
    if (!isFrom(e, mascot) || normal) return;
    finishPanelResize();
    const c = screen.getCursorScreenPoint();
    const [wx, wy] = mascot.getPosition();
    drag = { cx: c.x, cy: c.y, wx, wy };
  });
  ipcMain.on('mascot:drag-move', (e) => {
    if (!isFrom(e, mascot) || !drag) return;
    const c = screen.getCursorScreenPoint();
    const p = clampMascot(drag.wx + (c.x - drag.cx), drag.wy + (c.y - drag.cy), MASCOT_SIZE, MASCOT_SIZE);
    // Set position and size together: compositor/window-manager changes cannot grow the pet.
    mascot.setBounds({ x: p.x, y: p.y, width: MASCOT_SIZE, height: MASCOT_SIZE });
    // Follow the pet while the chat is open, without changing the chat's dimensions.
    if (panelVisible()) placePanel(true);
  });
  ipcMain.on('mascot:drag-end', (e, moved) => {
    if (!isFrom(e, mascot)) return;
    if (drag && moved === true) {
      // Repair any late compositor geometry change before releasing drag.
      if (panelVisible()) placePanel(true);
      savePosition();
    }
    drag = null;
  });
  ipcMain.on('mascot:menu', (e) => {
    if (!isFrom(e, mascot)) return;
    Menu.buildFromTemplate([
      { label: 'Ask a question', click: openPanel },
      { label: 'Settings…', click: () => openSettings('settings') },
      { label: 'Chat size', submenu: [
        { label: 'Compact (320 × 400)', click: () => setChatSize(320, 400) },
        { label: 'Default (380 × 520)', click: resetChatSize },
      ] },
      { label: 'Hide for 10 minutes', click: hideForNow },
      { type: 'separator' },
      { label: 'Quit Editing Coach', click: quitApp },
    ]).popup({ window: mascot });
  });
}

function quitApp() {
  quitting = true;
  app.quit();
}

// --------------------------------------------------------- lifecycle
if (!app.requestSingleInstanceLock()) {
  app.quit();
} else {
  app.on('second-instance', showMascot);          // launching again brings a hidden pet back
  app.on('before-quit', () => { quitting = true; finishPanelResize(); savePosition(); });
  app.on('window-all-closed', () => app.quit());

  app.on('web-contents-created', (_e, wc) => {     // the UI can't open windows or navigate away
    wc.setWindowOpenHandler(() => ({ action: 'deny' }));
    wc.on('will-navigate', (ev) => ev.preventDefault());
  });

  app.whenReady().then(() => {
    session.defaultSession.setPermissionRequestHandler((_wc, _perm, cb) => cb(false));
    Menu.setApplicationMenu(null);
    cfgFile = path.join(app.getPath('userData'), 'config.json');
    cfg = core.loadConfig(cfgFile);
    normal = forceNormal || cfg.windowMode === 'normal';
    registerIpc();
    screen.on('display-removed', reclampMascot);
    screen.on('display-metrics-changed', reclampMascot);
    if (cfg.setupDone) { createMascot(); createPanel(); } else { openSettings('setup'); }
  });
}
