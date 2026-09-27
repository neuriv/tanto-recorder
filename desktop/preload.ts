import { contextBridge, ipcRenderer } from 'electron';
import type { RecorderAPI } from './types';

// Expose three fixed bridge operations; renderer code cannot access Node or raw ipcRenderer.
// Main validates the command and sender again before any disk, dialog or process operation.
// Copy only payload data into callbacks, withholding privileged Electron event objects.
const api: RecorderAPI = {
  call: (command, value) => ipcRenderer.invoke('recorder', command, value),
  onState: listener => { ipcRenderer.on('state', (_event, value) => listener(value)); },
  onCue: listener => { ipcRenderer.on('cue', (_event, name) => listener(name)); }
};
contextBridge.exposeInMainWorld('recorder', api);
