import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { ConversationBridge } from '../bridge'
import type {
  ConversationAttachmentState,
  ConversationMainState,
  PendingWorkspaceEditSummaryState,
} from '../types'

interface ConversationComposerProps {
  state: ConversationMainState
  bridge: ConversationBridge | null
  bridgeConnected: boolean
  registerExternalAttachmentSink: ((sink: ((attachments: ConversationAttachmentState[]) => void) | null) => void) | null
  registerClearDraftAttachmentsHandler: ((handler: (() => void) | null) => void) | null
}

function attachmentKey(attachment: ConversationAttachmentState): string {
  return attachment.reference_id || attachment.path || attachment.name
}

function isInlineAttachment(attachment: ConversationAttachmentState): boolean {
  return attachment.placement === 'inline'
}

function isImageAttachment(attachment: ConversationAttachmentState): boolean {
  return attachment.type === 'image'
}

function mergeAttachments(
  current: ConversationAttachmentState[],
  incoming: ConversationAttachmentState[],
): ConversationAttachmentState[] {
  const seen = new Set(current.map((attachment) => attachmentKey(attachment)))
  const merged = [...current]
  for (const attachment of incoming) {
    const key = attachmentKey(attachment)
    if (!key || seen.has(key)) {
      continue
    }
    merged.push(attachment)
    seen.add(key)
  }
  return merged
}

function createInlineAttachmentChip(attachment: ConversationAttachmentState): HTMLSpanElement {
  const chip = document.createElement('span')
  chip.className = 'composer-inline-chip'
  chip.contentEditable = 'false'
  chip.dataset.attachmentKey = attachmentKey(attachment)
  chip.dataset.referenceId = attachment.reference_id || ''

  const label = document.createElement('span')
  label.className = 'composer-inline-chip__label'
  label.textContent = attachment.name || '未命名文件'

  const remove = document.createElement('span')
  remove.className = 'composer-inline-chip__remove'
  remove.dataset.removeInlineAttachment = attachmentKey(attachment)
  remove.textContent = '×'

  chip.append(label, remove)
  return chip
}

function focusEditorAtEnd(editor: HTMLDivElement): void {
  editor.focus()
  const selection = window.getSelection()
  if (!selection) {
    return
  }
  const range = document.createRange()
  range.selectNodeContents(editor)
  range.collapse(false)
  selection.removeAllRanges()
  selection.addRange(range)
}

function ensureEditorSelection(editor: HTMLDivElement): Range {
  const selection = window.getSelection()
  if (selection && selection.rangeCount > 0) {
    const range = selection.getRangeAt(0)
    if (editor.contains(range.commonAncestorContainer)) {
      return range
    }
  }
  focusEditorAtEnd(editor)
  const fallbackSelection = window.getSelection()
  if (fallbackSelection && fallbackSelection.rangeCount > 0) {
    return fallbackSelection.getRangeAt(0)
  }
  const range = document.createRange()
  range.selectNodeContents(editor)
  range.collapse(false)
  return range
}

function insertInlineAttachmentChip(editor: HTMLDivElement, attachment: ConversationAttachmentState): void {
  const range = ensureEditorSelection(editor)
  range.deleteContents()
  const fragment = document.createDocumentFragment()
  const chip = createInlineAttachmentChip(attachment)
  const trailingCursorHost = document.createTextNode('\u200b')
  fragment.append(chip, trailingCursorHost)
  range.insertNode(fragment)

  const selection = window.getSelection()
  if (selection) {
    const nextRange = document.createRange()
    nextRange.setStartAfter(trailingCursorHost)
    nextRange.collapse(true)
    selection.removeAllRanges()
    selection.addRange(nextRange)
  }
  editor.focus()
}

function insertPlainTextAtCursor(editor: HTMLDivElement, text: string): void {
  if (!text) {
    return
  }
  if (document.queryCommandSupported?.('insertText')) {
    document.execCommand('insertText', false, text)
    return
  }
  const range = ensureEditorSelection(editor)
  range.deleteContents()
  const textNode = document.createTextNode(text)
  range.insertNode(textNode)
  const selection = window.getSelection()
  if (selection) {
    const nextRange = document.createRange()
    nextRange.setStartAfter(textNode)
    nextRange.collapse(true)
    selection.removeAllRanges()
    selection.addRange(nextRange)
  }
}

