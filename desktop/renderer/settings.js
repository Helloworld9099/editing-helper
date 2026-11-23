(async () => {
  'use strict';
  const api = window.coach;
  const mode = new URLSearchParams(location.search).get('mode') === 'setup' ? 'setup' : 'settings';
  document.body.dataset.mode = mode;
  const $ = (id) => document.getElementById(id);
  const editor = $('editor'), version = $('version'), url = $('url');
  const onTop = $('onTop'), normalMode = $('normalMode');
  const errorEl = $('error'), infoEl = $('info'), saveBtn = $('save');

  if (mode === 'setup') {
    $('title').textContent = 'Welcome to Editing Coach';
    saveBtn.textContent = 'Start';
  } else {
    $('intro').hidden = true;
  }

  const cfg = await api.getConfig();
  const supported = cfg.supportedApps || [];
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
  url.value = cfg.apiBaseUrl;
  onTop.checked = cfg.keepOnTop;
  normalMode.checked = cfg.windowMode === 'normal';

  function warnText(raw) {
    try {
      const u = new URL(raw.trim());
      const h = u.hostname.replace(/^\[|\]$/g, '').toLowerCase();
      const loop = h === 'localhost' || h === '::1' || h.startsWith('127.');
      if (u.protocol === 'http:' && !loop) {
        return 'Plain http:// sends your questions unencrypted. Prefer https:// for a hosted server.';
      }
    } catch { /* not a URL yet */ }
    return '';
  }
  url.addEventListener('input', () => { $('urlWarn').textContent = warnText(url.value); });
  $('urlWarn').textContent = warnText(url.value);

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
    errorEl.textContent = '';
    const payload = { editor: editor.value.trim(), editorVersion: version.value, finishSetup: mode === 'setup' };
    if (mode === 'settings') {
      Object.assign(payload, { apiBaseUrl: url.value, keepOnTop: onTop.checked, windowMode: normalMode.checked ? 'normal' : 'floating' });
    }
    const res = await api.saveConfig(payload);
    saving = false;
    if (!res || !res.ok) {
      const errs = (res && res.errors) || {};
      errorEl.textContent = errs.editor || errs.apiBaseUrl || errs.form || 'Could not save settings.';
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

  $('cancel').addEventListener('click', () => window.close());
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && mode === 'settings') window.close(); });
})();
