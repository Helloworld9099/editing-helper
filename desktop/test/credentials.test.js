'use strict';
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { canStoreToken, saveToken, readToken, clearToken } = require('../src/credentials');

function tempPath(t) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'editing-coach-credentials-'));
  t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
  return path.join(dir, 'access-token.enc');
}

function fakeStore(backend = 'gnome_libsecret') {
  return {
    getSelectedStorageBackend: () => backend,
    isAsyncEncryptionAvailable: async () => true,
    encryptStringAsync: async (value) => Buffer.from('ENC:' + Buffer.from(value).toString('base64')),
    decryptStringAsync: async (ciphertext) => {
      const text = ciphertext.toString('utf8');
      if (!text.startsWith('ENC:')) throw Error('bad cipher');
      return { result: Buffer.from(text.slice(4), 'base64').toString('utf8'), shouldReEncrypt: false };
    },
  };
}

test('secure keyring stores token without plaintext and recovers it after relaunch', async (t) => {
  const file = tempPath(t), fake = fakeStore();
  assert.equal(await canStoreToken(fake, 'linux'), true);
  assert.equal(await readToken(file, fake, 'linux'), '');
  const secret = 'the-test-token-123_abc';
  await saveToken(file, secret, fake, 'linux');
  assert.ok(fs.existsSync(file));
  assert.ok(!fs.readFileSync(file, 'utf8').includes(secret));
  assert.equal(await readToken(file, fake, 'linux'), secret);
  if (process.platform !== 'win32') assert.equal(fs.statSync(file).mode & 0o777, 0o600);
  await saveToken(file, 'replacement-test-token', fake, 'linux');
  assert.equal(await readToken(file, fake, 'linux'), 'replacement-test-token');
  clearToken(file);
  assert.equal(await readToken(file, fake, 'linux'), '');
  clearToken(file);
});

test('Linux basic_text and unknown backend are never used to persist secrets', async (t) => {
  for (const backend of ['basic_text', 'unknown', '']) {
    const file = tempPath(t), fake = fakeStore(backend);
    assert.equal(await canStoreToken(fake, 'linux'), false);
    await assert.rejects(saveToken(file, 'private-token', fake, 'linux'), /keyring unavailable/);
    assert.equal(fs.existsSync(file), false);
  }
});

test('unavailable crypto never writes plaintext or returns a stored token', async (t) => {
  const file = tempPath(t);
  const fake = fakeStore();
  fake.isAsyncEncryptionAvailable = async () => false;
  assert.equal(await canStoreToken(fake, 'linux'), false);
  await assert.rejects(saveToken(file, 'token', fake, 'linux'), /keyring unavailable/);
  assert.equal(await readToken(file, fake, 'linux'), '');
});

test('corrupted credential cannot be used and can be overwritten', async (t) => {
  const file = tempPath(t), fake = fakeStore();
  fs.writeFileSync(file, Buffer.from('tampered'));
  assert.equal(await readToken(file, fake, 'linux'), '');
  await saveToken(file, 'restored', fake, 'linux');
  assert.equal(await readToken(file, fake, 'linux'), 'restored');
});

test('Windows and macOS do not need Linux-specific backend names', async (t) => {
  const file = tempPath(t), fake = fakeStore('unknown');
  assert.equal(await canStoreToken(fake, 'darwin'), true);
  await saveToken(file, 'mac-token', fake, 'darwin');
  assert.equal(await readToken(file, fake, 'darwin'), 'mac-token');
  assert.equal(await canStoreToken(fake, 'win32'), true);
});
