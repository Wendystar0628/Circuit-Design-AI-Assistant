import {
  memo,
  useCallback,
  useEffect,
  useId,
  useRef,
  useState,
  type ReactNode,
} from 'react'
import type {
  ConversationAgentStepState,
  ConversationAttachmentState,
  ConversationMainState,
  ConversationMessageState,
  ConversationToolCallState,
} from '../types'
import type { ConversationActions } from '../actions'
import { SafeMarkdown } from './SafeMarkdown'
import { getUiText } from '../uiText'

interface ConversationTimelineProps {
  state: ConversationMainState
  actions: ConversationActions | null
}

function attachmentKey(attachment: ConversationAttachmentState): string {
  return attachment.reference_id || attachment.path || attachment.name
}

function isInlineAttachment(attachment: ConversationAttachmentState): boolean {
  return attachment.placement === 'inline'
}

function isImageAttachment(attachment: ConversationAttachmentState): boolean {
  return attachment.type === 'image'
}

function stopReasonLabel(reason: string, uiText: Record<string, string>): string {
  return {
    user_requested: getUiText(uiText, 'conversation.timeline.stop_reason.user_requested', 'Stopped by user'),
    timeout: getUiText(uiText, 'conversation.timeline.stop_reason.timeout', 'Response timed out and was interrupted'),
    error: getUiText(uiText, 'conversation.timeline.stop_reason.error', 'Generation encountered an error and the content is partial'),
    session_switch: getUiText(uiText, 'conversation.timeline.stop_reason.session_switch', 'Session switched and interrupted the current response'),
    app_shutdown: getUiText(uiText, 'conversation.timeline.stop_reason.app_shutdown', 'Application shutdown interrupted the current response'),
  }[reason] ?? getUiText(uiText, 'conversation.timeline.stop_reason.incomplete', 'This response was not completed')
}

function stringifyValue(value: unknown): string {
  if (typeof value === 'string') {
    return value
  }
  try {
    return JSON.stringify(value ?? {}, null, 2)
  } catch {
    return String(value ?? '')
  }
}

const AttachmentGallery = memo(function AttachmentGallery({
  attachments,
  actions,
  uiText,
  contextId,
}: {
  attachments: ConversationAttachmentState[]
  actions: ConversationActions | null
  uiText: Record<string, string>
  contextId: string
}) {
  const galleryAttachments = attachments.filter((attachment) => !isInlineAttachment(attachment))
  if (!galleryAttachments.length) {
    return null
  }

  return (
    <div className="attachment-gallery">
      {galleryAttachments.map((attachment) => (
        <button
          key={attachmentKey(attachment)}
          type="button"
          className={`attachment-card ${isImageAttachment(attachment) ? 'attachment-card--image' : 'attachment-card--file'}`}
          onClick={() => {
            if (isImageAttachment(attachment)) {
              actions?.previewImage(contextId, attachment.path)
              return
            }
            actions?.openFile(contextId, attachment.path)
          }}
        >
          <div className="attachment-card__icon">
            {isImageAttachment(attachment)
              ? getUiText(uiText, 'common.image', 'Image')
              : getUiText(uiText, 'common.file', 'File')}
          </div>
          <div className="attachment-card__meta">
            <div className="attachment-card__name" title={attachment.name}>
              {attachment.name || getUiText(uiText, 'common.unnamed_attachment', 'Unnamed Attachment')}
            </div>
            <div className="attachment-card__path" title={attachment.path}>
              {attachment.path || getUiText(uiText, 'conversation.timeline.unresolved_path', 'Unresolved Path')}
            </div>
          </div>
        </button>
      ))}
    </div>
  )
})

const DetailCard = memo(function DetailCard({
  title,
  subtitle,
  children,
  uiText,
}: {
  title: string
  subtitle?: string
  children: ReactNode
  uiText: Record<string, string>
}) {
  const [expanded, setExpanded] = useState(false)
  const bodyId = useId()

  return (
    <section
      className={`detail-card ${expanded ? 'detail-card--expanded' : ''}`}
      data-expanded={expanded ? 'true' : 'false'}
    >
      <button
        type="button"
        className="detail-card__header"
        onClick={() => setExpanded((current) => !current)}
        aria-expanded={expanded}
        aria-controls={bodyId}
      >
        <div className="detail-card__heading">
          <span className="detail-card__title">{title}</span>
          {subtitle ? <span className="detail-card__subtitle">{subtitle}</span> : null}
        </div>
        <span className="detail-card__toggle">{expanded ? getUiText(uiText, 'common.collapse', 'Collapse') : getUiText(uiText, 'common.expand', 'Expand')}</span>
      </button>
      {expanded ? (
        <div id={bodyId} className="detail-card__body-wrap">
          <div className="detail-card__body">{children}</div>
        </div>
      ) : null}
    </section>
  )
})

