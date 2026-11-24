'use strict';
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const script = fs.readFileSync(path.join(__dirname, '../renderer/markdown.js'), 'utf8');

function makeRenderer(marked, DOMPurify) {
  const window = { marked, DOMPurify };
  vm.runInNewContext(script, { window });
  return window.editingCoachMarkdown;
}

test('renders Markdown through an explicitly restricted sanitizer', () => {
  let options;
  let value;
  const markdown = makeRenderer(
    { parse: (text, config) => {
      assert.equal(text, '# Hello\n**Bold**');
      assert.equal(config.gfm, true);
      assert.equal(config.breaks, true);
      return '<h1>Hello</h1><strong>Bold</strong>';
    } },
    { sanitize: (html, settings) => {
      value = html;
      options = settings;
      return html;
    } },
  );
  const element = { innerHTML: '', textContent: '' };
  markdown.renderInto(element, '# Hello\n**Bold**');
  assert.equal(element.innerHTML, '<h1>Hello</h1><strong>Bold</strong>');
  assert.ok(options.ALLOWED_TAGS.includes('strong'));
  assert.ok(options.ALLOWED_TAGS.includes('ol'));
  assert.ok(options.ALLOWED_TAGS.includes('code'));
  for (const forbidden of ['script', 'iframe', 'img', 'svg', 'video', 'style']) {
    assert.ok(!options.ALLOWED_TAGS.includes(forbidden));
  }
  assert.ok(!options.ALLOWED_ATTR.includes('src'));
  assert.ok(!options.ALLOWED_ATTR.includes('onerror'));
  assert.equal(options.ALLOW_DATA_ATTR, false);
  assert.equal(options.ALLOW_ARIA_ATTR, false);
  assert.equal(value, element.innerHTML);
});

test('falls back to literal text when renderer libraries are missing', () => {
  const target = { textContent: '', innerHTML: '' };
  makeRenderer(undefined, undefined).renderInto(target, '<img src=x onerror=alert(1)>');
  assert.equal(target.textContent, '<img src=x onerror=alert(1)>');
  assert.equal(target.innerHTML, '');
});

test('falls back to literal text when parsing or sanitizing fails', () => {
  for (const [marked, sanitizer] of [
    [{ parse() { throw Error('parse error'); } }, { sanitize() { return 'bad'; } }],
    [{ parse() { return '<b>unsafe</b>'; } }, { sanitize() { throw Error('sanitize error'); } }],
  ]) {
    const target = { textContent: '', innerHTML: '' };
    makeRenderer(marked, sanitizer).renderInto(target, '**Normal**');
    assert.equal(target.textContent, '**Normal**');
    assert.equal(target.innerHTML, '');
  }
});