function insertLineBreakAtCursor(editor: HTMLDivElement): void {
  if (document.queryCommandSupported?.('insertLineBreak')) {
    document.execCommand('insertLineBreak')
    return
  }
  const range = ensureEditorSelection(editor)
  range.deleteContents()
  const fragment = document.createDocumentFragment()
  const lineBreak = document.createElement('br')
  const trailingCursorHost = document.createTextNode('\u200b')
  fragment.append(lineBreak, trailingCursorHost)
  range.insertNode(fragment)
  const selection = window.getSelection()
  if (selection) {
    const nextRange = document.createRange()
    nextRange.setStartAfter(trailingCursorHost)
    nextRange.collapse(true)
    selection.removeAllRanges()
    selection.addRange(nextRange)
  }
}

function serializeNode(
  node: Node,
  attachmentsByKey: Map<string, ConversationAttachmentState>,
  includeInlineMarkers: boolean,
): string {
  if (node.nodeType === Node.TEXT_NODE) {
    return (node.textContent ?? '').replace(/\u200b/g, '')
  }
  if (node.nodeType !== Node.ELEMENT_NODE) {
    return ''
  }

  const element = node as HTMLElement
  const inlineKey = element.dataset.attachmentKey
  if (inlineKey) {
    if (!includeInlineMarkers) {
      return ''
    }
    return attachmentsByKey.get(inlineKey)?.inline_marker || ''
  }

  if (element.tagName === 'BR') {
    return '\n'
  }

  let buffer = ''
  element.childNodes.forEach((childNode) => {
    buffer += serializeNode(childNode, attachmentsByKey, includeInlineMarkers)
  })

  if ((element.tagName === 'DIV' || element.tagName === 'P') && !buffer.endsWith('\n')) {
    buffer += '\n'
  }
  return buffer
}

function findInlineChip(editor: HTMLDivElement, key: string): HTMLElement | null {
  const chips = editor.querySelectorAll<HTMLElement>('[data-attachment-key]')
  for (const chip of Array.from(chips)) {
    if (chip.dataset.attachmentKey === key) {
      return chip
    }
  }
  return null
}

function toDroppedPaths(event: DragEvent): string[] {
  const items = Array.from(event.dataTransfer?.files ?? []) as Array<File & { path?: string }>
  return items
    .map((file) => String(file.path ?? ''))
    .filter((value) => Boolean(value))
}

function formatCompactTokenCount(value: number): string {
  const normalized = Math.max(0, value)
  if (normalized >= 1_000_000) {
    const compact = normalized >= 10_000_000
      ? (normalized / 1_000_000).toFixed(0)
      : (normalized / 1_000_000).toFixed(1)
    return `${compact.replace(/\.0$/, '')}M`
  }
  if (normalized >= 1_000) {
    const compact = normalized >= 100_000
      ? (normalized / 1_000).toFixed(0)
      : (normalized / 1_000).toFixed(1)
    return `${compact.replace(/\.0$/, '')}K`
  }
  return `${Math.round(normalized)}`
}

function primaryActionLabel(mode: string): string {
  switch (mode) {
    case 'stop':
      return '停止'
    case 'stopping':
      return '停止中'
    case 'rollbacking':
      return '撤回中'
    default:
      return '发送'
  }
}

function usageTone(state: string): string {
  if (state === 'critical') {
    return 'critical'
  }
  if (state === 'warning') {
    return 'warning'
  }
  return 'normal'
}

