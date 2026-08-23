export const WORK_SESSION_STORAGE_KEY = 'circuit-design-ai.work-session.v1'
export const WORK_SESSION_VERSION = 1 as const

export const WORK_SESSION_SIMULATION_TABS = [
  'runs',
  'metrics',
  'chart',
  'waveform',
  'schematic',
  'analysis',
  'raw',
  'log',
  'export',
] as const

export type WorkSessionSimulationTab = typeof WORK_SESSION_SIMULATION_TABS[number]
export type WorkSessionCursorTarget = 'a' | 'b'
export type WorkSessionConversationSurface = 'conversation' | 'rag'

export interface WorkspaceDocumentSession {
  path: string
  unsavedContent: string | null
  savedContent: string | null
  cursorLine: number
  cursorColumn: number
  markdownPreview: boolean
}

export interface WorkspaceSession {
  openDocuments: WorkspaceDocumentSession[]
  activeDocumentPath: string | null
  explorerCollapsed: boolean
}

export interface SimulationSession {
  selectedResultPath: string | null
  activeTab: WorkSessionSimulationTab
  visibleSeriesIds: string[]
  cursorA: number | null
  cursorB: number | null
  cursorTarget: WorkSessionCursorTarget
}

export interface ConversationSession {
  sessionId: string | null
  activeSurface: WorkSessionConversationSurface
  draftText: string
}

export interface WorkSessionV1 {
  version: typeof WORK_SESSION_VERSION
  projectRoot: string | null
  workspace: WorkspaceSession
  simulation: SimulationSession
  conversation: ConversationSession
}

export interface WorkSessionStorage {
  getItem(key: string): string | null
  setItem(key: string, value: string): void
  removeItem(key: string): void
}

const SIMULATION_TAB_SET = new Set<string>(WORK_SESSION_SIMULATION_TABS)

function emptyWorkspaceSession(): WorkspaceSession {
  return {
    openDocuments: [],
    activeDocumentPath: null,
    explorerCollapsed: false,
  }
}

function emptySimulationSession(): SimulationSession {
  return {
    selectedResultPath: null,
    activeTab: 'runs',
    visibleSeriesIds: [],
    cursorA: null,
    cursorB: null,
    cursorTarget: 'a',
  }
}

function emptyConversationSession(): ConversationSession {
  return {
    sessionId: null,
    activeSurface: 'conversation',
    draftText: '',
  }
}

export function emptyWorkSession(projectRoot: string | null = null): WorkSessionV1 {
  return {
    version: WORK_SESSION_VERSION,
    projectRoot,
    workspace: emptyWorkspaceSession(),
    simulation: emptySimulationSession(),
    conversation: emptyConversationSession(),
  }
}

function recordValue(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null
}

function nullableString(value: unknown): string | null | undefined {
  return value === null || typeof value === 'string' ? value : undefined
}

function positiveInteger(value: unknown): number | undefined {
  return Number.isSafeInteger(value) && Number(value) >= 1 ? Number(value) : undefined
}

function finiteNumberOrNull(value: unknown): number | null | undefined {
  return value === null || (typeof value === 'number' && Number.isFinite(value))
    ? value
    : undefined
}

function normalizeWorkspaceDocument(value: unknown): WorkspaceDocumentSession | null {
  const document = recordValue(value)
  if (!document || typeof document.path !== 'string' || !document.path) return null
  const unsavedContent = nullableString(document.unsavedContent)
  const savedContent = nullableString(document.savedContent)
  const cursorLine = positiveInteger(document.cursorLine)
  const cursorColumn = positiveInteger(document.cursorColumn)
  if (
    unsavedContent === undefined
    || savedContent === undefined
    || cursorLine === undefined
    || cursorColumn === undefined
    || typeof document.markdownPreview !== 'boolean'
  ) return null
  return {
    path: document.path,
    unsavedContent,
    savedContent,
    cursorLine,
    cursorColumn,
    markdownPreview: document.markdownPreview,
  }
}

function normalizeWorkspace(value: unknown): WorkspaceSession | null {
  const workspace = recordValue(value)
  if (!workspace || !Array.isArray(workspace.openDocuments)) return null
  const openDocuments: WorkspaceDocumentSession[] = []
  const paths = new Set<string>()
  for (const value of workspace.openDocuments) {
    const document = normalizeWorkspaceDocument(value)
    if (!document || paths.has(document.path)) return null
    paths.add(document.path)
    openDocuments.push(document)
  }
  const activeDocumentPath = nullableString(workspace.activeDocumentPath)
  if (
    activeDocumentPath === undefined
    || typeof workspace.explorerCollapsed !== 'boolean'
    || (activeDocumentPath !== null && !paths.has(activeDocumentPath))
  ) return null
  return {
    openDocuments,
    activeDocumentPath,
    explorerCollapsed: workspace.explorerCollapsed,
  }
}

function normalizeSimulation(value: unknown): SimulationSession | null {
  const simulation = recordValue(value)
  if (!simulation || !Array.isArray(simulation.visibleSeriesIds)) return null
  if (
    !simulation.visibleSeriesIds.every((id) => typeof id === 'string' && Boolean(id))
    || typeof simulation.activeTab !== 'string'
    || !SIMULATION_TAB_SET.has(simulation.activeTab)
    || (simulation.cursorTarget !== 'a' && simulation.cursorTarget !== 'b')
  ) return null
  const selectedResultPath = nullableString(simulation.selectedResultPath)
  const cursorA = finiteNumberOrNull(simulation.cursorA)
  const cursorB = finiteNumberOrNull(simulation.cursorB)
  if (
    selectedResultPath === undefined
    || cursorA === undefined
    || cursorB === undefined
  ) return null
  return {
    selectedResultPath,
    activeTab: simulation.activeTab as WorkSessionSimulationTab,
    visibleSeriesIds: [...new Set(simulation.visibleSeriesIds as string[])],
    cursorA,
    cursorB,
    cursorTarget: simulation.cursorTarget,
  }
}

