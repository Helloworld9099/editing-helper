'use strict';
// Public email-code sign-in via Supabase Auth. No service-role key, model key, or shared secret.
const credentials = require('./credentials');

function releaseReady(config) {
  try {
    const api = new URL(config.apiBaseUrl);
    const auth = new URL(config.supabaseUrl);
    return config.authentication === 'user-accounts'
      && api.protocol === 'https:' && !api.username && !api.password
      && api.pathname === '/' && !api.search && !api.hash
      && auth.protocol === 'https:' && auth.pathname === '/'
      && !auth.username && !auth.password && !auth.search && !auth.hash
      && typeof config.supabasePublishableKey === 'string'
      && config.supabasePublishableKey.length > 12;
  } catch { return false; }
}

function validEmail(email) {
  return typeof email === 'string' && email.length <= 254
    && /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email.trim());
}

function makePublicAuth({ config, storageFile, safeStorage, transport = globalThis.fetch,
                          store = credentials, now = () => Date.now() }) {
  let session = null;
  let emailAddress = '';
  let storedRefresh = '';
  let persistence = false;
  const configured = releaseReady(config);

  function status() {
    return { configured, signedIn: Boolean(session?.accessToken),
             email: session ? emailAddress : '', remembered: persistence };
  }

  async function call(path, body, token = '') {
    if (!configured) throw Error('Public service is not configured yet.');
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 15000);
    let response;
    try {
      response = await transport(config.supabaseUrl.replace(/\/$/, '') + '/auth/v1/' + path, {
        method: 'POST',
        redirect: 'error',
        signal: controller.signal,
        headers: {
          'Content-Type': 'application/json',
          apikey: config.supabasePublishableKey,
          ...(token ? { Authorization: 'Bearer ' + token } : {}),
        },
        body: JSON.stringify(body),
      });
    } catch {
      throw Error('Could not reach the sign-in service. Check your connection.');
    } finally { clearTimeout(timer); }
    if (!response?.ok) {
      if (response?.status === 429) throw Error('Too many sign-in attempts. Try again later.');
      if (response?.status === 401 || response?.status === 403) throw Error('The code or session is invalid or expired.');
      throw Error('Sign-in was unsuccessful. Check your details and try again.');
    }
    try { return await response.json(); } catch { return {}; }
  }

  async function remember() {
    if (!session?.refreshToken || !persistence) return;
    await store.saveToken(storageFile, JSON.stringify({
      origin: config.supabaseUrl, refresh_token: session.refreshToken,
      email: emailAddress,
    }), safeStorage);
  }

  function accept(raw, fallbackEmail = '') {
    if (!raw || typeof raw.access_token !== 'string' ||
        !/^[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$/.test(raw.access_token) ||
        typeof raw.refresh_token !== 'string' || raw.refresh_token.length < 8) {
      throw Error('Sign-in did not return a valid session.');
    }
    const expiry = Number(raw.expires_in);
    if (!Number.isFinite(expiry) || expiry <= 0) throw Error('Invalid session lifetime.');
    session = {
      accessToken: raw.access_token, refreshToken: raw.refresh_token,
      expiresAt: now() + Math.min(expiry, 86400) * 1000,
    };
    emailAddress = raw.user?.email || fallbackEmail;
    storedRefresh = raw.refresh_token;
  }

  async function initialize() {
    if (!configured) return status();
    persistence = await store.canStoreToken(safeStorage);
    if (!persistence) return status();
    let saved;
    try { saved = JSON.parse(await store.readToken(storageFile, safeStorage)); }
    catch { return status(); }
    if (!saved || saved.origin !== config.supabaseUrl || typeof saved.refresh_token !== 'string') {
      return status();
    }
    storedRefresh = saved.refresh_token;
    emailAddress = saved.email || '';
    try { await refresh(); } catch { /* offline users can retry sign-in later */ }
    return status();
  }

  async function requestCode(email) {
    if (!validEmail(email)) throw Error('Enter a valid email address.');
    // Requires an email OTP template with {{ .Token }} and custom SMTP in Supabase.
    await call('otp', { email: email.trim(), create_user: true });
    return { ok: true };
  }

  async function verifyCode(email, token) {
    if (!validEmail(email) || typeof token !== 'string' || !/^\d{6,8}$/.test(token.trim())) {
      throw Error('Enter the email address and verification code.');
    }
    const raw = await call('verify', { type: 'email', email: email.trim(), token: token.trim() });
    accept(raw, email.trim());
    try { await remember(); }
    catch { persistence = false; } // Current session still works without a secure keyring.
    return status();
  }

  async function refresh() {
    const refreshToken = session?.refreshToken || storedRefresh;
    if (!refreshToken) return '';
    let raw;
    try { raw = await call('token?grant_type=refresh_token', { refresh_token: refreshToken }); }
    catch (e) {
      if (/invalid or expired/i.test(e.message)) {
        session = null; storedRefresh = '';
        try { store.clearToken(storageFile); } catch { /* ignore */ }
      }
      throw e;
    }
    accept(raw, emailAddress);
    try { await remember(); } catch { persistence = false; }
    return session.accessToken;
  }

  async function accessToken() {
    if (!configured) return '';
    if (session && session.expiresAt > now() + 90000) return session.accessToken;
    if (session?.refreshToken || storedRefresh) return refresh();
    return '';
  }

  async function signOut() {
    const priorToken = session?.accessToken || '';
    session = null; storedRefresh = ''; emailAddress = '';
    try { store.clearToken(storageFile); } catch { /* keep user signed out in this process */ }
    if (priorToken) {
      try { await call('logout', {}, priorToken); } catch { /* local logout remains effective */ }
    }
    return status();
  }

  return { status, initialize, requestCode, verifyCode, accessToken, signOut };
}

module.exports = { makePublicAuth, releaseReady, validEmail };
