import type { ConversationBridge } from '../bridge'
import { getUiText, type UiTextMap } from '../uiText'

interface RightPanelTabsProps {
  activeSurface: string
  bridge: ConversationBridge | null
  uiText?: UiTextMap
}

function ChatIcon() {
  return (
    <svg viewBox="0 0 20 20" aria-hidden="true" className="right-panel-tab__icon-svg">
      <path
        d="M4.5 5.5h11a1 1 0 0 1 1 1v6.25a1 1 0 0 1-1 1H9l-3.5 3v-3H4.5a1 1 0 0 1-1-1V6.5a1 1 0 0 1 1-1Z"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.7"
        strokeLinejoin="round"
      />
    </svg>
  )
}

function LibraryIcon() {
  return (
    <svg viewBox="0 0 20 20" aria-hidden="true" className="right-panel-tab__icon-svg">
      <path
        d="M5 4.5h7.5a1.5 1.5 0 0 1 1.5 1.5v8.5a1 1 0 0 1-1.53.85L9 13.25l-3.47 2.1A1 1 0 0 1 4 14.5V6A1.5 1.5 0 0 1 5.5 4.5Z"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinejoin="round"
      />
      <path d="M14.5 7.5h1A1.5 1.5 0 0 1 17 9v5.5" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
    </svg>
  )
}

export function RightPanelTabs({ activeSurface, bridge, uiText }: RightPanelTabsProps) {
  const tabs = [
    {
      id: 'conversation',
      label: getUiText(uiText, 'panel.conversation', 'Conversation'),
      icon: <ChatIcon />,
    },
    {
      id: 'rag',
      label: getUiText(uiText, 'panel.rag', 'Index Library'),
      icon: <LibraryIcon />,
    },
  ]

  return (
    <div className="right-panel-tabs" aria-label={getUiText(uiText, 'conversation.right_panel_navigation', 'Right panel navigation')}>
      {tabs.map((tab) => {
        const isActive = activeSurface === tab.id
        return (
          <button
            key={tab.id}
            type="button"
            aria-current={isActive ? 'page' : undefined}
            className={`right-panel-tab${isActive ? ' right-panel-tab--active' : ''}`}
            onClick={() => bridge?.activateSurface?.(tab.id)}
          >
            <span className="right-panel-tab__icon">{tab.icon}</span>
            <span className="right-panel-tab__label">{tab.label}</span>
          </button>
        )
      })}
    </div>
  )
}
