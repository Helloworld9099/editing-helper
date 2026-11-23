'use strict';
// GUI-free logic: config, URL checks, geometry, and the /v1/coach client.
// Only Node built-ins; no network access except the one POST in postCoach().
const fs = require('node:fs');
const path = require('node:path');
const http = require('node:http');
const https = require('node:https');

const DEFAULT_API_URL = 'http://127.0.0.1:8000';
const COACH_PATH = '/v1/coach';
const MAX_RESPONSE_BYTES = 1_000_000;
const MAX_QUESTION_CHARS = 1000; // matches /v1/coach
// Only entries in SUPPORTED_APPS can be saved or sent.
const SUPPORTED_APPS = Object.freeze(['DaVinci Resolve']);
const UPCOMING_APPS = Object.freeze(['Kdenlive', 'Adobe Premiere Pro', 'Final Cut Pro', 'CapCut', 'Shotcut', 'OpenShot']);

const PANEL_MIN = Object.freeze({ width: 300, height: 300 });
const PANEL_MAX = Object.freeze({ width: 1200, height: 1000 });

function panelResize(bounds, dx, dy, area, margin = 8) {
  function dimension(start, delta, min, cap, available) {
    const max = Math.max(1, Math.min(cap, available));
    return Math.min(max, Math.max(Math.min(min, max), Math.round(start + delta)));
  }
  return {
    width: dimension(bounds.width, dx, PANEL_MIN.width, PANEL_MAX.width, area.x + area.width - bounds.x - margin),
    height: dimension(bounds.height, dy, PANEL_MIN.height, PANEL_MAX.height, area.y + area.height - bounds.y - margin),
  };
}

const DEFAULTS = Object.freeze({
  setupDone: false,
  editor: '',
  editorVersion: '',
  apiBaseUrl: DEFAULT_API_URL,
  timeoutSeconds: 90,
  keepOnTop: true,
  windowMode: 'floating', // 'floating' (borderless pet) | 'normal' (regular windows fallback)
  panelWidth: 380,
  panelHeight: 520,
  mascotX: null,
  mascotY: null,
});

// ------------------------------------------------------------------ URLs
function isLoopback(host) {
  const h = String(host || '').toLowerCase().replace(/^\[|\]$/g, '');
  return h === 'localhost' || h === '::1' || h.startsWith('127.');
}

function validateBaseUrl(raw) {
  const s = String(raw ?? '').trim().replace(/\/+$/, '');
  if (!s) return { error: 'Enter the server address, e.g. http://127.0.0.1:8000' };
  if (/\s/.test(s)) return { error: 'The address must not contain spaces.' };
  let u;
  try { u = new URL(s); } catch { return { error: "That doesn't look like a valid address." }; }
  if (u.protocol !== 'http:' && u.protocol !== 'https:') return { error: 'The address must start with http:// or https://' };
  if (!u.hostname) return { error: 'The address is missing a host name.' };
  if (u.username || u.password) return { error: "Don't put a username or password in the address." };
  if (u.search || u.hash) return { error: 'Use just the server address (no ? or # parts).' };
  return { url: s };
}

function urlWarning(raw) {
  try {
    const u = new URL(String(raw || '').trim());
    if (u.protocol === 'http:' && !isLoopback(u.hostname)) {
      return 'Plain http:// sends your questions unencrypted. Prefer https:// for a hosted server.';
    }
  } catch { /* ignore */ }
  return '';
}

// ---------------------------------------------------------------- config
const isInt = (v) => Number.isInteger(v);

function coerce(key, v, d) {
  switch (key) {
    case 'setupDone': case 'keepOnTop': return typeof v === 'boolean' ? v : d;
    case 'editor': case 'editorVersion':
      return typeof v === 'string' ? sanitizeText(v).trim().slice(0, 40) : d;
    case 'apiBaseUrl': return (typeof v === 'string' && validateBaseUrl(v).url) || d;
    case 'timeoutSeconds': return typeof v === 'number' && v >= 1 && v <= 600 ? v : d;
    case 'windowMode': return v === 'floating' || v === 'normal' ? v : d;
    case 'panelWidth': return isInt(v) && v >= PANEL_MIN.width && v <= PANEL_MAX.width ? v : d;
    case 'panelHeight': return isInt(v) && v >= PANEL_MIN.height && v <= PANEL_MAX.height ? v : d;
    case 'mascotX': case 'mascotY': return isInt(v) && v > -10000 && v < 20000 ? v : null;
    default: return d;
  }
}

