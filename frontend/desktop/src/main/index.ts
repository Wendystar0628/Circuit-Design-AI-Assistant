import { randomBytes } from 'node:crypto'
import { existsSync } from 'node:fs'
import { createServer } from 'node:net'
import { join, resolve } from 'node:path'
import { spawn, type ChildProcess } from 'node:child_process'
import { pathToFileURL } from 'node:url'

import {
  app,
  BrowserWindow,
  dialog,
  ipcMain,
  Menu,
  shell,
  type FileFilter,
} from 'electron'

const BACKEND_HOST = '127.0.0.1'
const BACKEND_START_TIMEOUT_MS = 20_000
const BACKEND_STOP_TIMEOUT_MS = 2_000

const IPC = {
  backendConfig: 'desktop:backend-config',
  selectDirectory: 'desktop:select-directory',
  selectFiles: 'desktop:select-files',
  saveFile: 'desktop:save-file',
  openExternal: 'desktop:open-external',
} as const

interface BackendConnectionConfig {
  baseUrl: string
  wsUrl: string
  token: string
  apiVersion: 'v1'
}

interface OpenFilesOptions {
  title?: unknown
  filters?: unknown
  multiple?: unknown
}

interface SavePathOptions {
  title?: unknown
  defaultPath?: unknown
  filters?: unknown
}

let mainWindow: BrowserWindow | null = null
let sidecarProcess: ChildProcess | null = null
let backendConfig: BackendConnectionConfig | null = null
let shutdownPromise: Promise<void> | null = null
let shutdownComplete = false
let windowActivationPending = false

function delay(milliseconds: number): Promise<void> {
  return new Promise((resolveDelay) => setTimeout(resolveDelay, milliseconds))
}

async function reserveLoopbackPort(): Promise<number> {
  const server = createServer()
  server.unref()
  await new Promise<void>((resolveListen, rejectListen) => {
    server.once('error', rejectListen)
    server.listen(0, BACKEND_HOST, () => resolveListen())
  })
  const address = server.address()
  if (!address || typeof address === 'string') {
    server.close()
    throw new Error('Unable to reserve a backend port')
  }
  await new Promise<void>((resolveClose, rejectClose) => {
    server.close((error) => (error ? rejectClose(error) : resolveClose()))
  })
  return address.port
}

function findRepositoryRoot(): string {
  const candidates = [
    resolve(app.getAppPath(), '..', '..'),
    resolve(process.cwd(), '..', '..'),
    process.cwd(),
  ]
  for (const candidate of candidates) {
    if (
      existsSync(join(candidate, 'requirements.txt')) &&
      existsSync(join(candidate, 'application'))
    ) {
      return candidate
    }
  }
  throw new Error('Cannot locate the Circuit Design AI repository root')
}

function developmentPython(repositoryRoot: string): string {
  const executable =
    process.platform === 'win32'
      ? join(repositoryRoot, 'circuit', 'Scripts', 'python.exe')
      : join(repositoryRoot, 'circuit', 'bin', 'python')
  if (!existsSync(executable)) {
    throw new Error(`Repository Python is missing: ${executable}`)
  }
  return executable
}

function productionBackendExecutable(): string {
  const fileName = process.platform === 'win32' ? 'desktop_backend.exe' : 'desktop_backend'
  const executable = join(process.resourcesPath, 'backend', fileName)
  if (!existsSync(executable)) {
    throw new Error(`Packaged backend is missing: ${executable}`)
  }
  return executable
}

async function waitForBackend(
  processHandle: ChildProcess,
  healthUrl: string,
  startupFailure: () => Error | null,
): Promise<void> {
  const deadline = Date.now() + BACKEND_START_TIMEOUT_MS
  while (Date.now() < deadline) {
    const failure = startupFailure()
    if (failure) {
      throw failure
    }
    if (processHandle.exitCode !== null) {
      throw new Error(`Backend exited during startup with code ${processHandle.exitCode}`)
    }
    const controller = new AbortController()
    const timeout = setTimeout(() => controller.abort(), 500)
    try {
      const response = await fetch(healthUrl, {
        cache: 'no-store',
        signal: controller.signal,
      })
      if (response.ok) {
        const health = (await response.json()) as Record<string, unknown>
        // A PyInstaller one-file executable starts an unpacking parent and then
        // runs the application in a child process, so the health process ID is
        // intentionally not required to match Electron's spawned parent PID.
        if (health.status === 'ok' && health.api_version === 'v1') {
          return
        }
      }
    } catch {
      // The backend is expected to refuse connections while it is booting.
    } finally {
      clearTimeout(timeout)
    }
    await delay(100)
  }
  throw new Error('Backend did not become healthy within 20 seconds')
}