function PendingEditSummary({
  summary,
  bridge,
}: {
  summary: PendingWorkspaceEditSummaryState
  bridge: ConversationBridge | null
}) {
  const [expanded, setExpanded] = useState(false)
  if (!summary.file_count) {
    return null
  }

  return (
    <section className="composer-summary">
      <div className="composer-summary__header">
        <div className="composer-summary__stats">
          <span>{summary.file_count} 个待处理文件</span>
          <span>+{summary.added_lines}</span>
          <span>-{summary.deleted_lines}</span>
        </div>
        <div className="composer-summary__actions">
          <button type="button" className="secondary-button" onClick={() => bridge?.acceptAllPendingEdits?.()}>
            全部接受
          </button>
          <button type="button" className="secondary-button secondary-button--danger" onClick={() => bridge?.rejectAllPendingEdits?.()}>
            全部拒绝
          </button>
          <button type="button" className="ghost-button" onClick={() => setExpanded((current) => !current)}>
            {expanded ? '收起' : '展开'}
          </button>
        </div>
      </div>
      {expanded ? (
        <div className="composer-summary__files">
          {summary.files.map((file) => (
            <button
              key={file.path}
              type="button"
              className="composer-summary__file"
              onClick={() => bridge?.openPendingEditFile?.(file.path)}
            >
              <span className="composer-summary__file-path">{file.relative_path || file.path}</span>
              <span className="composer-summary__file-stats">+{file.added_lines} / -{file.deleted_lines}</span>
            </button>
          ))}
        </div>
      ) : null}
    </section>
  )
}

