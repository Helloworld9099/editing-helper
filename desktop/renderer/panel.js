(() => {
  'use strict';
  const api = window.coach;
  const log = document.getElementById('log');
  const input = document.getElementById('input');
  const sendBtn = document.getElementById('send');
  const status = document.getElementById('status');
  const MAX_CHARS = 1000;
  let busy = false;

  // Everything is added with textContent: replies are shown as plain text, never as markup or script.
  function addMessage(kind, who, text) {
    const el = document.createElement('div');
    el.className = 'msg ' + kind;
    if (who) {
      const w = document.createElement('div');
      w.className = 'who';
      w.textContent = who;
      el.appendChild(w);
    }
    const body = document.createElement('div');
    body.className = 'body';
    body.textContent = text;
    el.appendChild(body);
    if (kind === 'error') el.setAttribute('role', 'alert');
    log.appendChild(el);
    if (kind === 'coach') el.scrollIntoView({ block: 'start' });   // long answers open at the top
    else log.scrollTop = log.scrollHeight;
  }

  function setBusy(b) {
    busy = b;
    sendBtn.disabled = b;
    status.textContent = b ? 'Thinking' : '';
    status.classList.toggle('busy', b);
  }

  async function submit() {
    if (busy) return;                       // no duplicate submits
    const q = input.value.trim();
    if (!q) return;
    if (q.length > MAX_CHARS) {
      addMessage('error', null, `That question is too long (limit ${MAX_CHARS} characters).`);
      return;
    }
    setBusy(true);
    input.value = '';
    addMessage('user', 'You', q);
    let result;
    try {
      result = await api.ask(q);            // network happens in the main process; UI stays live
    } catch {
      result = { ok: false, message: 'Something went wrong inside the app. Try again.' };
    }
    setBusy(false);
    if (result && result.ok) {
      addMessage('coach', 'Coach', result.answer);
    } else {
      addMessage('error', null, (result && result.message) || 'Something went wrong. Try again.');
      if (!input.value.trim()) input.value = q;   // let the user retry without retyping
    }
    // Deliberately no input.focus() here: a reply must never pull focus back from your editor.
  }

  sendBtn.addEventListener('click', submit);
  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); submit(); }
  });
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape') api.closePanel(); });
  document.getElementById('collapse').addEventListener('click', () => api.closePanel());
  document.getElementById('settings').addEventListener('click', () => api.openSettings());

  async function showEditor() {
    const cfg = await api.getConfig();
    const app = cfg && cfg.editor ? cfg.editor + (cfg.editorVersion ? ' ' + cfg.editorVersion : '') : '';
    const prior = log.querySelector('.note');
    const note = app ? `Ask about ${app}. Answers aren't checked against sources yet.` : 'Choose your editor in Settings.';
    if (prior) prior.querySelector('.body').textContent = note;
    else addMessage('note', null, note);
  }
  api.on('panel:shown', () => { input.focus(); void showEditor(); });
  void showEditor();
})();
