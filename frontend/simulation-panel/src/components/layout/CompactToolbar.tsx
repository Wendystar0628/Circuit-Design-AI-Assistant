import type { ReactNode } from 'react'

interface CompactToolbarProps {
  title: string
  description?: string
  actions?: ReactNode
}

export function CompactToolbar({ title, description, actions }: CompactToolbarProps) {
  return (
    <div className="compact-toolbar">
      <div className="compact-toolbar__meta">
        <div className="compact-toolbar__title">{title}</div>
        {description ? <div className="compact-toolbar__description">{description}</div> : null}
      </div>
      {actions ? <div className="compact-toolbar__actions">{actions}</div> : null}
    </div>
  )
}
