'use strict';
// The only bridge between the web UI and the app. The UI has no Node access and no network access.
const { contextBridge, ipcRenderer } = require('electron');

const EVENTS = new Set(['panel:shown', 'mascot:busy', 'mascot:badge']);

contextBridge.exposeInMainWorld('coach', {
  getConfig: () => ipcRenderer.invoke('config:get'),
  saveConfig: (c) => ipcRenderer.invoke('config:save', c),
  ask: (question) => ipcRenderer.invoke('coach:ask', String(question)),
  resizePanel: (action, dx, dy) => ipcRenderer.send('panel:resize', action, dx, dy),
  closePanel: () => ipcRenderer.send('panel:close'),
  openSettings: () => ipcRenderer.send('app:open-settings'),
  quit: () => ipcRenderer.send('app:quit'),
  mascot: {
    dragStart: () => ipcRenderer.send('mascot:drag-start'),
    dragMove: () => ipcRenderer.send('mascot:drag-move'),
    dragEnd: (moved) => ipcRenderer.send('mascot:drag-end', moved === true),
    click: () => ipcRenderer.send('mascot:click'),
    menu: () => ipcRenderer.send('mascot:menu'),
  },
  on: (channel, cb) => {
    if (!EVENTS.has(channel)) return () => {};
    const handler = (_e, payload) => cb(payload);
    ipcRenderer.on(channel, handler);
    return () => ipcRenderer.removeListener(channel, handler);
  },
});
