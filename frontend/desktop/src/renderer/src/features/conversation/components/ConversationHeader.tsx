import { useEffect, useRef, useState, type KeyboardEvent } from 'react'

import type { ConversationActions } from '../actions'
import type { ConversationMainState } from '../types'
import { getUiText } from '../uiText'

interface ConversationHeaderProps {
  state: ConversationMainState
  actions: ConversationActions | null
  available: boolean
}

export function ConversationHeader({
  state,
  actions,
  available,
}: ConversationHeaderProps) {
  const untitledSessionLabel = getUiText(state.ui_text, 'conversation.header.untitled_session', 'New Conversation')
  const sessionName = state.session.name || untitledSessionLabel
  const [draftName, setDraftName] = useState(sessionName)
  const [isEditing, setIsEditing] = useState(false)
  const [editContextId, setEditContextId] = useState('')
  const renderedContextIdRef = useRef(state.context_id)
  const sessionActionsDisabled = !available || !actions || !state.context_id || state.view_flags.is_busy

  useEffect(() => {
    if (!isEditing) {
      setDraftName(sessionName)
    }
  }, [isEditing, sessionName])

  useEffect(() => {
    if (renderedContextIdRef.current === state.context_id) {
      return
    }
    renderedContextIdRef.current = state.context_id
    setDraftName(sessionName)
    setEditContextId('')
    setIsEditing(false)
  }, [sessionName, state.context_id])

  const beginRename = () => {
    if (sessionActionsDisabled) {
      return
    }
    setDraftName(sessionName)
    setEditContextId(state.context_id)
    setIsEditing(true)
  }

  const commitRename = () => {
    const nextName = draftName.trim()
    setIsEditing(false)
    if (
      sessionActionsDisabled
      || !actions
      || !editContextId
      || editContextId !== state.context_id
    ) {
      setDraftName(sessionName)
      setEditContextId('')
      return
    }
    if (!nextName || nextName === sessionName) {
      setDraftName(sessionName)
      setEditContextId('')
      return
    }
    actions.renameSession(editContextId, nextName)
    setEditContextId('')
  }

  const cancelRename = () => {
    setDraftName(sessionName)
    setEditContextId('')
    setIsEditing(false)
  }

  const handleNameKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.nativeEvent.isComposing || event.nativeEvent.keyCode === 229) {
      return
    }
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
            disabled={sessionActionsDisabled}
            title={getUiText(state.ui_text, 'conversation.header.session_name', 'Conversation name')}
            placeholder={getUiText(state.ui_text, 'conversation.header.session_name_placeholder', 'Enter conversation name')}
          />
        ) : (
          <button
            type="button"
            className="conversation-header__title"
            onClick={beginRename}
            disabled={sessionActionsDisabled}
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
          onClick={() => actions?.requestNewConversation(state.context_id)}
          disabled={sessionActionsDisabled}
        >
          {getUiText(state.ui_text, 'btn.new_conversation', 'New Conversation')}
        </button>
        <button
          type="button"
          className="secondary-button conversation-header__button"
          onClick={() => actions?.requestHistory()}
          disabled={sessionActionsDisabled}
        >
          {getUiText(state.ui_text, 'btn.history', 'History')}
        </button>
        <button
          type="button"
          className="secondary-button conversation-header__button"
          onClick={() => actions?.requestCompressContext(state.context_id)}
          disabled={sessionActionsDisabled}
        >
          {getUiText(state.ui_text, 'menu.conversation.compress', 'Compress Context')}
        </button>
      </div>
    </div>
  )
}
