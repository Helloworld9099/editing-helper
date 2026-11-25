'use strict';
// The only bridge between the web UI and the app. The UI has no Node access and no network access.
const { contextBridge, ipcRenderer } = require('electron');

const EVENTS = new Set(['panel:shown', 'panel:side', 'mascot:busy', 'mascot:badge', 'panel:auth-changed', 'panel:screen-analysis', 'panel:config-changed']);

contextBridge.exposeInMainWorld('coach', {
  getConfig: () => ipcRenderer.invoke('config:get'),
  authStatus: () => ipcRenderer.invoke('auth:status'),
  requestSignInCode: (email) => ipcRenderer.invoke('auth:request-code', String(email)),
  verifySignInCode: (email, code) => ipcRenderer.invoke('auth:verify-code', String(email), String(code)),
  signOut: () => ipcRenderer.invoke('auth:sign-out'),
  openSignIn: () => ipcRenderer.send('auth:open'),
  saveConfig: (c) => ipcRenderer.invoke('config:save', c),
  ask: (question) => ipcRenderer.invoke('coach:ask', String(question)),
  openScreenAnalysis: () => ipcRenderer.invoke('panel:open-screen-analysis'),
  openSource: (url) => ipcRenderer.invoke('source:open', String(url)),
  clearSources: () => ipcRenderer.send('coach:clear-sources'),
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