function normalizeConversation(value: unknown): ConversationSession | null {
  const conversation = recordValue(value)
  if (!conversation) return null
  const sessionId = nullableString(conversation.sessionId)
  if (
    sessionId === undefined
    || (conversation.activeSurface !== 'conversation' && conversation.activeSurface !== 'rag')
    || typeof conversation.draftText !== 'string'
  ) return null
  return {
    sessionId,
    activeSurface: conversation.activeSurface,
    draftText: conversation.draftText,
  }
}

export function normalizeWorkSession(value: unknown): WorkSessionV1 | null {
  const session = recordValue(value)
  if (!session || session.version !== WORK_SESSION_VERSION) return null
  const projectRoot = nullableString(session.projectRoot)
  const workspace = normalizeWorkspace(session.workspace)
  const simulation = normalizeSimulation(session.simulation)
  const conversation = normalizeConversation(session.conversation)
  if (
    projectRoot === undefined
    || (projectRoot !== null && !projectRoot.trim())
    || !workspace
    || !simulation
    || !conversation
  ) return null
  return {
    version: WORK_SESSION_VERSION,
    projectRoot,
    workspace,
    simulation,
    conversation,
  }
}

export function loadWorkSession(storage: WorkSessionStorage | null): WorkSessionV1 {
  if (!storage) return emptyWorkSession()
  try {
    const serialized = storage.getItem(WORK_SESSION_STORAGE_KEY)
    if (serialized === null) return emptyWorkSession()
    const normalized = normalizeWorkSession(JSON.parse(serialized))
    if (normalized) return normalized
  } catch {
    // Corrupt or inaccessible durable state is intentionally not migrated.
  }
  try {
    storage.removeItem(WORK_SESSION_STORAGE_KEY)
  } catch {
    // Persistence failure must not prevent the application from starting.
  }
  return emptyWorkSession()
}

export function persistWorkSession(
  storage: WorkSessionStorage | null,
  value: unknown,
): WorkSessionV1 {
  const normalized = normalizeWorkSession(value) ?? emptyWorkSession()
  if (storage) {
    try {
      storage.setItem(WORK_SESSION_STORAGE_KEY, JSON.stringify(normalized))
    } catch {
      // The in-memory session remains usable if durable browser storage fails.
    }
  }
  return normalized
}

export function sameProjectRoot(left: string | null, right: string | null): boolean {
  if (left === null || right === null) return left === right
  const normalize = (root: string) => {
    const slashed = root.trim().replaceAll('\\', '/').replace(/\/+/g, '/')
    const withoutTrailingSlash = slashed.length > 1 ? slashed.replace(/\/+$/, '') : slashed
    return withoutTrailingSlash.toLocaleLowerCase('en-US')
  }
  return normalize(left) === normalize(right)
}

function browserStorage(): WorkSessionStorage | null {
  if (typeof window === 'undefined') return null
  try {
    return window.localStorage
  } catch {
    return null
  }
}

function cloneSession(session: WorkSessionV1): WorkSessionV1 {
  return {
    ...session,
    workspace: {
      ...session.workspace,
      openDocuments: session.workspace.openDocuments.map((document) => ({ ...document })),
    },
    simulation: {
      ...session.simulation,
      visibleSeriesIds: [...session.simulation.visibleSeriesIds],
    },
    conversation: { ...session.conversation },
  }
}

let singletonSession: WorkSessionV1 | null = null

function currentSession(): WorkSessionV1 {
  if (!singletonSession) singletonSession = loadWorkSession(browserStorage())
  return singletonSession
}

function replaceSession(session: WorkSessionV1): WorkSessionV1 {
  singletonSession = persistWorkSession(browserStorage(), session)
  return cloneSession(singletonSession)
}

export function getWorkSession(): WorkSessionV1 {
  return cloneSession(currentSession())
}

export function beginWorkSessionProject(root: string): WorkSessionV1 {
  const normalizedRoot = root.trim()
  if (!normalizedRoot) throw new Error('Project root is required')
  const current = currentSession()
  if (sameProjectRoot(current.projectRoot, normalizedRoot)) return cloneSession(current)
  return replaceSession(emptyWorkSession(normalizedRoot))
}

export function forgetWorkSessionProject(root: string): WorkSessionV1 {
  const current = currentSession()
  if (!sameProjectRoot(current.projectRoot, root)) return cloneSession(current)
  return replaceSession(emptyWorkSession())
}

export function updateWorkspaceSession(root: string, workspace: WorkspaceSession): WorkSessionV1 {
  const current = currentSession()
  if (!sameProjectRoot(current.projectRoot, root)) return cloneSession(current)
  return replaceSession({ ...current, workspace })
}

export function updateSimulationSession(root: string, simulation: SimulationSession): WorkSessionV1 {
  const current = currentSession()
  if (!sameProjectRoot(current.projectRoot, root)) return cloneSession(current)
  return replaceSession({ ...current, simulation })
}

export function updateConversationSession(root: string, conversation: ConversationSession): WorkSessionV1 {
  const current = currentSession()
  if (!sameProjectRoot(current.projectRoot, root)) return cloneSession(current)
  return replaceSession({ ...current, conversation })
}
