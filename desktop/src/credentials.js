'use strict';
// Store the hosted API bearer token in an OS-protected Electron safeStorage blob.
// No secret is written to config.json or exposed to the renderer.
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');

const LINUX_SECURE_BACKENDS = new Set(['gnome_libsecret', 'kwallet', 'kwallet5', 'kwallet6']);

async function canStoreToken(safeStorage, platform = process.platform) {
  if (!safeStorage || typeof safeStorage.isAsyncEncryptionAvailable !== 'function' ||
      typeof safeStorage.encryptStringAsync !== 'function' ||
      typeof safeStorage.decryptStringAsync !== 'function') return false;
  // Electron's Linux basic_text fallback uses a hardcoded password. Never persist secrets with it.
  if (platform === 'linux') {
    let backend;
    try { backend = safeStorage.getSelectedStorageBackend(); } catch { return false; }
    if (!LINUX_SECURE_BACKENDS.has(backend)) return false;
  }
  try { return (await safeStorage.isAsyncEncryptionAvailable()) === true; }
  catch { return false; }
}

async function readToken(file, safeStorage, platform = process.platform) {
  if (!(await canStoreToken(safeStorage, platform))) return '';
  let ciphertext;
  try { ciphertext = fs.readFileSync(file); } catch { return ''; }
  try {
    const decoded = await safeStorage.decryptStringAsync(ciphertext);
    return decoded && typeof decoded.result === 'string' ? decoded.result : '';
  } catch {
    // An inaccessible or corrupted keyring item is not a valid token.
    return '';
  }
}

async function saveToken(file, token, safeStorage, platform = process.platform) {
  if (!token || typeof token !== 'string') throw new Error('Enter a non-empty access token.');
  if (!(await canStoreToken(safeStorage, platform))) {
    throw new Error('Secure system keyring unavailable. Unlock GNOME Keyring/KWallet or use an environment token.');
  }
  const encrypted = await safeStorage.encryptStringAsync(token);
  if (!Buffer.isBuffer(encrypted) || !encrypted.length) throw new Error('Could not encrypt the access token.');
  fs.mkdirSync(path.dirname(file), { recursive: true, mode: 0o700 });
  const temporary = file + '.' + process.pid + '.' + crypto.randomBytes(6).toString('hex') + '.tmp';
  try {
    fs.writeFileSync(temporary, encrypted, { flag: 'wx', mode: 0o600 });
    fs.renameSync(temporary, file);
    if (process.platform !== 'win32') fs.chmodSync(file, 0o600);
  } finally {
    try { fs.unlinkSync(temporary); } catch { /* already renamed or cleaned up */ }
  }
}

function clearToken(file) {
  try { fs.unlinkSync(file); }
  catch (error) { if (error.code !== 'ENOENT') throw error; }
}

module.exports = { canStoreToken, readToken, saveToken, clearToken };