async function startBackend(): Promise<BackendConnectionConfig> {
  const port = await reserveLoopbackPort()
  const token = randomBytes(32).toString('hex')
  const origin = `http://${BACKEND_HOST}:${port}`
  const rendererOrigin = app.isPackaged
    ? 'null'
    : new URL(requiredDevelopmentRendererUrl()).origin
  const commonArguments = [
    '--host',
    BACKEND_HOST,
    '--port',
    String(port),
    '--token',
    token,
    '--renderer-origin',
    rendererOrigin,
  ]

  let executable: string
  let arguments_: string[]
  let workingDirectory: string | undefined
  if (app.isPackaged) {
    executable = productionBackendExecutable()
    arguments_ = commonArguments
  } else {
    workingDirectory = findRepositoryRoot()
    executable = developmentPython(workingDirectory)
    arguments_ = ['-m', 'desktop_backend', ...commonArguments]
  }

  let failure: Error | null = null
  const processHandle = spawn(executable, arguments_, {
    cwd: workingDirectory,
    env: {
      ...process.env,
      PYTHONIOENCODING: 'utf-8',
      PYTHONUNBUFFERED: '1',
    },
    stdio: app.isPackaged ? 'ignore' : 'inherit',
    windowsHide: true,
  })
  sidecarProcess = processHandle
  processHandle.once('error', (error) => {
    failure = new Error(`Backend failed to start: ${error.message}`)
  })
  processHandle.once('exit', (code, signal) => {
    if (!failure && code !== 0) {
      failure = new Error(
        `Backend exited during startup (${code ?? signal ?? 'unknown'})`,
      )
    }
  })

  try {
    await waitForBackend(processHandle, `${origin}/health`, () => failure)
  } catch (error) {
    await terminateBackend()
    throw error
  }

  processHandle.once('exit', () => {
    if (sidecarProcess === processHandle && !shutdownPromise) {
      sidecarProcess = null
      dialog.showErrorBox(
        'Backend stopped',
        'The local Circuit Design AI backend stopped unexpectedly. The application will close.',
      )
      app.quit()
    }
  })

  return Object.freeze({
    baseUrl: origin,
    wsUrl: `ws://${BACKEND_HOST}:${port}/api/v1/events?token=${encodeURIComponent(token)}`,
    token,
    apiVersion: 'v1' as const,
  })
}

async function terminateWindowsProcessTree(pid: number): Promise<void> {
  await new Promise<void>((resolveKill) => {
    const killer = spawn('taskkill', ['/pid', String(pid), '/t', '/f'], {
      windowsHide: true,
      stdio: 'ignore',
    })
    killer.once('error', () => resolveKill())
    killer.once('exit', () => resolveKill())
  })
}

async function terminateBackend(): Promise<void> {
  const processHandle = sidecarProcess
  sidecarProcess = null
  if (!processHandle || processHandle.exitCode !== null) {
    return
  }
  const exited = new Promise<void>((resolveExit) => {
    processHandle.once('exit', () => resolveExit())
  })
  if (process.platform === 'win32' && processHandle.pid) {
    await terminateWindowsProcessTree(processHandle.pid)
  } else {
    processHandle.kill()
  }
  await Promise.race([exited, delay(BACKEND_STOP_TIMEOUT_MS)])
  if (processHandle.exitCode === null) {
    if (process.platform === 'win32' && processHandle.pid) {
      await terminateWindowsProcessTree(processHandle.pid)
    } else {
      processHandle.kill('SIGKILL')
    }
    await Promise.race([exited, delay(500)])
  }
}

function textOption(value: unknown, maximumLength = 240): string | undefined {
  if (typeof value !== 'string') {
    return undefined
  }
  const normalized = value.trim()
  return normalized ? normalized.slice(0, maximumLength) : undefined
}

function fileFilters(value: unknown): FileFilter[] | undefined {
  if (!Array.isArray(value)) {
    return undefined
  }
  const filters: FileFilter[] = []
  for (const rawFilter of value.slice(0, 20)) {
    if (!rawFilter || typeof rawFilter !== 'object') {
      continue
    }
    const record = rawFilter as Record<string, unknown>
    const name = textOption(record.name, 80)
    const extensions = Array.isArray(record.extensions)
      ? record.extensions
          .filter(
            (extension): extension is string =>
              typeof extension === 'string' && /^[a-zA-Z0-9_-]{1,16}$/.test(extension),
          )
          .slice(0, 30)
      : []
    if (name && extensions.length) {
      filters.push({ name, extensions })
    }
  }
  return filters.length ? filters : undefined
}