export function ConversationComposer({
state,
bridge,
bridgeConnected,
registerExternalAttachmentSink,
registerClearDraftAttachmentsHandler,
}: ConversationComposerProps) {
const editorRef = useRef<HTMLDivElement | null>(null)
const draftAttachmentsRef = useRef<ConversationAttachmentState[]>([])
const clearNonceRef = useRef(state.composer.clear_draft_nonce)
const [draftAttachments, setDraftAttachments] = useState<ConversationAttachmentState[]>([])
const [plainTextValue, setPlainTextValue] = useState('')
const bridgeReady = bridgeConnected && Boolean(bridge)

useEffect(() => {
draftAttachmentsRef.current = draftAttachments
}, [draftAttachments])

const refreshComposerState = useCallback(() => {
const editor = editorRef.current
if (!editor) {
setPlainTextValue('')
return
}
const attachmentsByKey = new Map(
draftAttachmentsRef.current.map((attachment) => [attachmentKey(attachment), attachment]),
)
const nextPlainText = serializeNode(editor, attachmentsByKey, false)
setPlainTextValue(nextPlainText)
editor.dataset.empty = nextPlainText.trim() || draftAttachmentsRef.current.length ? 'false' : 'true'
}, [])

const removeAttachment = useCallback(
(key: string) => {
setDraftAttachments((current) => current.filter((attachment) => attachmentKey(attachment) !== key))
const editor = editorRef.current
if (editor) {
const chip = findInlineChip(editor, key)
if (chip) {
const trailingCursorHost = chip.nextSibling
chip.remove()
if (trailingCursorHost?.nodeType === Node.TEXT_NODE && trailingCursorHost.textContent === '\u200b') {
trailingCursorHost.remove()
}
}
}
requestAnimationFrame(() => {
refreshComposerState()
})
},
[refreshComposerState],
)

const appendAttachments = useCallback(
(incoming: ConversationAttachmentState[]) => {
const uniqueIncoming = incoming.filter((attachment) => {
const key = attachmentKey(attachment)
return key && !draftAttachmentsRef.current.some((current) => attachmentKey(current) === key)
})
if (!uniqueIncoming.length) {
return
}
setDraftAttachments((current) => mergeAttachments(current, uniqueIncoming))
const editor = editorRef.current
if (editor) {
const inlineAttachments = uniqueIncoming.filter((attachment) => isInlineAttachment(attachment))
if (inlineAttachments.length) {
editor.focus()
inlineAttachments.forEach((attachment) => {
insertInlineAttachmentChip(editor, attachment)
})
}
}
requestAnimationFrame(() => {
refreshComposerState()
})
},
[refreshComposerState],
)

useEffect(() => {
if (!registerExternalAttachmentSink) {
return
}
registerExternalAttachmentSink(appendAttachments)
return () => {
registerExternalAttachmentSink(null)
}
}, [appendAttachments, registerExternalAttachmentSink])

useEffect(() => {
if (!registerClearDraftAttachmentsHandler) {
return
}
registerClearDraftAttachmentsHandler(() => {
const editor = editorRef.current
if (editor) {
const chips = editor.querySelectorAll('[data-attachment-key]')
chips.forEach((chip) => {
const trailingCursorHost = chip.nextSibling
chip.remove()
if (
trailingCursorHost?.nodeType === Node.TEXT_NODE
&& trailingCursorHost.textContent === '\u200b'
) {
trailingCursorHost.remove()
}
})
}
draftAttachmentsRef.current = []
setDraftAttachments([])
requestAnimationFrame(() => {
refreshComposerState()
})
})
return () => {
registerClearDraftAttachmentsHandler(null)
}
}, [refreshComposerState, registerClearDraftAttachmentsHandler])

useEffect(() => {
if (state.composer.clear_draft_nonce === clearNonceRef.current) {
return
}
clearNonceRef.current = state.composer.clear_draft_nonce
setDraftAttachments([])
draftAttachmentsRef.current = []
const editor = editorRef.current
if (editor) {
editor.innerHTML = ''
editor.dataset.empty = 'true'
}
setPlainTextValue('')
}, [state.composer.clear_draft_nonce])

useEffect(() => {
refreshComposerState()
}, [refreshComposerState])

const attachmentsByKey = useMemo(
() => new Map(draftAttachments.map((attachment) => [attachmentKey(attachment), attachment])),
[draftAttachments],
)

const serializedDraft = useMemo(() => {
const editor = editorRef.current
if (!editor) {
return ''
}
return serializeNode(editor, attachmentsByKey, true)
}, [attachmentsByKey, plainTextValue])

const hasSendPayload = Boolean(serializedDraft.trim() || draftAttachments.length)
const actionMode = state.composer.action_mode
const primaryActionDisabled =
!bridgeReady ||
actionMode === 'stopping' ||
actionMode === 'rollbacking' ||
(actionMode === 'send' && (!state.conversation.can_send || !hasSendPayload))

const galleryAttachments = draftAttachments.filter((attachment) => !isInlineAttachment(attachment))

return (
  <section className="composer-shell">
    <PendingEditSummary summary={state.composer.pending_workspace_edit_summary} bridge={bridge} />

    {galleryAttachments.length ? (
      <div className="composer-gallery">
        {galleryAttachments.map((attachment) => (
          <div key={attachmentKey(attachment)} className="composer-gallery__item">
            <div className="composer-gallery__meta">
              <span className="composer-gallery__name">{attachment.name || '未命名附件'}</span>
              <span className="composer-gallery__path">{attachment.path}</span>
            </div>
            <button type="button" className="ghost-button ghost-button--danger" onClick={() => removeAttachment(attachmentKey(attachment))}>
              移除
            </button>
          </div>
        ))}
      </div>
    ) : null}

    <div
      className="composer-editor-shell"
      onDragOver={(event) => {
        event.preventDefault()
      }}
      onDrop={(event) => {
        event.preventDefault()
        const paths = toDroppedPaths(event.nativeEvent)
        if (paths.length) {
          bridge?.attachFiles?.(paths)
        }
      }}
    >
      <div
        ref={editorRef}
        className="composer-editor"
        contentEditable={bridgeReady}
        suppressContentEditableWarning
        role="textbox"
        aria-label="消息输入框"
        aria-multiline="true"
        data-empty="true"
        data-placeholder="输入消息。Shift+Enter 换行，Enter 发送。"
        onFocus={() => {
          if (editorRef.current && editorRef.current.textContent === '') {
            editorRef.current.dataset.empty = draftAttachments.length ? 'false' : 'true'
          }
        }}
        onInput={() => {
          refreshComposerState()
        }}
        onPaste={(event) => {
          event.preventDefault()
          insertPlainTextAtCursor(editorRef.current as HTMLDivElement, event.clipboardData.getData('text/plain'))
          refreshComposerState()
        }}
        onMouseDown={(event) => {
          const target = event.target as HTMLElement | null
          const removeTarget = target?.closest<HTMLElement>('[data-remove-inline-attachment]')
          if (removeTarget?.dataset.removeInlineAttachment) {
            event.preventDefault()
            removeAttachment(removeTarget.dataset.removeInlineAttachment)
          }
        }}
        onKeyDown={(event) => {
          if (event.key === 'Enter' && !event.shiftKey) {
            event.preventDefault()
            if (!primaryActionDisabled && actionMode === 'send') {
              bridge?.sendMessage?.(serializedDraft, { attachments: draftAttachments })
              return
            }
            if (!primaryActionDisabled && actionMode === 'stop') {
              bridge?.requestStop?.()
            }
            return
          }
          if (event.key === 'Enter' && event.shiftKey) {
            event.preventDefault()
            if (editorRef.current) {
              insertLineBreakAtCursor(editorRef.current)
              refreshComposerState()
            }
            return
          }
          if (event.key === 'Escape' && actionMode === 'stop') {
            event.preventDefault()
            bridge?.requestStop?.()
            return
          }
          if ((event.key === 'Backspace' || event.key === 'Delete') && editorRef.current) {
            const selection = window.getSelection()
            if (!selection || !selection.isCollapsed) {
              return
            }
            const anchorNode = selection.anchorNode
            const anchorOffset = selection.anchorOffset
            const editor = editorRef.current
            let candidate: Node | null = null

            if (anchorNode?.nodeType === Node.TEXT_NODE) {
              const textNode = anchorNode as Text
              if (event.key === 'Backspace' && anchorOffset === 0) {
                candidate = textNode.previousSibling
              } else if (event.key === 'Delete' && anchorOffset === textNode.textContent?.length) {
                candidate = textNode.nextSibling
              }
            } else if (anchorNode?.nodeType === Node.ELEMENT_NODE) {
              const element = anchorNode as Element
              candidate = event.key === 'Backspace'
                ? element.childNodes[anchorOffset - 1] ?? null
                : element.childNodes[anchorOffset] ?? null
            }

            const candidateElement = candidate?.nodeType === Node.TEXT_NODE && candidate.textContent === '\u200b'
              ? (event.key === 'Backspace' ? candidate.previousSibling : candidate.nextSibling)
              : candidate
            const inlineKey = candidateElement instanceof HTMLElement ? candidateElement.dataset.attachmentKey : undefined
            if (inlineKey) {
              event.preventDefault()
              removeAttachment(inlineKey)
              if (editor) {
                editor.focus()
              }
            }
          }
        }}
      />

      <div className="composer-controls">
        <button
          type="button"
          className="icon-button composer-control-button"
          onClick={() => bridge?.requestUploadImage?.()}
          disabled={!bridgeReady}
          title="上传图片"
        >
          图片
        </button>
        <button
          type="button"
          className="icon-button composer-control-button"
          onClick={() => bridge?.requestSelectFile?.()}
          disabled={!bridgeReady}
          title="选择文件"
        >
          文件
        </button>
        <div className={`usage-card composer-usage-pill usage-card--${usageTone(state.composer.compress_button_state)}`}>
          <span className="usage-card__tokens">
            {formatCompactTokenCount(state.composer.usage.current_tokens)} / {formatCompactTokenCount(state.composer.usage.max_tokens)}
          </span>
        </div>
        <button
          type="button"
          className="model-card composer-model-button"
          onClick={() => bridge?.requestModelConfig?.()}
          disabled={!bridgeReady}
        >
          {state.composer.model_display_name || '模型'}
        </button>
        <button
          type="button"
          className={`primary-button primary-button--${actionMode} composer-send-button`}
          disabled={primaryActionDisabled}
          onClick={() => {
            if (actionMode === 'send') {
              bridge?.sendMessage?.(serializedDraft, { attachments: draftAttachments })
              return
            }
            if (actionMode === 'stop') {
              bridge?.requestStop?.()
            }
          }}
        >
          {primaryActionLabel(actionMode)}
        </button>
      </div>
    </div>
  </section>
)
}
