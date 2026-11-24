'use strict';
const el = id => document.getElementById(id);
const MAX_FILE = 24 * 1024 * 1024;
const MAX_SEND = 5 * 1024 * 1024;
let reviewed = '';
let busy = false;

function status(message) { el('status').textContent = message; }

async function run(message, action) {
  if (busy) return;
  busy = true;
  status(message);
  const controls = document.querySelectorAll('button:not(#cancel), select, input');
  for (const control of controls) control.disabled = true;
  try { await action(); }
  catch (error) { status(error.message || 'Could not prepare this screenshot. Try another file.'); }
  finally {
    for (const control of controls) control.disabled = false;
    busy = false;
  }
}

function clearPreview() {
  reviewed = '';
  el('preview').removeAttribute('src');
  el('review').hidden = true;
  el('choose').hidden = false;
  el('file').value = '';
  el('picker').hidden = true;
  el('sources').replaceChildren();
  el('crop').open = false;
}

async function present(url) {
  const preview = el('preview');
  reviewed = '';
  el('review').hidden = true;
  el('choose').hidden = false;
  preview.src = url;
  await preview.decode();
  reviewed = url;
  const w = preview.naturalWidth, h = preview.naturalHeight;
  el('dimensions').textContent = w + ' × ' + h + ' pixels';
  for (const [id, value] of Object.entries({ left: 0, top: 0, width: w, height: h })) el(id).value = value;
  el('choose').hidden = true;
  el('review').hidden = false;
  el('crop').open = false;
  status('');
}

async function render(image, x, y, width, height) {
  const scale = Math.min(1, 2560 / Math.max(width, height));
  const canvas = document.createElement('canvas');
  canvas.width = Math.max(1, Math.round(width * scale));
  canvas.height = Math.max(1, Math.round(height * scale));
  const ctx = canvas.getContext('2d', { alpha: false });
  ctx.fillStyle = '#fff';
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  ctx.imageSmoothingQuality = 'high';
  ctx.drawImage(image, x, y, width, height, 0, 0, canvas.width, canvas.height);
  const limit = Math.ceil(MAX_SEND / 3) * 4;
  try {
    let url = canvas.toDataURL('image/png');
    if (url.length > limit) url = canvas.toDataURL('image/jpeg', 0.9);
    if (url.length > limit) throw new Error('Open a smaller screenshot.');
    await present(url);
  } finally { canvas.width = canvas.height = 0; }
}

// Read dimensions before invoking an image decoder on a potentially huge file.
function fileSize(bytes) {
  const view = new DataView(bytes);
  if (view.byteLength >= 24 && view.getUint32(0) === 0x89504e47 && view.getUint32(4) === 0x0d0a1a0a &&
      view.getUint32(12) === 0x49484452) return [view.getUint32(16), view.getUint32(20), 'image/png'];
  if (view.byteLength >= 4 && view.getUint16(0) === 0xffd8) {
    let pos = 2;
    while (pos + 9 < view.byteLength && view.getUint8(pos++) === 0xff) {
      while (view.getUint8(pos) === 0xff) pos++;
      const marker = view.getUint8(pos++);
      const length = view.getUint16(pos);
      if (length < 2 || pos + length > view.byteLength || marker === 0xda) break;
      if ([0xc0, 0xc1, 0xc2].includes(marker) && length >= 8)
        return [view.getUint16(pos + 5), view.getUint16(pos + 3), 'image/jpeg'];
      pos += length;
    }
  }
  throw new Error('Choose a valid PNG or JPEG screenshot.');
}

async function handleSources(result) {
  if (result.error) throw new Error(result.error);
  if (result.preview) {
    const image = new Image();
    image.src = result.preview;
    await image.decode();
    await render(image, 0, 0, image.naturalWidth, image.naturalHeight);
  } else {
    el('sources').replaceChildren(...result.sources.map(s => new Option(s.name, s.id)));
    el('picker').hidden = false;
    status('Select the source to capture.');
  }
}

for (const button of document.querySelectorAll('[data-source]')) {
  button.onclick = () => run('Finding capture sources…', async () => {
    el('picker').hidden = true;
    await handleSources(await window.capture.list(button.dataset.source));
  });
}
el('take').onclick = () => run('Capturing…', async () => {
  el('picker').hidden = true;
  await handleSources(await window.capture.take(el('sources').value));
});
el('browse').onclick = () => el('file').click();
el('file').onchange = () => run('Preparing screenshot…', async () => {
  const file = el('file').files[0];
  el('file').value = '';
  if (!file) { status(''); return; }
  if (file.size > MAX_FILE) throw new Error('Choose a screenshot under 24 MiB.');
  const bytes = await file.arrayBuffer();
  const [w, h, mime] = fileSize(bytes);
  if (!w || !h || w * h > 32000000 || Math.max(w, h) > 16384)
    throw new Error('Image dimensions are too large or invalid. Crop the file before opening it.');
  const image = await createImageBitmap(new Blob([bytes], { type: mime }));
  try { await render(image, 0, 0, image.width, image.height); }
  finally { image.close(); }
});
el('apply').onclick = () => run('Applying crop…', async () => {
  const img = el('preview');
  const [x, y, w, h] = ['left', 'top', 'width', 'height'].map(id => el(id).valueAsNumber);
  if (![x, y, w, h].every(Number.isInteger) || x < 0 || y < 0 || w < 1 || h < 1 ||
      x + w > img.naturalWidth || y + h > img.naturalHeight) throw new Error('The crop must fit inside the screenshot.');
  await render(img, x, y, w, h);
});
el('retake').onclick = () => { clearPreview(); status('Choose a new source.'); };
el('cancel').onclick = () => window.close();
window.addEventListener('keydown', e => { if (e.key === 'Escape') window.close(); });
el('send').onclick = () => run('Sending screenshot for analysis…', async () => {
  if (!reviewed || !el('privacy').textContent) throw new Error('Review a screenshot before sending.');
  if (el('crop').open) throw new Error('Apply the crop or close the crop controls to send the current preview.');
  const [header, image] = reviewed.split(',');
  const result = await window.capture.send(header.slice(5, -7), image);
  if (result.error) throw new Error(result.error);
  clearPreview();
  el('choose').hidden = true;
  el('answer').textContent = result.answer;
  el('cancel').textContent = 'Close';
  status('Analysis complete.');
});
window.capture.destination().then(({ destination }) => {
  if (destination) el('privacy').textContent = 'Analyze Screenshot sends this preview to ' + destination +
    ' and Google Gemini for scene improvement suggestions.';
}).catch(() => status('Could not load the analysis destination. Close and reopen capture.'));
