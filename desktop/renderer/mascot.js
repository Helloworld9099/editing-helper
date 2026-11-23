(async () => {
  'use strict';
  const pet = document.getElementById('pet');
  const api = window.coach;
  const cfg = await api.getConfig();
  const canDrag = !(cfg && cfg.normal);   // in normal-window mode the window manager moves it
  const THRESHOLD = 5;

  let start = null, moved = false, dragging = false;

  pet.addEventListener('pointerdown', (e) => {
    if (e.button !== 0) return;
    start = { x: e.screenX, y: e.screenY };
    moved = dragging = false;
    pet.setPointerCapture(e.pointerId);
    if (canDrag) api.mascot.dragStart();
  });

  pet.addEventListener('pointermove', (e) => {
    if (!start) return;
    if (!moved && Math.hypot(e.screenX - start.x, e.screenY - start.y) < THRESHOLD) return;
    moved = true;
    if (!canDrag) return;
    dragging = true;
    pet.classList.add('dragging');
    api.mascot.dragMove();
  });

  function finish(e, cancelled) {
    if (!start) return;
    const wasDragging = dragging, wasMoved = moved;
    start = null; moved = dragging = false;
    pet.classList.remove('dragging');
    try { pet.releasePointerCapture(e.pointerId); } catch { /* already released */ }
    if (wasDragging) api.mascot.dragEnd();      // drag: keep position, don't open the panel
    else if (!wasMoved && !cancelled) api.mascot.click();   // plain click: toggle the panel
  }
  pet.addEventListener('pointerup', (e) => finish(e, false));
  pet.addEventListener('pointercancel', (e) => finish(e, true));

  pet.addEventListener('contextmenu', (e) => { e.preventDefault(); api.mascot.menu(); });
  pet.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); api.mascot.click(); }
    else if (e.key === 'ContextMenu' || (e.shiftKey && e.key === 'F10')) { e.preventDefault(); api.mascot.menu(); }
  });

  api.on('mascot:busy', (b) => pet.classList.toggle('busy', !!b));
  api.on('mascot:badge', (b) => pet.classList.toggle('badge-on', !!b));
})();
