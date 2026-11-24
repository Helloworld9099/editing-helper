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
  withServer((req, res) => {
    assert.equal(req.headers.authorization, undefined);
    json(res, 200, { answer: 'Press C for razor.\u0000\u001b' });
  }, async (s) => {
    const r = await core.postCoach({ baseUrl: s.url + '/', question: '  how to cut? ' });
    assert.deepEqual(r, { ok: true, answer: 'Press C for razor.' });
    assert.equal(s.state.method, 'POST');
    assert.equal(s.state.path, '/v1/coach');
    assert.deepEqual(JSON.parse(s.state.body), { question: 'how to cut?' });
  }));

test('sends the configured access token as a bearer header', () =>
  withServer((req, res) => {
    assert.equal(req.headers.authorization, 'Bearer test-coach-token');
    json(res, 200, { answer: 'Authorized' });
  }, async (s) => {
    const r = await core.postCoach({ baseUrl: s.url, question: 'Hi', accessToken: 'test-coach-token' });
    assert.deepEqual(r, { ok: true, answer: 'Authorized' });
    assert.deepEqual(JSON.parse(s.state.body), { question: 'Hi' });
  }));

test('rejects access tokens over plain HTTP to non-loopback hosts', async () => {
  const r = await core.postCoach({ baseUrl: 'http://coach.example.com', question: 'Hi', accessToken: 'token' });
  assert.equal(r.kind, 'config');
  assert.match(r.message, /HTTPS/);
});

test('only HTTPS source references are surfaced to the renderer', () =>
  withServer((req, res) => json(res, 200, {
    answer: 'A working answer',
    sources: [
      {title: 'Kdenlive Manual', url: 'https://docs.kdenlive.org/en/effects_and_filters.html',
       source_kind: 'official', version: '26.08'},
      {title: 'Unsafe', url: 'javascript:alert(1)', source_kind: 'official'},
      {title: 'Plain HTTP', url: 'http://example.com', source_kind: 'official'},
      {title: 'Embedded credentials', url: 'https://user:pass@example.com', source_kind: 'official'},
    ],
  }), async (s) => {
    const reply = await core.postCoach({ baseUrl: s.url, question: 'Help with effects' });
    assert.equal(reply.ok, true);
    assert.equal(reply.sources.length, 1);
    assert.equal(reply.sources[0].title, 'Kdenlive Manual');
    assert.equal(reply.sources[0].source_kind, 'official');
    assert.equal(reply.sources[0].version, '26.08');
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
    assert.equal(r.answer, '<img src=x onerror=alert(1)>');   // transport leaves raw text alone; renderer sanitizes Markdown
  }));

// ---- URLs ---------------------------------------------------------------
test('validateBaseUrl', () => {
  assert.equal(core.validateBaseUrl(' http://h:8000// ').url, 'http://h:8000');
  for (const bad of ['', 'h:8000', 'http://', 'http://u:p@h', 'http://h?x=1', 'http://h:99999', 'http://a b', 'javascript:alert(1)']) {
    assert.ok(core.validateBaseUrl(bad).error, bad);
  }
});

