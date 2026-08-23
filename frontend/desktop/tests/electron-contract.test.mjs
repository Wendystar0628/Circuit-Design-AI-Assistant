import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'
import test from 'node:test'

const desktopRoot = join(dirname(fileURLToPath(import.meta.url)), '..')
const projectRoot = join(desktopRoot, '..', '..')

async function source(relativePath) {
  return readFile(join(desktopRoot, relativePath), 'utf8')
}

test('Electron uses one isolated and sandboxed BrowserWindow', async () => {
  const main = await source('src/main/index.ts')
  assert.equal((main.match(/new BrowserWindow\s*\(/g) ?? []).length, 1)
  assert.match(main, /contextIsolation:\s*true/)
  assert.match(main, /sandbox:\s*true/)
  assert.match(main, /nodeIntegration:\s*false/)
  assert.match(main, /setWindowOpenHandler\(\(\) => \(\{ action: 'deny' \}\)\)/)
  assert.match(main, /const developmentUrl = app\.isPackaged\s*\? undefined/)
  assert.match(main, /app\.on\('second-instance', \(\) => \{\s*activateMainWindow\(\)/)
  assert.match(main, /if \(!window\.isVisible\(\)\) \{\s*window\.show\(\)/)
  assert.match(main, /windowActivationPending = true/)
  assert.match(main, /void loadPromise\.catch/)
})

test('preload exposes only the five approved desktop capabilities', async () => {
  const preload = await source('src/preload/index.ts')
  const exposedMethods = [
    'getBackendConfig',
    'selectDirectory',
    'selectFiles',
    'saveFile',
    'openExternal',
  ]
  for (const method of exposedMethods) {
    assert.match(preload, new RegExp(`\\b${method}\\b`))
  }
  assert.match(preload, /exposeInMainWorld\('circuitDesktop', desktopBridge\)/)
  assert.doesNotMatch(preload, /ipcRenderer:\s*ipcRenderer/)
  assert.doesNotMatch(preload, /send:\s*\(/)
})

test('REST URL contains the api-v1 prefix exactly once', async () => {
  const main = await source('src/main/index.ts')
  const api = await source('src/renderer/src/lib/api.ts')
  const baseUrl = 'http://127.0.0.1:43123'
  const requestPath = '/api/v1/project'
  const requestUrl = `${baseUrl}${requestPath}`

  assert.equal(requestUrl, 'http://127.0.0.1:43123/api/v1/project')
  assert.equal(requestUrl.match(/\/api\/v1/g)?.length, 1)
  assert.match(main, /baseUrl:\s*origin/)
  assert.doesNotMatch(main, /baseUrl:\s*`?\$\{origin\}\/api\/v1/)
  assert.match(api, /API path must start with \/api\/v1/)
  assert.match(api, /fetch\(`\$\{config\.baseUrl\}\$\{normalizeApiPath\(path\)\}`/)
})

test('sidecar launch has one dev and one packaged executable contract', async () => {
  const main = await source('src/main/index.ts')
  const builder = await source('electron-builder.yml')
  const packageConfig = JSON.parse(await source('package.json'))
  const spec = await readFile(join(projectRoot, 'desktop_backend.spec'), 'utf8')
  const requirements = await readFile(join(projectRoot, 'requirements.txt'), 'utf8')
  const launcher = await readFile(join(projectRoot, 'start-circuit-ai.bat'), 'utf8')
  assert.match(main, /arguments_ = \['-m', 'desktop_backend'/)
  assert.match(main, /process\.resourcesPath, 'backend', fileName/)
  assert.match(main, /randomBytes\(32\)\.toString\('hex'\)/)
  assert.match(main, /'--renderer-origin'/)
  assert.match(main, /app\.isPackaged\s*\? 'null'/)
  assert.match(main, /new URL\(requiredDevelopmentRendererUrl\(\)\)\.origin/)
  assert.match(main, /await waitForBackend/)
  assert.match(main, /await terminateBackend/)
  assert.match(main, /stdio:\s*app\.isPackaged\s*\?\s*'ignore'\s*:\s*'inherit'/)
  assert.match(main, /PYTHONIOENCODING:\s*'utf-8'/)
  assert.match(builder, /from: \.\.\/\.\.\/dist\/desktop_backend\.exe/)
  assert.match(builder, /to: backend\/desktop_backend\.exe/)
  assert.match(packageConfig.scripts['build:backend'], /desktop_backend\.spec/)
  assert.match(packageConfig.scripts.package, /^npm run build:backend && npm run build && electron-builder$/)
  assert.match(packageConfig.scripts['package:win'], /^npm run build:backend && npm run build && electron-builder --win$/)
  assert.match(spec, /desktop_backend" \/ "__main__\.py"/)
  assert.match(spec, /name="desktop_backend"/)
  assert.match(requirements, /^fastapi[^\r\n]*$/m)
  assert.match(requirements, /^uvicorn[^\r\n]*$/m)
  assert.match(requirements, /^pydantic[^\r\n]*$/m)
  assert.doesNotMatch(requirements, /PyQt6|qasync|pyqtgraph|matplotlib/i)
  assert.match(launcher, /cd \/d "%~dp0frontend\\desktop"/i)
  assert.match(launcher, /node -e "require\('electron'\)"/i)
  assert.match(launcher, /npm\.cmd run dev/i)
  assert.match(launcher, /:startup_failed/i)
  assert.match(launcher, /pause/i)
  assert.doesNotMatch(launcher, /python|main\.py|activate\.ps1/i)
})

test('renderer readiness and settings errors reflect real API transport state', async () => {
  const appState = await source('src/renderer/src/lib/app-state.tsx')
  const settings = await source('src/renderer/src/features/settings/SettingsFeature.tsx')

  assert.match(appState, /api\.get<[^;]+>\('\/api\/v1\/app\/state'\)/s)
  assert.match(appState, /state\.api_version !== 'v1' \|\| state\.ready !== true/)
  assert.match(settings, /const \[loadError, setLoadError\]/)
  assert.match(settings, /!loading && loadError/)
  assert.match(settings, /!loading && !loadError && modelConfig/)
})

test('Windows shutdown terminates the PyInstaller one-file process tree', async () => {
  const main = await source('src/main/index.ts')
  assert.doesNotMatch(main, /health\.pid\s*===\s*processHandle\.pid/)
  assert.match(
    main,
    /spawn\('taskkill', \['\/pid', String\(pid\), '\/t', '\/f'\]/,
  )
  assert.match(main, /process\.platform === 'win32' && processHandle\.pid/)
  assert.match(main, /await terminateWindowsProcessTree\(processHandle\.pid\)/)
  assert.match(main, /app\.on\('before-quit',[\s\S]*?shutdownPromise = terminateBackend\(\)/)
})
