import { contextBridge, ipcRenderer } from 'electron'

const IPC = {
  backendConfig: 'desktop:backend-config',
  selectDirectory: 'desktop:select-directory',
  selectFiles: 'desktop:select-files',
  saveFile: 'desktop:save-file',
  openExternal: 'desktop:open-external',
} as const

interface SelectFilesOptions {
  title?: string
  filters?: Array<{ name: string; extensions: string[] }>
  multiple?: boolean
}

interface SaveFileOptions {
  title?: string
  defaultPath?: string
  filters?: Array<{ name: string; extensions: string[] }>
}

const desktopBridge = Object.freeze({
  getBackendConfig: () => ipcRenderer.invoke(IPC.backendConfig),
  selectDirectory: () => ipcRenderer.invoke(IPC.selectDirectory),
  selectFiles: (options?: SelectFilesOptions) =>
    ipcRenderer.invoke(IPC.selectFiles, options),
  saveFile: (options?: SaveFileOptions) => ipcRenderer.invoke(IPC.saveFile, options),
  openExternal: (url: string) => ipcRenderer.invoke(IPC.openExternal, url),
})

contextBridge.exposeInMainWorld('circuitDesktop', desktopBridge)
