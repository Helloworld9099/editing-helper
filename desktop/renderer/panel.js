(() => {
  'use strict';
  const api = window.coach;
  const log = document.getElementById('log');
  const input = document.getElementById('input');
  const sendBtn = document.getElementById('send');
  const status = document.getElementById('status');
  const examples = document.getElementById('examples');
  const counter = document.getElementById('count');
  const clearBtn = document.getElementById('clear');
  const MAX_CHARS = 1000;
  let busy = false;
  let messageCount = 0;

  function syncControls() {
    const length = input.value.length;
    counter.textContent = length + ' / ' + MAX_CHARS;
    counter.classList.toggle('near-limit', length >= MAX_CHARS);
    sendBtn.disabled = busy || !input.value.trim() || length > MAX_CHARS;
    clearBtn.disabled = busy || messageCount === 0;
    log.classList.toggle('empty', messageCount === 0);
  }

  // Only AI replies use sanitized Markdown; user input and errors remain literal text.
  function addMessage(kind, who, text, sources = []) {
    const el = document.createElement('div');
    el.className = 'msg ' + kind;
    if (who) {
      const w = document.createElement('div');
      w.className = 'who';
      w.textContent = who;
      el.appendChild(w);
    }
    if (kind === 'note') {
      const mark = document.createElement('span');
      mark.className = 'note-mark';
      mark.setAttribute('aria-hidden', 'true');
      mark.textContent = '✦';
      const title = document.createElement('h2');
      title.textContent = 'Good edits start here.';
      el.appendChild(mark);
      el.appendChild(title);
    }
    const body = document.createElement('div');
    body.className = 'body';
    if (kind === 'coach' && window.editingCoachMarkdown?.renderInto) {
      window.editingCoachMarkdown.renderInto(body, text);
    } else {
      body.textContent = text;
    }
    el.appendChild(body);
    if (kind === 'coach') {
      const refs = Array.isArray(sources) ? sources : [];
      const foot = document.createElement('div');
      foot.className = 'source-foot';
      if (refs.length) {
        const reviewed = refs.filter(ref => ref.review_status === 'source_checked');
        const linkOnly = refs.filter(ref => ref.review_status !== 'source_checked');
        for (const [group, labelText] of [
          [reviewed, 'Source-reviewed notes'],
          [linkOnly, 'Further reading (links only)'],
        ]) {
          if (!group.length) continue;
          const label = document.createElement('div');
          label.className = 'source-label';
          label.textContent = labelText;
          foot.appendChild(label);
          for (const ref of group) {
            const button = document.createElement('button');
            button.className = 'source-link';
            button.type = 'button';
            button.textContent = (ref.source_kind === 'official' ? 'Official: ' : 'Community: ') + ref.title;
            button.title = 'Open original reference in your browser';
            button.setAttribute('aria-label', 'Open source: ' + ref.title);
            button.addEventListener('click', () => { void api.openSource(ref.url); });
            foot.appendChild(button);
          }
        }
      } else {
        foot.textContent = 'AI guidance · no matching documentation found';
      }
      el.appendChild(foot);
    }
    if (kind === 'error') el.setAttribute('role', 'alert');
    log.appendChild(el);
    if (kind !== 'note') {
      messageCount++;
      examples.hidden = true;
      syncControls();
    }
    if (kind === 'coach') el.scrollIntoView({ block: 'start' });   // long answers open at the top
    else log.scrollTop = log.scrollHeight;
  }

  function setBusy(b) {
    busy = b;
    status.textContent = b ? 'Thinking' : '';
    status.classList.toggle('busy', b);
    syncControls();
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
    syncControls();
    addMessage('user', 'You', q);
    let result;
    try {
      result = await api.ask(q);            // network happens in the main process; UI stays live
    } catch {
      result = { ok: false, message: 'Something went wrong inside the app. Try again.' };
    }
    setBusy(false);
    if (result && result.ok) {
      addMessage('coach', 'Coach', result.answer, result.sources);
    } else {
      addMessage('error', null, (result && result.message) || 'Something went wrong. Try again.');
      if (!input.value.trim()) input.value = q;   // let the user retry without retyping
    }
    syncControls();
    // Deliberately no input.focus() here: a reply must never pull focus back from your editor.
  }

  const grip = document.getElementById('resize');
  let resize = null;
  grip.addEventListener('pointerdown', (e) => {
    if (e.button !== 0 || resize) return;
    grip.setPointerCapture(e.pointerId);
    resize = { id: e.pointerId, x: e.screenX, y: e.screenY };
    api.resizePanel('start');
  });
  function moveGrip(e) {
    if (resize?.id !== e.pointerId) return;
    api.resizePanel('move', e.screenX - resize.x, e.screenY - resize.y);
  }
  function endGrip(e) {
    if (resize?.id !== e.pointerId) return;
    resize = null;
    api.resizePanel('end');
  }
  grip.addEventListener('pointermove', moveGrip);
  grip.addEventListener('pointerup', endGrip);
  grip.addEventListener('pointercancel', endGrip);
  grip.addEventListener('lostpointercapture', endGrip);
  grip.addEventListener('keydown', (e) => {
    const directions = { ArrowLeft: [-16, 0], ArrowRight: [16, 0], ArrowUp: [0, -16], ArrowDown: [0, 16] };
    if (!Object.hasOwn(directions, e.key)) return;
    e.preventDefault();
    api.resizePanel('key', ...directions[e.key]);
  });

  sendBtn.addEventListener('click', submit);
  input.addEventListener('input', syncControls);
  examples.querySelectorAll('[data-prompt]').forEach((button) => {
    button.addEventListener('click', () => {
      input.value = button.dataset.prompt;
      syncControls();
      input.focus();
    });
  });
  clearBtn.addEventListener('click', () => {
    if (busy || messageCount === 0) return;
    log.replaceChildren();
    api.clearSources?.();
    messageCount = 0;
    examples.hidden = false;
    input.value = '';
    syncControls();
    void showEditor();
    input.focus();
  });
  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); submit(); }
  });
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape') api.closePanel(); });
  document.getElementById('collapse').addEventListener('click', () => api.closePanel());
  document.getElementById('settings').addEventListener('click', () => api.openSettings());

  async function showEditor() {
    let cfg;
    try { cfg = await api.getConfig(); } catch { /* show the generic guidance */ }
    const app = cfg && cfg.editor ? cfg.editor + (cfg.editorVersion ? ' ' + cfg.editorVersion : '') : '';
    const prior = log.querySelector('.note');
    const note = app ? `Ask about ${app}. Related references appear when available; other advice is unverified.` : 'Choose your editor in Settings.';
    if (prior) prior.querySelector('.body').textContent = note;
    else addMessage('note', null, note);
  }
  api.on('panel:side', (side) => {
    if (side === 'left' || side === 'right') document.body.dataset.panelSide = side;
  });
  api.on('panel:config-changed', () => { void showEditor(); });
  api.on('panel:shown', () => { input.focus(); void showEditor(); });
  syncControls();
  void showEditor();
})();