test('urlWarning only for plain http to non-loopback', () => {
  assert.equal(core.isLoopback('127.attacker.example'), false);
  assert.equal(core.isLoopback('127.0.0.1'), true);
  assert.equal(core.isLoopback('[::1]'), true);
  assert.match(core.urlWarning('http://127.attacker.example:8000'), /unencrypted/);
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

test('credentials: normal launch uses persisted URL and token; env can override independently', () => {
  const cfg = { ...core.DEFAULTS, apiBaseUrl: 'https://saved-service.code.run' };
  assert.deepEqual(core.activeConnection(cfg, 'saved-token', {}), {
    baseUrl: 'https://saved-service.code.run',
    accessToken: 'saved-token',
  });
  assert.deepEqual(core.activeConnection(cfg, 'saved-token', { EDITING_HELPER_API: 'https://new-service.code.run' }), {
    baseUrl: 'https://new-service.code.run',
    accessToken: '',
  });
  assert.deepEqual(core.activeConnection(cfg, 'saved-token', { EDITING_HELPER_API: 'https://saved-service.code.run/preview' }), {
    baseUrl: 'https://saved-service.code.run/preview',
    accessToken: 'saved-token',
  });
  assert.deepEqual(core.activeConnection(cfg, 'saved-token', { EDITING_HELPER_ACCESS_TOKEN: 'override-token' }), {
    baseUrl: 'https://saved-service.code.run',
    accessToken: 'override-token',
  });
  assert.deepEqual(core.activeConnection(cfg, 'saved-token', {
    EDITING_HELPER_API: 'https://new-service.code.run', EDITING_HELPER_ACCESS_TOKEN: 'explicit-token',
  }), {
    baseUrl: 'https://new-service.code.run',
    accessToken: 'explicit-token',
  });
});

test('public release uses publisher URL, never a shared developer credential', () => {
  const base = { apiBaseUrl: 'https://editor-api.example.com', authentication: 'user-accounts',
                 accessToken: 'shared-secret-must-not-leak' };
  assert.match(core.managedConnection(base).error, /sign-in is not implemented/);
  assert.equal(core.managedConnection(base).accessToken, undefined);
  assert.match(core.managedConnection({ apiBaseUrl: '', authentication: 'not-configured' }).error, /no public service/);
  assert.match(core.managedConnection({ apiBaseUrl: 'http://api.example.com', authentication: 'user-accounts' }).error, /no public service/);
  assert.match(core.managedConnection({ apiBaseUrl: 'https://editor-api.example.com', authentication: 'not-configured' }).error, /Public sign-in/);
});

test('config never stores bearer tokens even when passed extra fields', () => {
  const f = tmpFile();
  core.saveConfig({ ...core.DEFAULTS, accessToken: 'secret-never-in-config', editor: 'Kdenlive' }, f);
  assert.equal(fs.readFileSync(f, 'utf8').includes('secret-never-in-config'), false);
  assert.equal(core.loadConfig(f).accessToken, undefined);
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

test('speech bubble stays below the pet and inside the work area', () => {
  const pane = { width: 380, height: 520 };
  const cases = [
    { area, start: { x: 1700, y: 1000, width: 80, height: 80 } },
    { area: { x: -1280, y: 50, width: 1280, height: 720 }, start: { x: -1200, y: 690, width: 80, height: 80 } },
    { area: { x: 1920, y: 0, width: 1280, height: 720 }, start: { x: 3100, y: 640, width: 80, height: 80 } },
  ];
  for (const { area: work, start } of cases) {
    const pet = core.mascotPositionForBubble(start, pane, work);
    const bubble = core.panelPosition({ ...start, ...pet }, pane, work, -10);
    assert.equal(bubble.y, pet.y + 16);
    assert.ok(bubble.y >= pet.y, 'chat must never start above pet');
    assert.ok(bubble.y + pane.height <= work.y + work.height - 8);
    assert.ok(bubble.x >= work.x + 8);
    assert.ok(bubble.x + pane.width <= work.x + work.width - 8);
  }
  const bottomPet = core.mascotPositionForBubble({ x: 1700, y: 1020, width: 80, height: 80 }, pane, area);
  assert.equal(bottomPet.y, 536, 'pet moves up once rather than pushing the chat above it');
});

test('speech bubble top alignment holds over repeated simulated drag positions', () => {
  const work = { x: 0, y: 0, width: 1280, height: 720 };
  const pane = { width: 320, height: 400 };
  let previousSide = null;
  for (let i = 0; i < 200; i++) {
    const m = { x: i * 11 % 1300, y: i * 29 % 760, width: 80, height: 80 };
    const pet = core.mascotPositionForBubble(m, pane, work);
    const bubble = core.panelPosition({ ...m, ...pet }, pane, work, -10, 8, previousSide);
    previousSide = bubble.side;
    assert.equal(bubble.y, pet.y + 16);
    assert.ok(bubble.x >= 8 && bubble.x + pane.width <= work.width - 8);
    assert.ok(bubble.y + pane.height <= work.height - 8);
  }
});

test('panel follows on preferred side without flipping at midpoint', () => {
  const m = { x: 1070, y: 510, width: 80, height: 80 };
  const pane = { width: 380, height: 520 };
  const p = core.panelPosition(m, pane, area, 8, 8, 'right');
  assert.equal(p.side, 'right');
  assert.equal(p.x, 1158);
  const atEdge = core.panelPosition({ ...m, x: 1700 }, pane, area, 8, 8, 'right');
  assert.equal(atEdge.side, 'left');
  assert.ok(atEdge.x >= 8);
});

test('sanitizeText strips control characters but keeps newlines', () => {
  assert.equal(core.sanitizeText('a\u0000b\u001b[31m\r\nc\td'), 'ab[31m\nc\td');
});

const requestedEditors = [
  'Adobe Premiere Pro', 'DaVinci Resolve', 'Kdenlive', 'Shotcut', 'CapCut',
  'ACDSee Luxea', 'Lightworks', 'Clipchamp', 'OpenShot', 'Canva', 'iMovie',
];

test('catalog contains the eleven requested editing applications', () => {
  assert.deepEqual([...core.SUPPORTED_APPS], requestedEditors);
  assert.deepEqual([...core.UPCOMING_APPS], ['Final Cut Pro']);
  assert.equal(new Set(core.SUPPORTED_APPS).size, core.SUPPORTED_APPS.length);
});

test('config: preserves every supported editor and rejects unsupported or empty selections', () => {
  const f = tmpFile();
  assert.equal(core.loadConfig(f).editor, '');
  for (const editor of [...requestedEditors, '', 'Unknown Editor', 'Final Cut Pro']) {
    core.saveConfig({ ...core.DEFAULTS, setupDone: true, editor, editorVersion: '20' }, f);
    const cfg = core.loadConfig(f);
    const valid = requestedEditors.includes(editor);
    assert.equal(cfg.setupDone, valid, editor);
    assert.equal(cfg.editor, valid ? editor : '', editor);
    assert.equal(cfg.editorVersion, valid ? '20' : '', editor);
  }
});

test('client sends the selected editor and optional version; rejects unknown editors', async () => {
  await withServer((req, res) => json(res, 200, { answer: 'Step one' }), async (s) => {
    for (const editor of requestedEditors) {
      for (const version of ['', '20.1']) {
        const result = await core.postCoach({ baseUrl: s.url, question: 'How?', editor, version });
        assert.equal(result.ok, true, editor);
        assert.deepEqual(JSON.parse(s.state.body), { question: 'How?', editor, ...(version && { version }) });
      }
    }
    const hits = s.state.hits;
    assert.equal((await core.postCoach({ baseUrl: s.url, question: 'How?', editor: 'Unknown Editor' })).kind, 'config');
    assert.equal((await core.postCoach({ baseUrl: s.url, question: 'How?', editor: 'Final Cut Pro' })).kind, 'config');
    assert.equal(s.state.hits, hits, 'unsupported editors must be rejected before contacting the API');
  });
});

test('panel resize applies inward and outward deltas and respects screen edges', () => {
  const bounds = { x: 32, y: 40, width: 380, height: 520 };
  assert.deepEqual(core.panelResize(bounds, 100, 60, area), { width: 480, height: 580 });
  assert.deepEqual(core.panelResize(bounds, -30, -45, area), { width: 350, height: 475 });
  assert.deepEqual(core.panelResize(bounds, 0, 0, area), { width: 380, height: 520 });
  assert.deepEqual(core.panelResize(bounds, -9999, -9999, area), { width: 300, height: 300 });
  const secondary = { x: -1280, y: 0, width: 1280, height: 720 };
  assert.deepEqual(core.panelResize({ ...bounds, x: -600 }, 9999, 9999, secondary), { width: 592, height: 672 });
});

test('chat dimensions persist without changing the saved mascot position', () => {
  const f = tmpFile();
  core.saveConfig({ ...core.DEFAULTS, panelWidth: 660, panelHeight: 590, mascotX: 22, mascotY: 23 }, f);
  const cfg = core.loadConfig(f);
  assert.deepEqual([cfg.panelWidth, cfg.panelHeight, cfg.mascotX, cfg.mascotY], [660, 590, 22, 23]);
  fs.writeFileSync(f, JSON.stringify({ panelWidth: 9999, panelHeight: -1, mascotSize: 144 }));
  const invalid = core.loadConfig(f);
  assert.deepEqual([invalid.panelWidth, invalid.panelHeight], [380, 520]);
  assert.equal(invalid.mascotSize, undefined);
});