const ToolCallView = memo(function ToolCallView({ toolCall, uiText }: { toolCall: ConversationToolCallState; uiText: Record<string, string> }) {
  const isFailed = toolCall.status === 'failed'
  const statusLabel = toolCall.status === 'running'
    ? getUiText(uiText, 'conversation.timeline.tool_status_running', 'Running')
    : isFailed
      ? getUiText(uiText, 'conversation.timeline.tool_status_failed', 'Failed')
      : getUiText(uiText, 'conversation.timeline.tool_status_completed', 'Completed')
  return (
    <div className={`tool-call ${isFailed ? 'tool-call--error' : ''}`}>
      <div className="tool-call__header">
        <span className="tool-call__name">{toolCall.tool_name || getUiText(uiText, 'conversation.timeline.tool', 'Tool')}</span>
        <span className="tool-call__status">{statusLabel}</span>
      </div>
      <div className="tool-call__section">
        <div className="tool-call__label">{getUiText(uiText, 'conversation.timeline.tool_arguments', 'Arguments')}</div>
        <pre className="tool-call__code">{stringifyValue(toolCall.arguments)}</pre>
      </div>
      {toolCall.result_content ? (
        <div className="tool-call__section">
          <div className="tool-call__label">{getUiText(uiText, 'conversation.timeline.tool_result', 'Result')}</div>
          <pre className="tool-call__code">{toolCall.result_content}</pre>
        </div>
      ) : null}
    </div>
  )
})

const AgentStepCard = memo(function AgentStepCard({
  step,
  actions,
  contextId,
  runtime,
  uiText,
}: {
  step: ConversationAgentStepState
  actions: ConversationActions | null
  contextId: string
  runtime: boolean
  uiText: Record<string, string>
}) {
  const hasToolDetails = step.tool_calls.length > 0

  return (
    <div className={`message-bubble message-bubble--assistant ${runtime ? 'message-bubble--runtime' : ''}`}>
      {step.reasoning_content ? (
        <div className="detail-card-list">
          <DetailCard
            title={getUiText(uiText, 'conversation.timeline.reasoning', 'Reasoning')}
            subtitle={step.is_complete ? getUiText(uiText, 'conversation.timeline.completed', 'Completed') : getUiText(uiText, 'conversation.timeline.in_progress', 'In Progress')}
            uiText={uiText}
          >
            <SafeMarkdown content={step.reasoning_content} actions={actions} contextId={contextId} />
          </DetailCard>
        </div>
      ) : null}
      {step.content ? (
        <SafeMarkdown content={step.content} actions={actions} contextId={contextId} className="message-bubble__content" />
      ) : (
        <div className="step-placeholder">{runtime ? getUiText(uiText, 'conversation.timeline.generating', 'Generating content…') : getUiText(uiText, 'conversation.timeline.no_content', 'No content yet')}</div>
      )}
      {step.is_partial ? <div className="partial-badge">{stopReasonLabel(step.stop_reason, uiText)}</div> : null}
      <div className="detail-card-list">
        {hasToolDetails ? (
          <DetailCard title={getUiText(uiText, 'conversation.timeline.tool_calls', 'Tool Calls')} subtitle={getUiText(uiText, 'conversation.timeline.call_count', '{count} calls', { count: step.tool_calls.length })} uiText={uiText}>
            <div className="tool-call-list">
              {step.tool_calls.map((toolCall) => (
                <ToolCallView key={toolCall.tool_call_id || toolCall.tool_name} toolCall={toolCall} uiText={uiText} />
              ))}
            </div>
          </DetailCard>
        ) : null}
      </div>
    </div>
  )
})

