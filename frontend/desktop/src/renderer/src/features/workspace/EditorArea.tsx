import Editor, { type OnMount } from '@monaco-editor/react'
import { useEffect, useRef, useState } from 'react'
import { errorMessage, workspaceApi } from './apiPort'
import { monaco } from './monacoSetup'
import { SafeMarkdown } from './SafeMarkdown'
import type { WorkspaceDocument } from './types'

interface EditorAreaProps {
  projectId: string | null
  documents: WorkspaceDocument[]
  activeDocumentId: string | null
  savingDocumentIds: ReadonlySet<string>
  onActivate: (documentId: string) => void
  onClose: (documentId: string) => void
  onContentChange: (documentId: string, content: string) => void
  onSave: (documentId: string) => void
  onCursorChange: (documentId: string, line: number, column: number) => void
  onMarkdownPreviewChange: (documentId: string, preview: boolean) => void
  onOpenProject: () => void
  openingProject: boolean
  simulationRunControl: {
    canRun: boolean
    busy: boolean
    title: string
  }
  onRunSimulation: () => void
}

function AssetPreview({ projectId, document }: { projectId: string; document: WorkspaceDocument }) {
  const [url, setUrl] = useState('')
  const [error, setError] = useState('')

  useEffect(() => {
    let disposed = false
    let objectUrl = ''
    setUrl('')
    setError('')
    workspaceApi.asset(projectId, document.path)
      .then((blob) => {
        if (disposed) return
        const mimeType = (blob.type || document.mimeType).toLowerCase()
        if (
          document.viewKind === 'image'
          && !['image/png', 'image/jpeg', 'image/gif', 'image/webp', 'image/bmp'].includes(mimeType)
        ) {
          setError('Only raster image previews are supported.')
          return
        }
        if (document.viewKind === 'pdf' && mimeType !== 'application/pdf') {
          setError('The preview response is not a PDF document.')
          return
        }
        objectUrl = URL.createObjectURL(blob)
        setUrl(objectUrl)
      })
      .catch((reason) => {
        if (!disposed) setError(errorMessage(reason))
      })
    return () => {
      disposed = true
      if (objectUrl) URL.revokeObjectURL(objectUrl)
    }
  }, [document.documentId, document.path, document.revision, projectId])

  if (error) return <div className="workspace-document-state workspace-document-state--error">{error}</div>
  if (!url) return <div className="workspace-document-state">Loading preview…</div>
  if (document.viewKind === 'image') {
    return <div className="workspace-image-preview"><img src={url} alt={document.name} /></div>
  }
  return <object className="workspace-pdf-preview" data={url} type="application/pdf" aria-label={document.name} />
}

function languageFor(document: WorkspaceDocument): string {
  const suffix = document.name.split('.').pop()?.toLowerCase() ?? ''
  const languages: Record<string, string> = {
    cir: 'spice',
    sp: 'spice',
    spice: 'spice',
    net: 'spice',
    py: 'python',
    js: 'javascript',
    jsx: 'javascript',
    ts: 'typescript',
    tsx: 'typescript',
    json: 'json',
    html: 'html',
    htm: 'html',
    css: 'css',
    scss: 'scss',
    less: 'less',
    md: 'markdown',
    markdown: 'markdown',
    yml: 'yaml',
    yaml: 'yaml',
    xml: 'xml',
    sh: 'shell',
    ps1: 'powershell',
  }
  return languages[suffix] || 'plaintext'
}

