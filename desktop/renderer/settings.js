(async () => {
  'use strict';
  const api = window.coach;
  const mode = new URLSearchParams(location.search).get('mode') === 'setup' ? 'setup' : 'settings';
  document.body.dataset.mode = mode;
  const $ = (id) => document.getElementById(id);
  const editor = $('editor'), version = $('version'), url = $('url');
  const onTop = $('onTop'), normalMode = $('normalMode');
  const accessToken = $('accessToken'), forgetToken = $('forgetToken'), tokenHint = $('tokenHint');
  const errorEl = $('error'), infoEl = $('info'), saveBtn = $('save');
  // Closing Settings must work even if configuration retrieval fails.
  $('cancel').addEventListener('click', () => window.close());
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && mode === 'settings') window.close(); });

  if (mode === 'setup') {
    $('title').textContent = 'Welcome to Editing Coach';
    saveBtn.textContent = 'Start';
  } else {
    $('intro').hidden = true;
  }

  let cfg;
  try { cfg = await api.getConfig(); } catch { /* handled below */ }
  if (!cfg || !Array.isArray(cfg.supportedApps)) {
    errorEl.textContent = 'Could not load settings. Close this window and reopen it.';
    saveBtn.disabled = true;
    return;
  }
  const developerMode = cfg.developerMode === true;
  document.body.dataset.developer = String(developerMode);
  const supported = cfg.supportedApps;
  for (const name of supported) editor.add(new Option(name, name));
  const upcoming = document.createElement('optgroup');
  upcoming.label = 'Coming soon';
  upcoming.disabled = true;
  for (const name of (cfg.upcomingApps || [])) {
    const option = new Option(name, name);
    option.disabled = true;
    upcoming.appendChild(option);
  }
  if (upcoming.children.length) editor.appendChild(upcoming);
  editor.value = supported.includes(cfg.editor) ? cfg.editor : '';
  version.value = cfg.editorVersion;
  onTop.checked = cfg.keepOnTop;
  normalMode.checked = cfg.windowMode === 'normal';

  // The public Settings window has no editable backend URL or shared token.
  if (developerMode) {
    url.value = cfg.apiBaseUrl || '';

    if (cfg.accessTokenSaved) {
      tokenHint.textContent = 'An encrypted access token is saved on this computer. Leave the field blank to keep it.';
    } else if (cfg.canSaveAccessToken) {
      tokenHint.textContent = 'Enter the token once to store it with your operating system keyring.';
    } else {
      tokenHint.textContent = 'Secure keyring unavailable. Unlock GNOME Keyring/KWallet to save a token, or use the launch environment variables.';
      accessToken.disabled = true;
    }
    if (cfg.environmentTokenActive) {
      tokenHint.textContent += ' A launch environment token currently overrides the saved token.';
    }
    forgetToken.disabled = !cfg.accessTokenSaved;
    forgetToken.addEventListener('change', () => {
      accessToken.disabled = Boolean(forgetToken.checked) || !cfg.canSaveAccessToken;
      if (forgetToken.checked) accessToken.value = '';
    });

    function warnText(raw) {
      try {
        const u = new URL(raw.trim());
        const h = u.hostname.replace(/^\[|\]$/g, '').toLowerCase();
        const loop = h === 'localhost' || h === '::1' || /^127\.(?:\d{1,3}\.){2}\d{1,3}$/.test(h);
        if (u.protocol === 'http:' && !loop) {
          return 'Plain http:// sends your questions unencrypted. Prefer https:// for a hosted server.';
        }
      } catch { /* not a URL yet */ }
      return '';
    }
    url.addEventListener('input', () => { $('urlWarn').textContent = warnText(url.value); });
    $('urlWarn').textContent = warnText(url.value);
  }

  let saving = false;
  $('form').addEventListener('submit', async (e) => {
    e.preventDefault();
    if (saving) return;
    if (!supported.includes(editor.value)) {
      errorEl.textContent = 'Choose a supported video editor.';
      editor.focus();
      return;
    }
    saving = true;
    saveBtn.disabled = true;
    errorEl.textContent = '';
    const payload = { editor: editor.value.trim(), editorVersion: version.value, finishSetup: mode === 'setup' };
    if (mode === 'settings') {
      Object.assign(payload, {
        keepOnTop: onTop.checked,
        windowMode: normalMode.checked ? 'normal' : 'floating',
      });
      if (developerMode) {
        Object.assign(payload, {
          apiBaseUrl: url.value,
          accessToken: accessToken.value,
          forgetAccessToken: forgetToken.checked,
        });
      }
    }
    let res;
    try { res = await api.saveConfig(payload); }
    catch { res = { ok: false, errors: { form: 'Could not save settings. Try again.' } }; }
    finally { saving = false; saveBtn.disabled = false; }
    if (!res || !res.ok) {
      const errs = (res && res.errors) || {};
      errorEl.textContent = errs.editor || errs.apiBaseUrl || errs.accessToken || errs.form || 'Could not save settings.';
      return;
    }
    if (res.restartNeeded) {
      infoEl.textContent = 'Saved. The window mode change applies the next time you start Editing Coach.';
      saveBtn.textContent = 'Close';
      saveBtn.type = 'button';
      saveBtn.addEventListener('click', () => window.close());
      return;
    }
    window.close();
  });

})();
