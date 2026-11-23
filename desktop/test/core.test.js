'use strict';
const { test } = require('node:test');
const assert = require('node:assert/strict');
const http = require('node:http');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const core = require('../src/core');

// ---- mock backend -------------------------------------------------------
function startServer(handler) {
  return new Promise((resolve) => {
    const state = { hits: 0, body: null };
    const srv = http.createServer((req, res) => {
      state.hits++;
      let data = '';
      req.on('data', (c) => { data += c; });
      req.on('end', () => {
        state.body = data; state.method = req.method; state.path = req.url;
        handler(req, res, state);
      });
    });
    srv.listen(0, '127.0.0.1', () => resolve({ srv, state, url: `http://127.0.0.1:${srv.address().port}` }));
  });
}
const json = (res, code, obj) => { res.writeHead(code, { 'Content-Type': 'application/json' }); res.end(JSON.stringify(obj)); };
async function withServer(handler, fn) {
  const s = await startServer(handler);
  try { await fn(s); } finally { s.srv.closeAllConnections?.(); s.srv.close(); }
}

test('ok: sends {"question"} to POST /v1/coach and returns sanitized answer', () =>
  withServer((req, res) => json(res, 200, { answer: 'Press C for razor.\u0000\u001b' }), async (s) => {
    const r = await core.postCoach({ baseUrl: s.url + '/', question: '  how to cut? ' });
    assert.deepEqual(r, { ok: true, answer: 'Press C for razor.' });
    assert.equal(s.state.method, 'POST');
    assert.equal(s.state.path, '/v1/coach');
    assert.deepEqual(JSON.parse(s.state.body), { question: 'how to cut?' });
  }));