const MessageBlock = memo(function MessageBlock({
  message,
  actions,
  uiText,
  contextId,
}: {
  message: ConversationMessageState
  actions: ConversationActions | null
  uiText: Record<string, string>
  contextId: string
}) {
  const isUser = message.role === 'user'
  const messageClassName = `timeline-row ${isUser ? 'timeline-row--user' : 'timeline-row--assistant'}`

  return (
    <article className={messageClassName}>
      {isUser ? (
        <div className="message-bubble message-bubble--user">
          <div className="message-bubble__meta">
            <span>{getUiText(uiText, 'conversation.timeline.you', 'You')}</span>
            {message.can_rollback && contextId ? (
              <button type="button" className="message-bubble__action" onClick={() => actions?.requestRollback(contextId, message.id)}>
                {getUiText(uiText, 'conversation.timeline.rollback_here', 'Rollback to here')}
              </button>
            ) : null}
          </div>
          <SafeMarkdown content={message.content} actions={actions} contextId={contextId} className="message-bubble__content" />
          <AttachmentGallery attachments={message.attachments} actions={actions} uiText={uiText} contextId={contextId} />
        </div>
      ) : (
        <div className="message-stack">
          {message.agent_steps.length ? (
            message.agent_steps.map((step) => (
              <AgentStepCard
                key={step.step_id || `${message.id}:${step.step_index}`}
                step={step}
                actions={actions}
                contextId={contextId}
                runtime={false}
                uiText={uiText}
              />
            ))
          ) : (
            <div className="message-bubble message-bubble--assistant">
              <div className="message-bubble__meta">
                <span>{getUiText(uiText, 'role.assistant', 'Assistant')}</span>
              </div>
              {message.reasoning_content ? (
                <div className="detail-card-list">
                  <DetailCard
                    title={getUiText(uiText, 'conversation.timeline.reasoning', 'Reasoning')}
                    subtitle={getUiText(uiText, 'conversation.timeline.completed', 'Completed')}
                    uiText={uiText}
                  >
                    <SafeMarkdown
                      content={message.reasoning_content}
                      actions={actions}
                      contextId={contextId}
                    />
                  </DetailCard>
                </div>
              ) : null}
              <SafeMarkdown content={message.content} actions={actions} contextId={contextId} className="message-bubble__content" />
              <AttachmentGallery attachments={message.attachments} actions={actions} uiText={uiText} contextId={contextId} />
              {message.is_partial ? (
                <div className="partial-badge">{stopReasonLabel(message.stop_reason, uiText)}</div>
              ) : null}
              {message.status_summary ? <div className="message-status">{message.status_summary}</div> : null}
            </div>
          )}
        </div>
      )}
    </article>
  )
})

export function ConversationTimeline({ state, actions }: ConversationTimelineProps) {
  const scrollRef = useRef<HTMLDivElement | null>(null)
  const contentRef = useRef<HTMLDivElement | null>(null)
  const stickToBottomRef = useRef(true)
  const uiText = state.ui_text

  const scrollToBottom = useCallback(() => {
    const container = scrollRef.current
    if (!container || !stickToBottomRef.current) {
      return
    }
    container.scrollTop = container.scrollHeight
  }, [])

  useEffect(() => {
    stickToBottomRef.current = true
    const handle = window.requestAnimationFrame(scrollToBottom)
    return () => window.cancelAnimationFrame(handle)
  }, [scrollToBottom, state.context_id])

  useEffect(() => {
    const handle = window.requestAnimationFrame(scrollToBottom)
    return () => window.cancelAnimationFrame(handle)
  }, [scrollToBottom, state.conversation.messages, state.conversation.runtime_steps])

  useEffect(() => {
    const content = contentRef.current
    if (!content || typeof ResizeObserver === 'undefined') {
      return
    }
    let frameHandle = 0
    const observer = new ResizeObserver(() => {
      if (!stickToBottomRef.current) {
        return
      }
      window.cancelAnimationFrame(frameHandle)
      frameHandle = window.requestAnimationFrame(scrollToBottom)
    })
    observer.observe(content)
    return () => {
      window.cancelAnimationFrame(frameHandle)
      observer.disconnect()
    }
  }, [scrollToBottom])

  const hasAnyItems = state.conversation.messages.length > 0 || state.conversation.runtime_steps.length > 0

  return (
    <section className="timeline-shell">
      <div
        ref={scrollRef}
        className="timeline-scroll"
        onScroll={() => {
          const container = scrollRef.current
          if (!container) {
            return
          }
          const distanceToBottom = container.scrollHeight - container.scrollTop - container.clientHeight
          stickToBottomRef.current = distanceToBottom < 36
        }}
      >
        <div ref={contentRef} className="timeline-content">
          {!hasAnyItems ? (
            <div className="timeline-empty-state">
              <div className="timeline-empty-state__title">{getUiText(uiText, 'conversation.timeline.empty_title', 'Start a new conversation')}</div>
              <div className="timeline-empty-state__description">{getUiText(uiText, 'conversation.timeline.empty_description', 'Send a message, drop files, or let the assistant continue working on your workspace changes.')}</div>
            </div>
          ) : null}
          {state.conversation.messages.map((message) => (
            <MessageBlock
              key={message.id}
              message={message}
              actions={actions}
              uiText={uiText}
              contextId={state.context_id}
            />
          ))}
          {state.conversation.runtime_steps.map((step) => (
            <article key={step.step_id || `runtime:${step.step_index}`} className="timeline-row timeline-row--assistant">
              <div className="message-stack">
                <AgentStepCard step={step} actions={actions} contextId={state.context_id} runtime={true} uiText={uiText} />
              </div>
            </article>
          ))}
        </div>
      </div>
    </section>
  )
 }