function registerIpcHandlers(): void {
  ipcMain.handle(IPC.backendConfig, () => {
    if (!backendConfig) {
      throw new Error('Backend connection is not ready')
    }
    return backendConfig
  })

  ipcMain.handle(IPC.selectDirectory, async () => {
    if (!mainWindow) {
      return null
    }
    const result = await dialog.showOpenDialog(mainWindow, {
      properties: ['openDirectory'],
    })
    return result.canceled ? null : result.filePaths[0] ?? null
  })

  ipcMain.handle(IPC.selectFiles, async (_event, options: OpenFilesOptions = {}) => {
    if (!mainWindow) {
      return []
    }
    const properties: Array<'openFile' | 'multiSelections'> = ['openFile']
    if (options.multiple === true) {
      properties.push('multiSelections')
    }
    const result = await dialog.showOpenDialog(mainWindow, {
      title: textOption(options.title),
      filters: fileFilters(options.filters),
      properties,
    })
    return result.canceled ? [] : result.filePaths
  })

  ipcMain.handle(IPC.saveFile, async (_event, options: SavePathOptions = {}) => {
    if (!mainWindow) {
      return null
    }
    const result = await dialog.showSaveDialog(mainWindow, {
      title: textOption(options.title),
      defaultPath: textOption(options.defaultPath, 2_048),
      filters: fileFilters(options.filters),
    })
    return result.canceled ? null : result.filePath ?? null
  })

  ipcMain.handle(IPC.openExternal, async (_event, rawUrl: unknown) => {
    const value = textOption(rawUrl, 2_048)
    if (!value) {
      throw new Error('External URL is required')
    }
    const target = new URL(value)
    if (!['https:', 'http:', 'mailto:'].includes(target.protocol)) {
      throw new Error(`External URL protocol is not allowed: ${target.protocol}`)
    }
    if (target.username || target.password) {
      throw new Error('External URLs with embedded credentials are not allowed')
    }
    await shell.openExternal(target.toString())
  })
}

function activateMainWindow(): void {
  const window = mainWindow
  if (!window) {
    windowActivationPending = true
    return
  }
  windowActivationPending = false
  if (window.isMinimized()) {
    window.restore()
  }
  if (!window.isVisible()) {
    window.show()
  }
  window.focus()
}

function requiredDevelopmentRendererUrl(): string {
  const value = process.env.ELECTRON_RENDERER_URL
  if (!value) {
    throw new Error('Electron renderer URL is missing in development mode')
  }
  const rendererUrl = new URL(value)
  if (
    rendererUrl.protocol !== 'http:' ||
    !['127.0.0.1', '::1', 'localhost'].includes(rendererUrl.hostname) ||
    !rendererUrl.port
  ) {
    throw new Error(`Electron renderer URL must use a loopback HTTP origin: ${value}`)
  }
  return rendererUrl.toString()
}

function createMainWindow(): BrowserWindow {
  const window = new BrowserWindow({
    width: 1560,
    height: 960,
    minWidth: 1180,
    minHeight: 720,
    show: false,
    autoHideMenuBar: true,
    backgroundColor: '#f4f7fb',
    webPreferences: {
      preload: join(__dirname, '../preload/index.js'),
      contextIsolation: true,
      sandbox: true,
      nodeIntegration: false,
      devTools: !app.isPackaged,
    },
  })

  window.webContents.setWindowOpenHandler(() => ({ action: 'deny' }))
  window.webContents.on('will-attach-webview', (event) => event.preventDefault())
  window.once('ready-to-show', () => {
    window.show()
    if (windowActivationPending) {
      activateMainWindow()
    }
  })
  window.on('closed', () => {
    if (mainWindow === window) {
      mainWindow = null
    }
  })

  const developmentUrl = app.isPackaged
    ? undefined
    : requiredDevelopmentRendererUrl()
  let loadPromise: Promise<void>
  if (developmentUrl) {
    const allowedOrigin = new URL(developmentUrl).origin
    window.webContents.on('will-navigate', (event, targetUrl) => {
      if (new URL(targetUrl).origin !== allowedOrigin) {
        event.preventDefault()
      }
    })
    loadPromise = window.loadURL(developmentUrl)
  } else {
    const entry = join(__dirname, '../renderer/index.html')
    const entryUrl = pathToFileURL(entry).toString()
    window.webContents.on('will-navigate', (event, targetUrl) => {
      if (targetUrl !== entryUrl) {
        event.preventDefault()
      }
    })
    loadPromise = window.loadFile(entry)
  }
  void loadPromise.catch((error: unknown) => {
    dialog.showErrorBox(
      'Circuit Design AI interface could not load',
      error instanceof Error ? error.message : String(error),
    )
    app.quit()
  })
  return window
}

const hasSingleInstanceLock = app.requestSingleInstanceLock()
if (!hasSingleInstanceLock) {
  app.quit()
} else {
  app.on('second-instance', () => {
    activateMainWindow()
  })

  app.whenReady().then(async () => {
    try {
      Menu.setApplicationMenu(null)
      backendConfig = await startBackend()
      registerIpcHandlers()
      mainWindow = createMainWindow()
    } catch (error) {
      dialog.showErrorBox(
        'Circuit Design AI could not start',
        error instanceof Error ? error.message : String(error),
      )
      app.quit()
    }
  })
}

app.on('window-all-closed', () => app.quit())

app.on('before-quit', (event) => {
  if (shutdownComplete) {
    return
  }
  event.preventDefault()
  if (!shutdownPromise) {
    shutdownPromise = terminateBackend().finally(() => {
      shutdownComplete = true
      app.quit()
    })
  }
})

process.on('SIGINT', () => app.quit())
process.on('SIGTERM', () => app.quit())