function loadConfig(file) {
  const cfg = { ...DEFAULTS };
  if (!fs.existsSync(file)) return cfg;
  let data;
  try {
    data = JSON.parse(fs.readFileSync(file, 'utf8'));
    if (data === null || typeof data !== 'object' || Array.isArray(data)) throw new Error('not an object');
  } catch {
    try { fs.renameSync(file, file + '.corrupt'); } catch { /* keep going */ }
    return cfg;
  }
  for (const [key, def] of Object.entries(DEFAULTS)) {
    if (key in data) cfg[key] = coerce(key, data[key], def);
  }
  if (!SUPPORTED_APPS.includes(cfg.editor)) {
    cfg.setupDone = false;
    cfg.editor = '';
    cfg.editorVersion = '';
  }
  return cfg;
}

function saveConfig(cfg, file) {
  fs.mkdirSync(path.dirname(file), { recursive: true });
  const out = {};
  for (const key of Object.keys(DEFAULTS)) out[key] = cfg[key] ?? DEFAULTS[key];
  const tmp = file + '.tmp';
  fs.writeFileSync(tmp, JSON.stringify(out, null, 2));
  fs.renameSync(tmp, file);
}

// -------------------------------------------------------------- geometry
// `area` is a display work area: {x, y, width, height}.
function clampToArea(x, y, w, h, area, margin = 0) {
  const minX = area.x + margin, minY = area.y + margin;
  const maxX = area.x + area.width - w - margin, maxY = area.y + area.height - h - margin;
  return { x: Math.round(Math.max(minX, Math.min(x, maxX))), y: Math.round(Math.max(minY, Math.min(y, maxY))) };
}

function defaultMascotPosition(size, area, margin = 16) {
  return clampToArea(area.x + area.width - size - margin, area.y + Math.round(area.height / 2 - size / 2), size, size, area, 8);
}

// Keep the panel on the same side during a drag until it would run off screen.
// This avoids an unnecessary side-switch as the pet crosses the screen's midpoint.
function panelPosition(m, panel, area, gap = 8, margin = 8, preferredSide = null) {
  const leftX = m.x - gap - panel.width;
  const rightX = m.x + m.width + gap;
  const leftFits = leftX >= area.x + margin;
  const rightFits = rightX + panel.width <= area.x + area.width - margin;
  const defaultSide = m.x + m.width / 2 > area.x + area.width / 2 ? 'left' : 'right';
  let side = preferredSide === 'left' || preferredSide === 'right' ? preferredSide : defaultSide;
  if (side === 'left' && !leftFits && rightFits) side = 'right';
  if (side === 'right' && !rightFits && leftFits) side = 'left';
  const x = side === 'left' ? leftX : rightX;
  const y = m.y + Math.round(m.height / 2 - panel.height / 2);
  return { ...clampToArea(x, y, panel.width, panel.height, area, margin), side };
}

// ------------------------------------------------------------ API client
function sanitizeText(s) {
  return String(s).replace(/\r\n?/g, '\n').replace(/[\u0000-\u0008\u000B\u000C\u000E-\u001F\u007F-\u009F\u2028\u2029]/g, '');
}

function httpDetail(buf) {
  try {
    const d = JSON.parse(buf.toString('utf8')).detail;
    if (typeof d === 'string' && d.trim()) return ': ' + sanitizeText(d.trim()).slice(0, 200);
  } catch { /* no usable detail */ }
  return '';
}

function parseResponse(status, buf) {
  const fail = (kind, message) => ({ ok: false, kind, message });
  if (status >= 300 && status < 400) {
    return fail('unexpected', `The server redirected the request (HTTP ${status}); check the address in Settings.`);
  }
  if (status < 200 || status >= 300) {
    return fail('http', `The coach server returned an error (HTTP ${status})${httpDetail(buf)}`);
  }
  let data;
  try { data = JSON.parse(buf.toString('utf8')); } catch {
    return fail('unexpected', "The server's reply wasn't valid JSON. Is that address really the Editing Coach backend?");
  }
  const answer = data && typeof data === 'object' ? data.answer : undefined;
  if (typeof answer !== 'string' || !answer.trim()) {
    return fail('unexpected', 'The server\'s reply had no text "answer" field.');
  }
  return { ok: true, answer: sanitizeText(answer).trim() };
}

