#!/usr/bin/env node
'use strict';
// MOCK backend for testing the widget without Ollama. Not used by the app itself:
// the app has no mock/fallback mode. Listens on 127.0.0.1 only.
//   node tools/mock-backend.js [port]      (default 8001)
// Then in the widget: right-click pet -> Settings -> Server address = http://127.0.0.1:8001
//
// Type these as your question to trigger a behavior:
//   /slow    wait 8s, then reply        /err     HTTP 500 with detail
//   /bad     200 but not JSON           /noanswer  200 JSON without "answer"
//   /html    reply containing HTML      /long    120-line reply
//   /hang    never replies (tests timeout; set "timeoutSeconds": 5 in config.json first)
//   anything else: a short canned reply that echoes your question
const http = require('node:http');

const port = Number(process.argv[2] || process.env.PORT || 8001);
const send = (res, code, body, type = 'application/json') => {
  res.writeHead(code, { 'Content-Type': type });
  res.end(typeof body === 'string' ? body : JSON.stringify(body));
};

http.createServer((req, res) => {
  if (req.method !== 'POST' || req.url !== '/v1/coach') return send(res, 404, { detail: 'Not Found' });
  let raw = '';
  req.on('data', (c) => { raw += c; if (raw.length > 100000) req.destroy(); });
  req.on('end', () => {
    let q, editor, version;
    try { ({ question: q, editor, version } = JSON.parse(raw)); } catch { /* handled below */ }
    if (typeof q !== 'string') return send(res, 422, { detail: [{ msg: 'question must be a string' }] });
    const cmd = q.trim().split(/\s+/)[0];
    switch (cmd) {
      case '/slow': return void setTimeout(() => send(res, 200, { answer: 'MOCK: that took a while, but here I am.' }), 8000);
      case '/err': return send(res, 500, { detail: 'mock: ollama unavailable' });
      case '/bad': return send(res, 200, 'this is not json', 'text/plain');
      case '/noanswer': return send(res, 200, { reply: 'wrong field name' });
      case '/html': return send(res, 200, { answer: 'MOCK <b>bold?</b> <img src=x onerror=alert(1)> <script>alert(2)</script>' });
      case '/long': return send(res, 200, { answer: Array.from({ length: 120 }, (_, i) => `MOCK line ${i + 1}: scrolling test.`).join('\n') });
      case '/hang': return;   // never answer
      default: return send(res, 200, { answer: `MOCK reply (not the real coach).\nEditor: ${editor || "not sent"}${version ? " " + version : ""}\nYou asked: ${q.trim().slice(0, 200)}` });
    }
  });
}).listen(port, '127.0.0.1', () => console.log(`MOCK coach backend on http://127.0.0.1:${port}  (Ctrl+C to stop)`));
