'use strict';
const { contextBridge, ipcRenderer } = require('electron');
contextBridge.exposeInMainWorld('capture', {
  list: type => ipcRenderer.invoke('capture:list', type),
  take: id => ipcRenderer.invoke('capture:take', id),
  destination: () => ipcRenderer.invoke('capture:destination'),
  send: (mime_type, image) => ipcRenderer.invoke('capture:send', { mime_type, image }),
});
