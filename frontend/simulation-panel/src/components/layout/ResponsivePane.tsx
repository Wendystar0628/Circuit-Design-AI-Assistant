import type { ReactNode } from 'react'

interface ResponsivePaneProps {
  sidebar?: ReactNode
  main: ReactNode
  footer?: ReactNode
}

export function ResponsivePane({ sidebar, main, footer }: ResponsivePaneProps) {
  const paneClassName = sidebar ? 'responsive-pane responsive-pane--with-sidebar' : 'responsive-pane'

  return (
    <div className="responsive-pane-shell">
      <div className={paneClassName}>
        {sidebar ? <aside className="responsive-pane__sidebar">{sidebar}</aside> : null}
        <section className="responsive-pane__main">{main}</section>
      </div>
      {footer ? <div className="responsive-pane__footer">{footer}</div> : null}
    </div>
  )
}
