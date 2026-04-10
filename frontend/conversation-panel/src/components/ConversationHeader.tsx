import { useEffect, useMemo, useState, type KeyboardEvent } from 'react'

import type { ConversationBridge } from '../bridge'
import type { ConversationMainState } from '../types'

interface ConversationHeaderProps {
  state: ConversationMainState
  bridge: ConversationBridge | null
  bridgeConnected: boolean
}

function formatSessionMeta(messageCount: number): string {
  if (messageCount <= 0) {
    return '暂无消息'
  }
  return `${messageCount} 条消息`
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

  const messageCount = useMemo(
    () => state.conversation.message_count + state.conversation.runtime_steps.length,
    [state.conversation.message_count, state.conversation.runtime_steps.length],
  )

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
        <div className="conversation-header__eyebrow">会话</div>
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
        <div className="conversation-header__meta">
          <span>{formatSessionMeta(messageCount)}</span>
          <span>{state.view_flags.is_busy ? '运行中' : '就绪'}</span>
        </div>
      </div>
      <div className="conversation-header__actions">
        <button
          type="button"
          className="secondary-button"
          onClick={() => bridge?.requestNewConversation?.()}
          disabled={!bridgeConnected}
        >
          新对话
        </button>
        <button
          type="button"
          className="secondary-button"
          onClick={() => bridge?.requestHistory?.()}
          disabled={!bridgeConnected}
        >
          历史
        </button>
        <button
          type="button"
          className="secondary-button"
          onClick={() => bridge?.requestCompressContext?.()}
          disabled={!bridgeConnected}
        >
          压缩
        </button>
        <button
          type="button"
          className="secondary-button secondary-button--danger"
          onClick={() => bridge?.requestClearDisplay?.()}
          disabled={!bridgeConnected}
        >
          清空显示
        </button>
      </div>
    </div>
  )
}
