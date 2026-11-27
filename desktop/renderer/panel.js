(() => {
  'use strict';
  const api = window.coach;
  const log = document.getElementById('log');
  const input = document.getElementById('input');
  const sendBtn = document.getElementById('send');
  const counter = document.getElementById('count');
  const clearBtn = document.getElementById('clear');
  const attachBtn = document.getElementById('attach-video');
  const removeBtn = document.getElementById('remove-video');
  const picker = document.getElementById('video-file');
  const attachment = document.getElementById('attachment');
  const preview = document.getElementById('preview');
  const filename = document.getElementById('filename');
  const clipDetail = document.getElementById('clip-detail');
  const MAX_CHARS = 1000;
  const MAX_VIDEO_BYTES = 10 * 1024 * 1024;
  let busy = false;
  let clip = null;
  let messageCount = 0;
  let typingBubble = null;

  function syncControls() {
    const length = input.value.length;
    counter.textContent = length + ' / ' + MAX_CHARS;
    counter.classList.toggle('near-limit', length >= MAX_CHARS);
    const hasDraft = Boolean(input.value.trim() || clip);
    sendBtn.disabled = busy || !hasDraft || length > MAX_CHARS;
    clearBtn.disabled = busy || !hasDraft;
    attachBtn.disabled = busy;
    removeBtn.disabled = busy;
    log.classList.toggle('empty', messageCount === 0);
    if (messageCount > 0) log.querySelector('.note')?.remove();
  }

  function removeClip() {
    if (!clip) return;
    URL.revokeObjectURL(clip.url);
    clip = null;
    preview.removeAttribute('src');
    preview.load();
    attachment.hidden = true;
    syncControls();
  }

  function selectClip() {
    const file = picker.files[0];
    picker.value = '';
    if (busy || !file) return;
    const extension = file.name.split('.').pop().toLowerCase();
    if (!/\.(mp4|mov|webm)$/i.test(file.name)) {
      addMessage('error', null, 'Choose an MP4, MOV or WebM video.');
      return;
    }
    if (!file.size || file.size > MAX_VIDEO_BYTES) {
      addMessage('error', null, 'Choose a video up to 10 MiB that is between 1 and 5 seconds long.');
      return;
    }
    removeClip();
    clip = { file, extension, url: URL.createObjectURL(file) };
    filename.textContent = file.name;
    filename.title = file.name;
    clipDetail.textContent = '1–5 second reference';
    preview.hidden = false;
    attachment.hidden = false;
    preview.src = clip.url;
    syncControls();
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
      const title = document.createElement('h2');
      title.textContent = 'Good edits start here.';
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
        foot.textContent = 'AI guidance';
      }
      el.appendChild(foot);
    }
    if (kind === 'error') el.setAttribute('role', 'alert');
    log.appendChild(el);
    if (kind !== 'note') {
      messageCount++;
      syncControls();
    }
    if (kind === 'coach') el.scrollIntoView({ block: 'start' });   // long answers open at the top
    else log.scrollTop = log.scrollHeight;
  }

  function setBusy(b) {
    busy = b;
    if (b && !typingBubble) {
      typingBubble = document.createElement('div');
      typingBubble.className = 'msg coach typing';
      typingBubble.setAttribute('role', 'status');
      typingBubble.setAttribute('aria-label', 'Coach is preparing a reply');
      for (let i = 0; i < 3; i++) {
        const dot = document.createElement('span');
        dot.className = 'typing-dot';
        dot.setAttribute('aria-hidden', 'true');
        typingBubble.appendChild(dot);
      }
      log.appendChild(typingBubble);
      log.scrollTop = log.scrollHeight;
    } else if (!b && typingBubble) {
      typingBubble.remove();
      typingBubble = null;
    }
    syncControls();
  }

  async function submit() {
    if (busy) return;                       // no duplicate submits
    const q = input.value.trim();
    if (!q && !clip) return;
    if (q.length > MAX_CHARS) {
      addMessage('error', null, `That question is too long (limit ${MAX_CHARS} characters).`);
      return;
    }
    input.value = '';
    const reference = clip;
    const label = reference ? reference.file.name : '';
    addMessage('user', 'You', [q, label].filter(Boolean).join('\n'));
    setBusy(true);
    let result;
    try {
      result = reference
        ? await api.analyzeVideo(q, reference.extension, await reference.file.arrayBuffer())
        : await api.ask(q);
    } catch {
      result = { ok: false, message: 'Something went wrong inside the app. Try again.' };
    }
    setBusy(false);
    if (result && result.ok) {
      if (reference) removeClip();
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
  attachBtn.addEventListener('click', () => picker.click());
  picker.addEventListener('change', selectClip);
  removeBtn.addEventListener('click', () => {
    removeClip();
    attachBtn.focus();
  });
  preview.addEventListener('loadedmetadata', () => {
    if (!clip || preview.currentSrc !== clip.url) return;
    const seconds = preview.duration;
    if (!Number.isFinite(seconds)) return;
    if (!busy && (seconds < 1 || seconds > 5)) {
      removeClip();
      addMessage('error', null, 'The video must be between 1 and 5 seconds long.');
      return;
    }
    clipDetail.textContent = `${seconds.toFixed(2)} s`;
  });
  preview.addEventListener('error', () => {
    if (!clip || preview.currentSrc !== clip.url) return;
    preview.hidden = true;
    clipDetail.textContent = 'Preview unavailable. You can still submit the clip.';
  });
  clearBtn.addEventListener('click', () => {
    if (clearBtn.disabled) return;
    log.replaceChildren();
    api.clearSources?.();
    messageCount = 0;
    input.value = '';
    removeClip();
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
    if (messageCount > 0 || busy) return;
    const prior = log.querySelector('.note');
    const note = app ? `Ask about ${app}.` : 'Choose your editor in Settings.';
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