export function EditorArea({
  projectId,
  documents,
  activeDocumentId,
  savingDocumentIds,
  onActivate,
  onClose,
  onContentChange,
  onSave,
  onCursorChange,
  onMarkdownPreviewChange,
  onOpenProject,
  openingProject,
  simulationRunControl,
  onRunSimulation,
}: EditorAreaProps) {
  const activeDocument = documents.find((document) => document.documentId === activeDocumentId) ?? null
  const tabsRef = useRef<HTMLDivElement | null>(null)
  const tabRefs = useRef(new Map<string, HTMLDivElement>())
  const editorRef = useRef<Parameters<OnMount>[0] | null>(null)
  const activeDocumentRef = useRef(activeDocument)
  const onSaveRef = useRef(onSave)
  const onCursorChangeRef = useRef(onCursorChange)

  activeDocumentRef.current = activeDocument
  onSaveRef.current = onSave
  onCursorChangeRef.current = onCursorChange

  useEffect(() => {
    const tabs = tabsRef.current
    const tab = activeDocumentId ? tabRefs.current.get(activeDocumentId) : null
    if (!tabs || !tab) return
    if (tab.offsetLeft < tabs.scrollLeft) tabs.scrollLeft = tab.offsetLeft
    else if (tab.offsetLeft + tab.offsetWidth > tabs.scrollLeft + tabs.clientWidth) {
      tabs.scrollLeft = tab.offsetLeft + tab.offsetWidth - tabs.clientWidth
    }
  }, [activeDocumentId, documents.length])

  const restoreEditorCursor = () => {
    const editor = editorRef.current
    const document = activeDocumentRef.current
    const model = editor?.getModel()
    if (!editor || !document || !model) return
    const lineNumber = Math.max(1, Math.min(document.cursorLine, model.getLineCount()))
    const column = Math.max(1, Math.min(document.cursorColumn, model.getLineMaxColumn(lineNumber)))
    const current = editor.getPosition()
    if (current?.lineNumber !== lineNumber || current.column !== column) {
      editor.setPosition({ lineNumber, column })
    }
    editor.revealPositionInCenterIfOutsideViewport({ lineNumber, column })
  }

  useEffect(() => {
    if (
      !activeDocument
      || (activeDocument.viewKind === 'markdown' && activeDocument.markdownPreview)
    ) return
    restoreEditorCursor()
  }, [
    activeDocument?.documentId,
    activeDocument?.cursorColumn,
    activeDocument?.cursorLine,
    activeDocument?.markdownPreview,
  ])

  const handleEditorMount: OnMount = (editor) => {
    editorRef.current = editor
    editor.onDidChangeCursorPosition((event) => {
      const document = activeDocumentRef.current
      if (document) {
        onCursorChangeRef.current(
          document.documentId,
          event.position.lineNumber,
          event.position.column,
        )
      }
    })
    editor.onDidChangeModel(() => window.queueMicrotask(restoreEditorCursor))
    editor.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.KeyS, () => {
      const document = activeDocumentRef.current
      if (document && !document.readonly && document.dirty) {
        onSaveRef.current(document.documentId)
      }
    })
    restoreEditorCursor()
    editor.focus()
  }

  const renderDocument = () => {
    if (!activeDocument || !projectId) {
      if (!projectId) {
        return (
          <div className="workspace-document-state workspace-document-state--empty">
            <span>Open a workspace to get started.</span>
            <button
              type="button"
              className="workspace-button workspace-button--primary workspace-open-project-button"
              disabled={openingProject}
              onClick={onOpenProject}
            >
              {openingProject ? 'Opening…' : 'Open project'}
            </button>
          </div>
        )
      }
      return (
        <div className="workspace-document-state workspace-document-state--empty">
          <span>Select a file to view.</span>
        </div>
      )
    }
    if (activeDocument.viewKind === 'image' || activeDocument.viewKind === 'pdf') {
      return <AssetPreview projectId={projectId} document={activeDocument} />
    }
    if (activeDocument.viewKind === 'markdown' && activeDocument.markdownPreview) {
      return <SafeMarkdown content={activeDocument.content} />
    }
    return (
      <Editor
        className="workspace-monaco-editor"
        path={`workspace://${projectId}/${activeDocument.documentId}`}
        language={languageFor(activeDocument)}
        value={activeDocument.content}
        theme="vs"
        loading={<div className="workspace-document-state">Loading editor…</div>}
        options={{
          automaticLayout: true,
          readOnly: activeDocument.readonly,
          minimap: { enabled: false },
          fontFamily: '"Cascadia Code", Consolas, monospace',
          fontSize: 13,
          lineHeight: 20,
          scrollBeyondLastLine: false,
          smoothScrolling: true,
          renderWhitespace: 'selection',
          stickyScroll: { enabled: false },
          padding: { top: 8, bottom: 8 },
        }}
        onMount={handleEditorMount}
        onChange={(value) => onContentChange(activeDocument.documentId, value ?? '')}
      />
    )
  }

  return (
    <main className="workspace-editor-area" data-layout-surface="editor">
      <header className="workspace-tabs">
        <div className="workspace-tabs__scroll" ref={tabsRef} role="tablist">
          {!documents.length ? <div className="workspace-tabs__empty">No open files</div> : null}
          {documents.map((document) => {
            const active = document.documentId === activeDocumentId
            return (
              <div
                key={document.documentId}
                ref={(element) => {
                  if (element) tabRefs.current.set(document.documentId, element)
                  else tabRefs.current.delete(document.documentId)
                }}
                className={`workspace-tab${active ? ' workspace-tab--active' : ''}`}
                role="tab"
                aria-selected={active}
                title={document.missing ? `${document.path} — deleted on disk` : document.path}
              >
                <button type="button" className="workspace-tab__activate" onClick={() => onActivate(document.documentId)}>
                  <span>{document.name}{document.missing ? ' (deleted)' : ''}</span>
                  {document.dirty ? <span className="workspace-dirty-dot" aria-label="Modified" /> : null}
                </button>
                <button type="button" className="workspace-tab__close" aria-label={`Close ${document.name}`} onClick={() => onClose(document.documentId)}>×</button>
              </div>
            )
          })}
        </div>
        <div className="workspace-tabs__actions">
          {activeDocument?.viewKind === 'markdown' ? (
            <div className="workspace-segmented" aria-label="Markdown view">
              <button
                type="button"
                className={!activeDocument.markdownPreview ? 'active' : ''}
                onClick={() => onMarkdownPreviewChange(activeDocument.documentId, false)}
              >
                Edit
              </button>
              <button
                type="button"
                className={activeDocument.markdownPreview ? 'active' : ''}
                onClick={() => onMarkdownPreviewChange(activeDocument.documentId, true)}
              >
                Preview
              </button>
            </div>
          ) : null}
          {activeDocument && !activeDocument.readonly && activeDocument.viewKind !== 'image' && activeDocument.viewKind !== 'pdf' ? (
            <button
              type="button"
              className="workspace-button workspace-button--primary workspace-save-button"
              disabled={!activeDocument.dirty || savingDocumentIds.has(activeDocument.documentId)}
              onClick={() => onSave(activeDocument.documentId)}
            >
              {savingDocumentIds.has(activeDocument.documentId) ? 'Saving…' : 'Save'}
            </button>
          ) : null}
          <button
            type="button"
            className="workspace-run-button"
            title={simulationRunControl.title}
            aria-label={simulationRunControl.title}
            disabled={!simulationRunControl.canRun}
            onClick={onRunSimulation}
          >
            <span aria-hidden="true">▶</span>
            <span className="workspace-run-button__label">
              {simulationRunControl.busy ? 'Starting…' : 'Run'}
            </span>
          </button>
        </div>
      </header>
      <section className="workspace-document-surface" role="tabpanel">
        {renderDocument()}
      </section>
    </main>
  )
}
