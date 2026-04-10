export interface ConversationBridge {
  markReady?: () => void
  sendMessage?: (text: string, composerState: Record<string, unknown>) => void
  requestStop?: () => void
  requestNewConversation?: () => void
  requestHistory?: () => void
  closeHistory?: () => void
  selectHistorySession?: (sessionId: string) => void
  openHistorySession?: (sessionId: string) => void
  requestExportHistorySession?: (sessionId: string, exportFormat: string) => void
  requestDeleteHistorySession?: (sessionId: string) => void
  requestClearDisplay?: () => void
  resolveConfirmDialog?: (accepted: boolean) => void
  closeNoticeDialog?: () => void
  requestCompressContext?: () => void
  renameSession?: (name: string) => void
  selectSuggestion?: (suggestionId: string) => void
  requestRollback?: (messageId: string) => void
  closeRollbackPreview?: () => void
  confirmRollback?: () => void
  acceptAllPendingEdits?: () => void
  rejectAllPendingEdits?: () => void
  openPendingEditFile?: (filePath: string) => void
  openFile?: (filePath: string) => void
  openLink?: (url: string) => void
  previewImage?: (imagePath: string) => void
  requestUploadImage?: () => void
  requestSelectFile?: () => void
  requestModelConfig?: () => void
  attachFiles?: (paths: string[]) => void
}

export interface ConversationAppApi {
  setState: (nextState: unknown) => void
  appendDraftAttachments?: (nextAttachments: unknown) => void
  clearDraftAttachments?: () => void
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
    conversationApp?: ConversationAppApi
    renderMathInElement?: (element: Element, options?: Record<string, unknown>) => void
  }
}

let activeBridge: ConversationBridge | null = null

export function setConversationBridge(nextBridge: ConversationBridge | null): void {
  activeBridge = nextBridge
}

export function getConversationBridge(): ConversationBridge | null {
  return activeBridge
}
