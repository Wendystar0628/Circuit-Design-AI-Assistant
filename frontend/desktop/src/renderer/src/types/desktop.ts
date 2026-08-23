export interface BackendConnectionConfig {
  baseUrl: string
  wsUrl: string
  token: string
  apiVersion: 'v1'
}

export interface FileDialogFilter {
  name: string
  extensions: string[]
}

export interface SelectFilesOptions {
  title?: string
  filters?: FileDialogFilter[]
  multiple?: boolean
}

export interface SaveFileOptions {
  title?: string
  defaultPath?: string
  filters?: FileDialogFilter[]
}

export interface DesktopBridge {
  getBackendConfig(): Promise<BackendConnectionConfig>
  selectDirectory(): Promise<string | null>
  selectFiles(options?: SelectFilesOptions): Promise<string[]>
  saveFile(options?: SaveFileOptions): Promise<string | null>
  openExternal(url: string): Promise<void>
}

export interface DesktopProject {
  id: string
  name: string
  root: string
}

export interface BackendEvent {
  type: string
  sequence: number
  project_id: string | null
  context_id?: string
  session_id?: string
  run_id?: string
  job_id?: string
  [key: string]: unknown
}

declare global {
  interface Window {
    circuitDesktop: DesktopBridge
  }
}

export {}
