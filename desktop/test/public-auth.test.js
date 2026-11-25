'use strict';
const { test } = require('node:test');
const assert = require('node:assert/strict');
const { makePublicAuth, releaseReady, validEmail } = require('../src/public-auth');

const config = {
  apiBaseUrl: 'https://api.example.net',
  authentication: 'user-accounts',
  supabaseUrl: 'https://demo.supabase.co',
  supabasePublishableKey: 'sb_publishable_public_test',
};

function harness({ canStore = true } = {}) {
  let disk = '', nowMs = 0;
  const calls = [];
  const store = {
    canStoreToken: async () => canStore,
    readToken: async () => disk,
    saveToken: async (_file, value) => { disk = value; },
    clearToken: () => { disk = ''; },
  };
  const transport = async (url, init) => {
    calls.push({ url, options: init, body: JSON.parse(init.body) });
    if (url.endsWith('/otp')) return { ok: true, json: async () => ({}) };
    if (url.endsWith('/verify')) return { ok: true, json: async () => ({
      access_token: 'header.body.signature', refresh_token: 'long-refresh-secret',
      expires_in: 3600, user: { email: 'video@example.com' },
    }) };
    if (url.includes('grant_type=refresh_token')) {
      return { ok: true, json: async () => ({
        access_token: 'renewed.body.signature', refresh_token: 'rotated-refresh-secret',
        expires_in: 3600, user: { email: 'video@example.com' },
      }) };
    }
    if (url.endsWith('/logout')) return { ok: true, json: async () => ({}) };
    throw Error('Unexpected URL ' + url);
  };
  const make = () => makePublicAuth({
    config, storageFile: '/tmp/test.enc', safeStorage: {}, store, transport, now: () => nowMs,
  });
  return { make, calls, getDisk: () => disk, setDisk: v => { disk = v; }, setNow: n => { nowMs = n; } };
}

test('public release configuration must include HTTPS endpoints and user-account mode', () => {
  assert.equal(releaseReady(config), true);
  assert.equal(releaseReady({ ...config, apiBaseUrl: 'http://api.example.net' }), false);
  assert.equal(releaseReady({ ...config, authentication: 'not-configured' }), false);
  assert.equal(releaseReady({ ...config, supabasePublishableKey: '' }), false);
  assert.equal(validEmail('video@example.com'), true);
  assert.equal(validEmail('broken-address'), false);
});

test('passwordless OTP sends no service key and stores only refresh token', async () => {
  const t = harness();
  const auth = t.make();
  await auth.initialize();
  await auth.requestCode('video@example.com');
  await auth.verifyCode('video@example.com', '123456');
  assert.equal((await auth.accessToken()), 'header.body.signature');
  assert.equal(auth.status().signedIn, true);
  assert.equal(t.calls[0].url, 'https://demo.supabase.co/auth/v1/otp');
  assert.equal(t.calls[0].options.headers.apikey, config.supabasePublishableKey);
  assert.equal(t.calls[0].body.email, 'video@example.com');
  assert.equal(t.calls[1].body.type, 'email');
  assert.equal(t.calls[1].body.token, '123456');
  assert.equal(t.getDisk().includes('header.body.signature'), false);
  assert.equal(JSON.parse(t.getDisk()).refresh_token, 'long-refresh-secret');
});

test('restart restores from refresh token, automatic rotation and sign-out', async () => {
  const t = harness();
  const first = t.make();
  await first.initialize();
  await first.verifyCode('video@example.com', '123456');
  const second = t.make();
  assert.equal((await second.initialize()).signedIn, true);
  assert.equal(await second.accessToken(), 'renewed.body.signature');
  assert.equal(JSON.parse(t.getDisk()).refresh_token, 'rotated-refresh-secret');
  await second.signOut();
  assert.equal(second.status().signedIn, false);
  assert.equal(t.getDisk(), '');
});

test('no secure keyring still permits a temporary sign-in', async () => {
  const t = harness({ canStore: false });
  const auth = t.make();
  await auth.initialize();
  await auth.verifyCode('video@example.com', '123456');
  assert.equal(auth.status().remembered, false);
  assert.equal(await auth.accessToken(), 'header.body.signature');
  assert.equal(t.getDisk(), '');
});

test('bad code and invalid configuration never create sessions', async () => {
  const t = harness();
  const auth = t.make();
  await assert.rejects(auth.verifyCode('not-an-email', '123456'), /email address/);
  await assert.rejects(auth.verifyCode('video@example.com', 'abc'), /verification code/);
  assert.equal(auth.status().signedIn, false);
  const wrong = makePublicAuth({
    config: { ...config, authentication: 'not-configured' },
    storageFile: '/tmp/none', safeStorage: {}, transport: () => { throw Error('network'); },
  });
  await assert.rejects(wrong.requestCode('video@example.com'), /not configured/);
});
