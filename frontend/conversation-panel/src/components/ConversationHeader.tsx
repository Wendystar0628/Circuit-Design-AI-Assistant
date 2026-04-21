import { useEffect, useState, type KeyboardEvent } from 'react'

import type { ConversationBridge } from '../bridge'
import type { ConversationMainState } from '../types'
import { getUiText } from '../uiText'

interface ConversationHeaderProps {
  state: ConversationMainState
  bridge: ConversationBridge | null
  bridgeConnected: boolean
}

export function ConversationHeader({
  state,
  bridge,
  bridgeConnected,
}: ConversationHeaderProps) {
  const untitledSessionLabel = getUiText(state.ui_text, 'conversation.header.untitled_session', 'New Conversation')
  const sessionName = state.session.name || untitledSessionLabel
  const [draftName, setDraftName] = useState(sessionName)
  const [isEditing, setIsEditing] = useState(false)

  useEffect(() => {
    if (!isEditing) {
      setDraftName(sessionName)
    }
  }, [isEditing, sessionName])

  const commitRename = () => {
    const nextName = draftName.trim()
    setIsEditing(false)
    if (!nextName || nextName === sessionName) {
      setDraftName(sessionName)
      return
    }
    bridge?.renameSession?.(nextName)
  }

  const cancelRename = () => {
    setDraftName(sessionName)
    setIsEditing(false)
  }

  const handleNameKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === 'Enter') {
      event.preventDefault()
      commitRename()
      return
    }
    if (event.key === 'Escape') {
      event.preventDefault()
      cancelRename()
    }
  }

  return (
    <div className="conversation-header">
      <div className="conversation-header__identity">
        {isEditing ? (
          <input
            className="conversation-header__title-input"
            value={draftName}
            onChange={(event) => setDraftName(event.target.value)}
            onBlur={commitRename}
            onKeyDown={handleNameKeyDown}
            autoFocus
            disabled={!bridgeConnected}
            title={getUiText(state.ui_text, 'conversation.header.session_name', 'Conversation name')}
            placeholder={getUiText(state.ui_text, 'conversation.header.session_name_placeholder', 'Enter conversation name')}
          />
        ) : (
          <button
            type="button"
            className="conversation-header__title"
            onClick={() => setIsEditing(true)}
            disabled={!bridgeConnected}
            title={getUiText(state.ui_text, 'conversation.header.rename_session', 'Rename conversation')}
          >
            {sessionName}
          </button>
        )}
      </div>
      <div className="conversation-header__actions">
        <button
          type="button"
          className="secondary-button conversation-header__button"
          onClick={() => bridge?.requestNewConversation?.()}
          disabled={!bridgeConnected}
        >
          {getUiText(state.ui_text, 'btn.new_conversation', 'New Conversation')}
        </button>
        <button
          type="button"
          className="secondary-button conversation-header__button"
          onClick={() => bridge?.requestHistory?.()}
          disabled={!bridgeConnected}
        >
          {getUiText(state.ui_text, 'btn.history', 'History')}
        </button>
        <button
          type="button"
          className="secondary-button conversation-header__button"
          onClick={() => bridge?.requestCompressContext?.()}
          disabled={!bridgeConnected}
        >
          {getUiText(state.ui_text, 'menu.conversation.compress', 'Compress Context')}
        </button>
      </div>
    </div>
  )
}
