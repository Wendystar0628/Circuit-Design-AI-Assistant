export interface ModelConfigBridge {
  markReady?: () => void
  updateDraft?: (section: string, field: string, value: unknown) => void
  selectTab?: (tabId: string) => void
  requestTestConnection?: () => void
  requestSave?: () => void
  requestCancel?: () => void
  resolveConfirmDialog?: (accepted: boolean) => void
  closeNoticeDialog?: () => void
}

export interface ModelConfigAppApi {
  setState: (nextState: unknown) => void
}

declare global {
  interface Window {
    QWebChannel?: new (
      transport: unknown,
      callback: (channel: { objects: Record<string, unknown> }) => void,
    ) => unknown
    qt?: {
      webChannelTransport?: unknown
    }
    modelConfigApp?: ModelConfigAppApi
  }
}

let activeBridge: ModelConfigBridge | null = null

export function setModelConfigBridge(nextBridge: ModelConfigBridge | null): void {
  activeBridge = nextBridge
}

export function getModelConfigBridge(): ModelConfigBridge | null {
  return activeBridge
}