const OFFLINE_CODES = new Set(['ECONNREFUSED', 'ENOTFOUND', 'EAI_AGAIN', 'EHOSTUNREACH', 'ENETUNREACH', 'ECONNRESET', 'EPIPE', 'ETIMEDOUT']);

/**
 * POST {"question": ..., "editor"?: ..., "version"?: ...} to <baseUrl>/v1/coach. Never throws; resolves to
 * {ok:true, answer} or {ok:false, kind, message}.
 * kind: empty | config | offline | timeout | tls | http | unexpected
 * No proxies, no redirects followed, response size capped.
 */
function postCoach({ baseUrl, question, editor, version, timeoutMs = 90000 }) {
  return new Promise((resolve) => {
    const fail = (kind, message) => resolve({ ok: false, kind, message });
    const q = String(question ?? '').trim();
    if (!q) return fail('empty', 'Type a question first.');
    if (q.length > MAX_QUESTION_CHARS) return fail('empty', `That question is too long (limit ${MAX_QUESTION_CHARS} characters).`);
    const { url: base, error } = validateBaseUrl(baseUrl);
    if (error) return fail('config', `Server address problem: ${error}`);

    const target = new URL(base + COACH_PATH);
    const payload = { question: q };
    if (editor != null) {
      if (!SUPPORTED_APPS.includes(editor)) return fail('config', 'Choose a supported editor in Settings.');
      payload.editor = editor;
      const v = sanitizeText(String(version ?? '')).trim().slice(0, 40);
      if (v) payload.version = v;
    }
    const body = Buffer.from(JSON.stringify(payload));
    const lib = target.protocol === 'https:' ? https : http;
    const secs = Math.round(timeoutMs / 1000);
    const broken = { ok: false, kind: 'unexpected', message: 'The connection to the server broke mid-reply. Try again.' };
    let done = false;
    let timer;
    const finish = (r) => { if (done) return; done = true; clearTimeout(timer); resolve(r); };

    const req = lib.request(target, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Content-Length': body.length, Accept: 'application/json' },
    }, (res) => {
      const chunks = [];
      let size = 0;
      res.on('data', (c) => {
        size += c.length;
        if (size > MAX_RESPONSE_BYTES) {
          finish({ ok: false, kind: 'unexpected', message: "The server's reply was unexpectedly large, so it was ignored." });
          req.destroy();
          return;
        }
        chunks.push(c);
      });
      res.on('end', () => finish(parseResponse(res.statusCode, Buffer.concat(chunks))));
      res.on('error', () => finish(broken));
      res.on('close', () => finish(broken)); // no-op if 'end' already finished
    });

    timer = setTimeout(() => {
      finish({ ok: false, kind: 'timeout', message: `The coach server didn't answer within ${secs} seconds. The model may be busy or still loading; try again in a moment.` });
      req.destroy();
    }, timeoutMs);

    req.on('error', (err) => {
      const code = err && err.code ? String(err.code) : '';
      if (/CERT|SELF_SIGNED|UNABLE_TO_VERIFY|ERR_TLS|ERR_SSL|HOSTNAME_MISMATCH/.test(code)) {
        finish({ ok: false, kind: 'tls', message: 'Secure connection failed (certificate or TLS problem).' });
      } else if (OFFLINE_CODES.has(code) || err instanceof AggregateError) {
        finish({ ok: false, kind: 'offline', message: `Can't reach the coach server at ${base}. Make sure your FastAPI backend is running, or check the address in Settings.` });
      } else {
        finish(broken);
      }
    });
    req.end(body);
  });
}

module.exports = {
  DEFAULT_API_URL, COACH_PATH, MAX_QUESTION_CHARS, MAX_RESPONSE_BYTES, SUPPORTED_APPS, UPCOMING_APPS, DEFAULTS,
  panelResize, isLoopback, validateBaseUrl, urlWarning, loadConfig, saveConfig,
  clampToArea, defaultMascotPosition, panelPosition, sanitizeText, postCoach,
};
