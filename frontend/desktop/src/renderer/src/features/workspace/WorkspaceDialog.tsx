import { useEffect, useRef, useState } from 'react'
import type { WorkspaceDocument, WorkspaceTreeEntry } from './types'

export type WorkspaceDialogState =
  | {
      kind: 'create-file' | 'create-directory' | 'rename' | 'delete'
      entry: WorkspaceTreeEntry | null
    }
  | {
      kind: 'dirty-document'
      documentId: string
    }
  | {
      kind: 'dirty-project'
    }

interface WorkspaceDialogProps {
  dialog: WorkspaceDialogState
  documents: WorkspaceDocument[]
  busy: boolean
  onCancel: () => void
  onEntryConfirm: (name: string) => void
  onDirtyAction: (action: 'save' | 'discard') => void
}

export function WorkspaceDialog({
  dialog,
  documents,
  busy,
  onCancel,
  onEntryConfirm,
  onDirtyAction,
}: WorkspaceDialogProps) {
  const rootRef = useRef<HTMLDivElement | null>(null)
  const inputRef = useRef<HTMLInputElement | null>(null)
  const [name, setName] = useState(dialog.kind === 'rename' ? dialog.entry?.name ?? '' : '')

  useEffect(() => {
    const previous = document.activeElement instanceof HTMLElement ? document.activeElement : null
    const timer = window.setTimeout(() => {
      if (inputRef.current) {
        inputRef.current.focus()
        inputRef.current.select()
      } else {
        rootRef.current?.querySelector<HTMLButtonElement>('button')?.focus()
      }
    }, 0)
    const keydown = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && !busy) {
        event.preventDefault()
        onCancel()
      }
      if (event.key !== 'Tab' || !rootRef.current) return
      const focusable = Array.from(rootRef.current.querySelectorAll<HTMLElement>('button:not(:disabled), input:not(:disabled)'))
      if (!focusable.length) return
      const first = focusable[0]
      const last = focusable[focusable.length - 1]
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault()
        last.focus()
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault()
        first.focus()
      }
    }
    document.addEventListener('keydown', keydown)
    return () => {
      window.clearTimeout(timer)
      document.removeEventListener('keydown', keydown)
      previous?.focus()
    }
  }, [busy, onCancel])

  const dirtyDocuments = dialog.kind === 'dirty-document'
    ? documents.filter((document) => document.documentId === dialog.documentId && document.dirty)
    : dialog.kind === 'dirty-project'
      ? documents.filter((document) => document.dirty)
      : []
  const hasUnsavableDirtyDocument = dirtyDocuments.some(
    (document) => document.missing || document.readonly,
  )

  let title = ''
  let message = ''
  if (dialog.kind === 'create-file') {
    title = 'Create file'
    message = `Create a file in ${dialog.entry?.path || 'the project root'}.`
  } else if (dialog.kind === 'create-directory') {
    title = 'Create folder'
    message = `Create a folder in ${dialog.entry?.path || 'the project root'}.`
  } else if (dialog.kind === 'rename') {
    title = 'Rename entry'
    message = `Rename ${dialog.entry?.path || ''}.`
  } else if (dialog.kind === 'delete') {
    title = 'Delete entry'
    message = `Delete ${dialog.entry?.path || ''}? This cannot be undone.`
  } else {
    title = 'Unsaved changes'
    if (hasUnsavableDirtyDocument) {
      message = 'A changed document was deleted or became read-only. Copy its contents before discarding it.'
    } else {
      message = dialog.kind === 'dirty-project'
        ? 'Save all changed documents before closing the project?'
        : 'Save this document before closing it?'
    }
  }

  const needsName = dialog.kind === 'create-file' || dialog.kind === 'create-directory' || dialog.kind === 'rename'
  const isDirtyDialog = dialog.kind === 'dirty-document' || dialog.kind === 'dirty-project'

  return (
    <div className="workspace-dialog-backdrop">
      <section ref={rootRef} className="workspace-dialog" role="dialog" aria-modal="true" aria-labelledby="workspace-dialog-title">
        <header><h2 id="workspace-dialog-title">{title}</h2></header>
        <div className="workspace-dialog__body">
          <p>{message}</p>
          {needsName ? (
            <label>
              <span>Name</span>
              <input
                ref={inputRef}
                value={name}
                disabled={busy}
                onChange={(event) => setName(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === 'Enter' && name.trim() && !busy) {
                    event.preventDefault()
                    onEntryConfirm(name.trim())
                  }
                }}
              />
            </label>
          ) : null}
          {dirtyDocuments.length ? (
            <div className="workspace-dialog__documents">
              {dirtyDocuments.map((document) => (
                <div key={document.documentId} title={document.path}>
                  <span className="workspace-dirty-dot" aria-hidden="true" />
                  <span>{document.name}</span>
                </div>
              ))}
            </div>
          ) : null}
        </div>
        <footer>
          <button type="button" className="workspace-button" disabled={busy} onClick={onCancel}>Cancel</button>
          {isDirtyDialog ? (
            <>
              <button type="button" className="workspace-button workspace-button--danger" disabled={busy} onClick={() => onDirtyAction('discard')}>Discard</button>
              {!hasUnsavableDirtyDocument ? (
                <button type="button" className="workspace-button workspace-button--primary" disabled={busy} onClick={() => onDirtyAction('save')}>{busy ? 'Saving…' : 'Save'}</button>
              ) : null}
            </>
          ) : (
            <button
              type="button"
              className={dialog.kind === 'delete' ? 'workspace-button workspace-button--danger' : 'workspace-button workspace-button--primary'}
              disabled={busy || (needsName && !name.trim())}
              onClick={() => onEntryConfirm(name.trim())}
            >
              {busy ? 'Working…' : dialog.kind === 'delete' ? 'Delete' : dialog.kind === 'rename' ? 'Rename' : 'Create'}
            </button>
          )}
        </footer>
      </section>
    </div>
  )
}