test('offline: connection refused', async () => {
  const s = await startServer(() => {});
  const url = s.url; s.srv.close();
  await new Promise((r) => setTimeout(r, 50));
  const r = await core.postCoach({ baseUrl: url, question: 'hi', timeoutMs: 3000 });
  assert.equal(r.ok, false); assert.equal(r.kind, 'offline');
  assert.match(r.message, /Can't reach the coach server/);
});

test('timeout: slow server', () =>
  withServer(() => { /* never answers */ }, async (s) => {
    const t0 = Date.now();
    const r = await core.postCoach({ baseUrl: s.url, question: 'hi', timeoutMs: 300 });
    assert.equal(r.kind, 'timeout');
    assert.ok(Date.now() - t0 < 2000);
  }));

test('http 500 shows status and detail', () =>
  withServer((req, res) => json(res, 500, { detail: 'ollama unavailable' }), async (s) => {
    const r = await core.postCoach({ baseUrl: s.url, question: 'hi' });
    assert.equal(r.kind, 'http');
    assert.match(r.message, /500/); assert.match(r.message, /ollama unavailable/);
  }));

test('http 422 with non-string detail has no detail text', () =>
  withServer((req, res) => json(res, 422, { detail: [{ msg: 'x' }] }), async (s) => {
    const r = await core.postCoach({ baseUrl: s.url, question: 'hi' });
    assert.equal(r.kind, 'http'); assert.match(r.message, /422/);
  }));

test('unexpected shapes: html, missing answer, non-string answer, empty answer', async () => {
  const cases = [
    (req, res) => { res.writeHead(200); res.end('<html>hi</html>'); },
    (req, res) => json(res, 200, { reply: 'x' }),
    (req, res) => json(res, 200, { answer: ['x'] }),
    (req, res) => json(res, 200, { answer: '   ' }),
    (req, res) => json(res, 200, 'just a string'),
  ];
  for (const h of cases) {
    await withServer(h, async (s) => {
      const r = await core.postCoach({ baseUrl: s.url, question: 'hi' });
      assert.equal(r.kind, 'unexpected');
    });
  }
});

test('redirects are not followed', () =>
  withServer((req, res) => { res.writeHead(307, { Location: 'http://127.0.0.1:1/x' }); res.end(); }, async (s) => {
    const r = await core.postCoach({ baseUrl: s.url, question: 'hi' });
    assert.equal(r.kind, 'unexpected'); assert.match(r.message, /redirect/);
  }));

test('oversized reply is rejected', () =>
  withServer((req, res) => { res.writeHead(200); res.end('x'.repeat(core.MAX_RESPONSE_BYTES + 5000)); }, async (s) => {
    const r = await core.postCoach({ baseUrl: s.url, question: 'hi' });
    assert.equal(r.kind, 'unexpected');
  }));

test('input validation happens before any request', () =>
  withServer((req, res) => json(res, 200, { answer: 'x' }), async (s) => {
    assert.equal((await core.postCoach({ baseUrl: s.url, question: '   ' })).kind, 'empty');
    assert.equal((await core.postCoach({ baseUrl: s.url, question: 'x'.repeat(5000) })).kind, 'empty');
    assert.equal((await core.postCoach({ baseUrl: 'ftp://x', question: 'hi' })).kind, 'config');
    assert.equal(s.state.hits, 0);
  }));

test('HTML in a reply stays literal text', () =>
  withServer((req, res) => json(res, 200, { answer: '<img src=x onerror=alert(1)>' }), async (s) => {
    const r = await core.postCoach({ baseUrl: s.url, question: 'hi' });
    assert.equal(r.answer, '<img src=x onerror=alert(1)>');   // untouched; the UI uses textContent
  }));

// ---- URLs ---------------------------------------------------------------
test('validateBaseUrl', () => {
  assert.equal(core.validateBaseUrl(' http://h:8000// ').url, 'http://h:8000');
  for (const bad of ['', 'h:8000', 'http://', 'http://u:p@h', 'http://h?x=1', 'http://h:99999', 'http://a b', 'javascript:alert(1)']) {
    assert.ok(core.validateBaseUrl(bad).error, bad);
  }
});

test('urlWarning only for plain http to non-loopback', () => {
  assert.equal(core.urlWarning('http://127.0.0.1:8000'), '');
  assert.equal(core.urlWarning('http://localhost:8000'), '');
  assert.equal(core.urlWarning('https://coach.example.com'), '');
  assert.match(core.urlWarning('http://coach.example.com'), /unencrypted/);
});

// ---- config -------------------------------------------------------------
const tmpFile = () => path.join(fs.mkdtempSync(path.join(os.tmpdir(), 'coach-')), 'sub', 'config.json');

test('config: defaults, roundtrip, atomic write', () => {
  const f = tmpFile();
  assert.deepEqual(core.loadConfig(f), core.DEFAULTS);
  const c = { ...core.DEFAULTS, setupDone: true, editor: 'DaVinci Resolve', editorVersion: '24.08', mascotX: -5, mascotY: 300, apiBaseUrl: 'https://coach.example.com' };
  core.saveConfig(c, f);
  assert.deepEqual(core.loadConfig(f), c);
  assert.ok(!fs.existsSync(f + '.tmp'));
});

test('config: corrupt file is set aside and defaults used', () => {
  const f = tmpFile(); fs.mkdirSync(path.dirname(f), { recursive: true }); fs.writeFileSync(f, '{nope');
  assert.deepEqual(core.loadConfig(f), core.DEFAULTS);
  assert.ok(fs.existsSync(f + '.corrupt'));
});

test('config: bad values fall back to defaults', () => {
  const f = tmpFile(); fs.mkdirSync(path.dirname(f), { recursive: true });
  fs.writeFileSync(f, JSON.stringify({ setupDone: 'yes', apiBaseUrl: 'javascript:x', windowMode: 'weird', mascotX: true, mascotY: '5', timeoutSeconds: 99999, extra: 1 }));
  assert.deepEqual(core.loadConfig(f), core.DEFAULTS);
});

// ---- geometry -----------------------------------------------------------
const area = { x: 0, y: 0, width: 1920, height: 1080 };

test('clampToArea keeps window on screen, including offset displays', () => {
  assert.deepEqual(core.clampToArea(5000, -50, 96, 96, area, 8), { x: 1920 - 96 - 8, y: 8 });
  const second = { x: 1920, y: 0, width: 1280, height: 720 };
  const p = core.clampToArea(100, 900, 96, 96, second, 8);   // saved spot from a vanished monitor
  assert.ok(p.x >= 1928 && p.y <= 720 - 96 - 8);
});

test('default mascot position is at the right edge', () => {
  const p = core.defaultMascotPosition(96, area);
  assert.ok(p.x > 1700 && p.y > 0 && p.y < 1080 - 96);
});

test('panelPosition: opens toward the roomy side and stays on screen', () => {
  const panel = { width: 380, height: 520 };
  const right = core.panelPosition({ x: 1800, y: 500, width: 96, height: 96 }, panel, area);
  assert.ok(right.x + 380 < 1800);
  const left = core.panelPosition({ x: 20, y: 500, width: 96, height: 96 }, panel, area);
  assert.ok(left.x > 116);
  const corner = core.panelPosition({ x: 1800, y: 1000, width: 96, height: 96 }, panel, area);
  assert.ok(corner.x >= 0 && corner.x + 380 <= 1920 && corner.y >= 0 && corner.y + 520 <= 1080);
});

test('sanitizeText strips control characters but keeps newlines', () => {
  assert.equal(core.sanitizeText('a\u0000b\u001b[31m\r\nc\td'), 'ab[31m\nc\td');
});

test('config: preserves a supported editor and resets unsupported legacy picks', () => {
  const f = tmpFile();
  assert.equal(core.loadConfig(f).editor, '');
  for (const editor of ['DaVinci Resolve', '', 'Kdenlive']) {
    core.saveConfig({ ...core.DEFAULTS, setupDone: true, editor, editorVersion: '20' }, f);
    const cfg = core.loadConfig(f);
    assert.equal(cfg.setupDone, editor === 'DaVinci Resolve');
    assert.equal(cfg.editor, cfg.setupDone ? editor : '');
    assert.equal(cfg.editorVersion, cfg.setupDone ? '20' : '');
  }
});

test('client sends the selected editor and optional version; rejects unsupported editors', async () => {
  await withServer((req, res) => json(res, 200, { answer: 'Step one' }), async (s) => {
    for (const version of ['', '20.1']) {
      const result = await core.postCoach({ baseUrl: s.url, question: 'How?', editor: 'DaVinci Resolve', version });
      assert.equal(result.ok, true);
      assert.deepEqual(JSON.parse(s.state.body), { question: 'How?', editor: 'DaVinci Resolve', ...(version && { version }) });
    }
    assert.equal((await core.postCoach({ baseUrl: s.url, question: 'How?', editor: 'Shotcut' })).kind, 'config');
  });
});

test('mascot zoom cycles through fixed levels and persists separately from drag position', () => {
  let size = core.DEFAULTS.mascotSize;
  assert.equal(size, 96);
  for (const next of [120, 144, 96]) {
    size = core.nextMascotSize(size);
    assert.equal(size, next);
  }
  const f = tmpFile();
  core.saveConfig({ ...core.DEFAULTS, mascotSize: 144, mascotX: 22, mascotY: 23 }, f);
  assert.equal(core.loadConfig(f).mascotSize, 144);
  fs.writeFileSync(f, JSON.stringify({ mascotSize: 9999 }));
  assert.equal(core.loadConfig(f).mascotSize, 96);
});
