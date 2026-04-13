import { ResizableStack } from '../layout/ResizableStack'

export interface SignalSelectionSidebarSelectableItem {
  id: string
  label: string
  meta?: string
  checked: boolean
  onCheckedChange: (checked: boolean) => void
}

export interface SignalSelectionSidebarVisibleItem {
  id: string
  label: string
  color: string
  lineStyle?: 'solid' | 'dash'
  meta?: string
}

interface SignalSelectionSidebarProps {
  selectableTitle: string
  selectableDescription?: string
  selectableItems: SignalSelectionSidebarSelectableItem[]
  emptySelectableMessage: string
  visibleTitle: string
  visibleDescription?: string
  visibleItems: SignalSelectionSidebarVisibleItem[]
  emptyVisibleMessage: string
  defaultPrimaryRatio?: number
}

export function SignalSelectionSidebar({
  selectableTitle,
  selectableDescription,
  selectableItems,
  emptySelectableMessage,
  visibleTitle,
  visibleDescription,
  visibleItems,
  emptyVisibleMessage,
  defaultPrimaryRatio = 0.7,
}: SignalSelectionSidebarProps) {
  return (
    <div className="content-card signal-sidebar">
      <ResizableStack
        defaultPrimaryRatio={defaultPrimaryRatio}
        minPrimarySize={144}
        minSecondarySize={104}
        primary={
          <section className="signal-sidebar__panel">
            <div className="signal-sidebar__panel-header">
              <div className="signal-sidebar__panel-title">{selectableTitle}</div>
              {selectableDescription ? <div className="signal-sidebar__panel-description">{selectableDescription}</div> : null}
            </div>
            <div className="signal-sidebar__panel-body">
              <div className="signal-list signal-sidebar__selection-list">
                {selectableItems.length ? selectableItems.map((item) => (
                  <label key={item.id} className="signal-item signal-item--checkbox">
                    <div className="signal-item__stack">
                      <span className="signal-item__name">{item.label}</span>
                      {item.meta ? <span className="signal-item__meta">{item.meta}</span> : null}
                    </div>
                    <input
                      type="checkbox"
                      checked={item.checked}
                      onChange={(event) => item.onCheckedChange(event.target.checked)}
                    />
                  </label>
                )) : <div className="signal-item"><span className="muted-text">{emptySelectableMessage}</span></div>}
              </div>
            </div>
          </section>
        }
        secondary={
          <section className="signal-sidebar__panel">
            <div className="signal-sidebar__panel-header">
              <div className="signal-sidebar__panel-title">{visibleTitle}</div>
              {visibleDescription ? <div className="signal-sidebar__panel-description">{visibleDescription}</div> : null}
            </div>
            <div className="signal-sidebar__panel-body">
              <div className="signal-sidebar__visible-list">
                {visibleItems.length ? visibleItems.map((item) => (
                  <div key={item.id} className="signal-sidebar__visible-item">
                    <svg className="signal-sidebar__visible-swatch" viewBox="0 0 24 12" aria-hidden="true" focusable="false">
                      <line
                        x1="1"
                        x2="23"
                        y1="6"
                        y2="6"
                        stroke={item.color}
                        strokeWidth="2"
                        strokeLinecap="round"
                        strokeDasharray={item.lineStyle === 'dash' ? '6 4' : undefined}
                        className="signal-sidebar__visible-line"
                      />
                    </svg>
                    <div className="signal-sidebar__visible-copy">
                      <span className="signal-sidebar__visible-name">{item.label}</span>
                      {item.meta ? <span className="signal-sidebar__visible-meta">{item.meta}</span> : null}
                    </div>
                  </div>
                )) : <div className="muted-text">{emptyVisibleMessage}</div>}
              </div>
            </div>
          </section>
        }
      />
    </div>
  )
}
