import { useEffect, useState, type KeyboardEvent } from 'react'

import type { ConversationBridge } from '../bridge'
import type { ConversationMainState } from '../types'

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
  const sessionName = state.session.name || '新对话'
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
            title="会话名称"
            placeholder="输入会话名称"
          />
        ) : (
          <button
            type="button"
            className="conversation-header__title"
            onClick={() => setIsEditing(true)}
            disabled={!bridgeConnected}
            title="重命名会话"
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
          新对话
        </button>
        <button
          type="button"
          className="secondary-button conversation-header__button"
          onClick={() => bridge?.requestHistory?.()}
          disabled={!bridgeConnected}
        >
          历史
        </button>
        <button
          type="button"
          className="secondary-button conversation-header__button"
          onClick={() => bridge?.requestCompressContext?.()}
          disabled={!bridgeConnected}
        >
          压缩
        </button>
      </div>
    </div>
  )
}
