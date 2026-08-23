import { useEffect, useRef, useState, type CSSProperties } from 'react'
import type { ProjectSummary, WorkspaceTreeEntry } from './types'

export type TreeEntryAction = 'create-file' | 'create-directory' | 'rename' | 'delete'

interface WorkspaceTreeProps {
  project: ProjectSummary | null
  entries: WorkspaceTreeEntry[]
  loading: boolean
  busy: boolean
  collapsed: boolean
  onToggleCollapsed: () => void
  onOpenProject: () => void
  onCloseProject: () => void
  onRefresh: () => void
  onToggleDirectory: (entry: WorkspaceTreeEntry) => void
  onOpenFile: (entry: WorkspaceTreeEntry) => void
  onEntryAction: (action: TreeEntryAction, entry: WorkspaceTreeEntry | null) => void
}

interface MenuState {
  entry: WorkspaceTreeEntry
  x: number
  y: number
}

interface EntryProps {
  entry: WorkspaceTreeEntry
  depth: number
  onToggleDirectory: (entry: WorkspaceTreeEntry) => void
  onOpenFile: (entry: WorkspaceTreeEntry) => void
  onContextMenu: (entry: WorkspaceTreeEntry, x: number, y: number) => void
}

function TreeEntry({
  entry,
  depth,
  onToggleDirectory,
  onOpenFile,
  onContextMenu,
}: EntryProps) {
  const activate = () => {
    if (entry.kind === 'directory') onToggleDirectory(entry)
    else onOpenFile(entry)
  }
  return (
    <div className="workspace-tree__node">
      <button
        type="button"
        role="treeitem"
        aria-level={depth + 1}
        aria-expanded={entry.kind === 'directory' ? entry.expanded : undefined}
        className="workspace-tree__row"
        style={{ '--workspace-depth': depth } as CSSProperties}
        title={entry.path}
        onClick={activate}
        onContextMenu={(event) => {
          event.preventDefault()
          onContextMenu(entry, event.clientX, event.clientY)
        }}
        onKeyDown={(event) => {
          if (event.shiftKey && event.key === 'F10') {
            event.preventDefault()
            const bounds = event.currentTarget.getBoundingClientRect()
            onContextMenu(entry, bounds.left + 24, bounds.bottom)
          }
        }}
      >
        <span className="workspace-tree__disclosure" aria-hidden="true">
          {entry.kind === 'directory' ? (entry.loading ? '…' : entry.expanded ? '▾' : '▸') : ''}
        </span>
        <span className={`workspace-tree__glyph workspace-tree__glyph--${entry.kind}`} aria-hidden="true" />
        <span className="workspace-tree__name">{entry.name}</span>
        {entry.isDirty ? <span className="workspace-dirty-dot" aria-label="Modified" /> : null}
      </button>
      {entry.kind === 'directory' && entry.expanded && entry.children ? (
        <div role="group">
          {entry.children.map((child) => (
            <TreeEntry
              key={child.path}
              entry={child}
              depth={depth + 1}
              onToggleDirectory={onToggleDirectory}
              onOpenFile={onOpenFile}
              onContextMenu={onContextMenu}
            />
          ))}
          {!entry.children.length ? <div className="workspace-tree__empty-folder">Empty</div> : null}
        </div>
      ) : null}
    </div>
  )
}

export function WorkspaceTree({
  project,
  entries,
  loading,
  busy,
  collapsed,
  onToggleCollapsed,
  onOpenProject,
  onCloseProject,
  onRefresh,
  onToggleDirectory,
  onOpenFile,
  onEntryAction,
}: WorkspaceTreeProps) {
  const [menu, setMenu] = useState<MenuState | null>(null)
  const menuRef = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    if (!menu) return undefined
    const close = () => setMenu(null)
    const keydown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') close()
    }
    const pointerdown = (event: PointerEvent) => {
      if (!menuRef.current?.contains(event.target as Node)) close()
    }
    document.addEventListener('keydown', keydown)
    document.addEventListener('pointerdown', pointerdown)
    window.addEventListener('blur', close)
    return () => {
      document.removeEventListener('keydown', keydown)
      document.removeEventListener('pointerdown', pointerdown)
      window.removeEventListener('blur', close)
    }
  }, [menu])

  useEffect(() => {
    if (!menu || !menuRef.current) return
    const element = menuRef.current
    element.style.left = `${Math.max(8, Math.min(menu.x, window.innerWidth - element.offsetWidth - 8))}px`
    element.style.top = `${Math.max(8, Math.min(menu.y, window.innerHeight - element.offsetHeight - 8))}px`
    element.querySelector<HTMLButtonElement>('button')?.focus()
  }, [menu])

  if (collapsed) {
    return (
      <aside className="workspace-explorer workspace-explorer--collapsed">
        <button type="button" className="workspace-icon-button" aria-label="Expand explorer" onClick={onToggleCollapsed}>›</button>
      </aside>
    )
  }

  return (
    <aside className="workspace-explorer">
      <header className="workspace-explorer__header">
        <strong title={project?.root}>{project?.name || 'Workspace'}</strong>
        <div className="workspace-explorer__header-actions">
          <button type="button" className="workspace-icon-button" title="Refresh" aria-label="Refresh" disabled={!project || loading} onClick={onRefresh}>↻</button>
          <button type="button" className="workspace-icon-button" title="Collapse explorer" aria-label="Collapse explorer" onClick={onToggleCollapsed}>‹</button>
        </div>
      </header>
      <div className="workspace-explorer__project-actions">
        <button type="button" className="workspace-button workspace-button--primary" disabled={busy} onClick={onOpenProject}>
          {project ? 'Open another' : 'Open project'}
        </button>
        {project ? <button type="button" className="workspace-button" disabled={busy} onClick={onCloseProject}>Close</button> : null}
      </div>
      {project ? (
        <div className="workspace-explorer__entry-actions">
          <button type="button" onClick={() => onEntryAction('create-file', null)}>New file</button>
          <button type="button" onClick={() => onEntryAction('create-directory', null)}>New folder</button>
        </div>
      ) : null}
      <div className="workspace-tree" role="tree" aria-label="Project files">
        {loading && !entries.length ? <div className="workspace-tree__message">Loading…</div> : null}
        {!loading && project && !entries.length ? <div className="workspace-tree__message">This project is empty</div> : null}
        {!project ? <div className="workspace-tree__message">Open a project folder to begin.</div> : null}
        {entries.map((entry) => (
          <TreeEntry
            key={entry.path}
            entry={entry}
            depth={0}
            onToggleDirectory={onToggleDirectory}
            onOpenFile={onOpenFile}
            onContextMenu={(target, x, y) => setMenu({ entry: target, x, y })}
          />
        ))}
      </div>
      {menu ? (
        <div ref={menuRef} className="workspace-context-menu" role="menu" aria-label={menu.entry.name}>
          {menu.entry.kind === 'directory' ? (
            <>
              <button type="button" role="menuitem" onClick={() => { onEntryAction('create-file', menu.entry); setMenu(null) }}>New file</button>
              <button type="button" role="menuitem" onClick={() => { onEntryAction('create-directory', menu.entry); setMenu(null) }}>New folder</button>
              <div className="workspace-context-menu__separator" />
            </>
          ) : null}
          <button type="button" role="menuitem" onClick={() => { onEntryAction('rename', menu.entry); setMenu(null) }}>Rename</button>
          <button type="button" role="menuitem" className="workspace-context-menu__danger" onClick={() => { onEntryAction('delete', menu.entry); setMenu(null) }}>Delete</button>
        </div>
      ) : null}
    </aside>
  )
}
