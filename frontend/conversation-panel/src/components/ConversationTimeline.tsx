import {
  memo,
  useCallback,
  useEffect,
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
import type { ConversationBridge } from '../bridge'
import { RichHtml } from './RichHtml'
import { getUiText } from '../uiText'

interface ConversationTimelineProps {
  state: ConversationMainState
  bridge: ConversationBridge | null
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

function toFileUrl(filePath: string): string {
  if (!filePath) {
    return ''
  }
  const normalized = filePath.replace(/\\/g, '/')
  if (/^[a-zA-Z]:\//.test(normalized)) {
    return `file:///${encodeURI(normalized)}`
  }
  if (normalized.startsWith('/')) {
    return `file://${encodeURI(normalized)}`
  }
  return encodeURI(normalized)
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

function searchStateLabel(state: string, uiText: Record<string, string>): string {
  return {
    idle: getUiText(uiText, 'conversation.timeline.search_state.idle', 'Not Started'),
    running: getUiText(uiText, 'conversation.timeline.search_state.running', 'Searching'),
    complete: getUiText(uiText, 'conversation.timeline.search_state.complete', 'Completed'),
    error: getUiText(uiText, 'conversation.timeline.search_state.error', 'Failed'),
  }[state] ?? getUiText(uiText, 'common.processing', 'Processing')
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

function summarizeSearchResult(result: Record<string, unknown>, uiText: Record<string, string>): {
  title: string
  url: string
  snippet: string
  details: string
} {
  const title = String(result.title ?? result.name ?? result.display_name ?? getUiText(uiText, 'conversation.timeline.search_result', 'Search Result'))
  const url = String(result.url ?? result.link ?? '')
  const snippet = String(result.snippet ?? result.summary ?? result.description ?? '')
  return {
    title,
    url,
    snippet,
    details: stringifyValue(result),
  }
}

const AttachmentGallery = memo(function AttachmentGallery({
  attachments,
  bridge,
  uiText,
}: {
  attachments: ConversationAttachmentState[]
  bridge: ConversationBridge | null
  uiText: Record<string, string>
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
              bridge?.previewImage?.(attachment.path)
              return
            }
            bridge?.openFile?.(attachment.path)
          }}
        >
          {isImageAttachment(attachment) && attachment.path ? (
            <img className="attachment-card__thumb" src={toFileUrl(attachment.path)} alt={attachment.name} />
          ) : (
            <div className="attachment-card__icon">{getUiText(uiText, 'common.file', 'File')}</div>
          )}
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

  return (
    <section
      className={`detail-card ${expanded ? 'detail-card--expanded' : ''}`}
      data-expanded={expanded ? 'true' : 'false'}
    >
      <button
        type="button"
        className="detail-card__header"
        onClick={() => setExpanded((current) => !current)}
      >
        <div className="detail-card__heading">
          <span className="detail-card__title">{title}</span>
          {subtitle ? <span className="detail-card__subtitle">{subtitle}</span> : null}
        </div>
        <span className="detail-card__toggle">{expanded ? getUiText(uiText, 'common.collapse', 'Collapse') : getUiText(uiText, 'common.expand', 'Expand')}</span>
      </button>
      <div className="detail-card__body-wrap">
        <div className="detail-card__body">{children}</div>
      </div>
    </section>
  )
})

const ToolCallView = memo(function ToolCallView({ toolCall, uiText }: { toolCall: ConversationToolCallState; uiText: Record<string, string> }) {
  return (
    <div className={`tool-call ${toolCall.is_error ? 'tool-call--error' : ''}`}>
      <div className="tool-call__header">
        <span className="tool-call__name">{toolCall.tool_name || getUiText(uiText, 'conversation.timeline.tool', 'Tool')}</span>
        <span className="tool-call__status">{toolCall.is_error ? getUiText(uiText, 'conversation.timeline.tool_status_failed', 'Failed') : getUiText(uiText, 'conversation.timeline.tool_status_completed', 'Completed')}</span>
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

const SearchResultsView = memo(function SearchResultsView({
  results,
  bridge,
  uiText,
}: {
  results: Array<Record<string, unknown>>
  bridge: ConversationBridge | null
  uiText: Record<string, string>
}) {
  if (!results.length) {
    return <div className="search-results__empty">{getUiText(uiText, 'conversation.timeline.no_results', 'No results')}</div>
  }

  return (
    <div className="search-results">
      {results.map((result, index) => {
        const summary = summarizeSearchResult(result, uiText)
        return (
          <article key={`${summary.url}:${index}`} className="search-result-card">
            <div className="search-result-card__header">
              <div className="search-result-card__title">{summary.title}</div>
              {summary.url ? (
                <button
                  type="button"
                  className="search-result-card__link"
                  onClick={() => bridge?.openLink?.(summary.url)}
                >
                  {getUiText(uiText, 'conversation.timeline.open_link', 'Open Link')}
                </button>
              ) : null}
            </div>
            {summary.url ? <div className="search-result-card__url">{summary.url}</div> : null}
            {summary.snippet ? <div className="search-result-card__snippet">{summary.snippet}</div> : null}
            <pre className="search-result-card__details">{summary.details}</pre>
          </article>
        )
      })}
    </div>
  )
})

const AgentStepCard = memo(function AgentStepCard({
  step,
  bridge,
  runtime,
  uiText,
}: {
  step: ConversationAgentStepState
  bridge: ConversationBridge | null
  runtime: boolean
  uiText: Record<string, string>
}) {
  const hasSearchDetails = Boolean(step.web_search_query || step.web_search_message || step.web_search_results.length)
  const hasToolDetails = step.tool_calls.length > 0

  return (
    <div className={`message-bubble message-bubble--assistant ${runtime ? 'message-bubble--runtime' : ''}`}>
      {step.reasoning_content_html ? (
        <div className="detail-card-list">
          <DetailCard
            title={getUiText(uiText, 'conversation.timeline.reasoning', 'Reasoning')}
            subtitle={step.is_complete ? getUiText(uiText, 'conversation.timeline.completed', 'Completed') : getUiText(uiText, 'conversation.timeline.in_progress', 'In Progress')}
            uiText={uiText}
          >
            <RichHtml html={step.reasoning_content_html} bridge={bridge} />
          </DetailCard>
        </div>
      ) : null}
      {step.content_html ? (
        <RichHtml html={step.content_html} bridge={bridge} className="message-bubble__content" />
      ) : (
        <div className="step-placeholder">{runtime ? getUiText(uiText, 'conversation.timeline.generating', 'Generating content…') : getUiText(uiText, 'conversation.timeline.no_content', 'No content yet')}</div>
      )}
      {step.is_partial ? <div className="partial-badge">{stopReasonLabel(step.stop_reason, uiText)}</div> : null}
      <div className="detail-card-list">
        {hasSearchDetails ? (
          <DetailCard title={getUiText(uiText, 'conversation.timeline.search_process', 'Search Process')} subtitle={searchStateLabel(step.web_search_state, uiText)} uiText={uiText}>
            {step.web_search_query ? (
              <div className="detail-label-group">
                <span className="detail-label">{getUiText(uiText, 'conversation.timeline.query', 'Query')}</span>
                <span className="detail-label__value">{step.web_search_query}</span>
              </div>
            ) : null}
            {step.web_search_message ? <div className="detail-note">{step.web_search_message}</div> : null}
            <SearchResultsView results={step.web_search_results} bridge={bridge} uiText={uiText} />
          </DetailCard>
        ) : null}
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

const SuggestionBlock = memo(function SuggestionBlock({
  message,
  bridge,
}: {
  message: ConversationMessageState
  bridge: ConversationBridge | null
}) {
  if (!message.suggestions.length) {
    return null
  }

  return (
    <div className="suggestion-block">
      {message.content_html ? (
        <RichHtml html={message.content_html} bridge={bridge} className="suggestion-block__intro" />
      ) : null}
      <div className="suggestion-chip-list">
        {message.suggestions.map((suggestion) => {
          const isSelected = suggestion.id === message.selected_suggestion_id
          const isExpired = message.suggestion_state === 'expired'
          return (
            <button
              key={suggestion.id}
              type="button"
              className={`suggestion-chip ${suggestion.is_recommended ? 'suggestion-chip--recommended' : ''} ${isSelected ? 'suggestion-chip--selected' : ''}`}
              disabled={isExpired}
              onClick={() => bridge?.selectSuggestion?.(suggestion.id)}
              title={suggestion.description || suggestion.value || suggestion.label}
            >
              <span className="suggestion-chip__label">{suggestion.label || suggestion.value}</span>
              {suggestion.description ? <span className="suggestion-chip__description">{suggestion.description}</span> : null}
            </button>
          )
        })}
      </div>
      {message.status_summary ? <div className="message-status">{message.status_summary}</div> : null}
    </div>
  )
})

const MessageBlock = memo(function MessageBlock({
  message,
  bridge,
  uiText,
}: {
  message: ConversationMessageState
  bridge: ConversationBridge | null
  uiText: Record<string, string>
}) {
  const isUser = message.role === 'user'
  const messageClassName = `timeline-row ${isUser ? 'timeline-row--user' : 'timeline-row--assistant'}`

  return (
    <article className={messageClassName}>
      {isUser ? (
        <div className="message-bubble message-bubble--user">
          <div className="message-bubble__meta">
            <span>{getUiText(uiText, 'conversation.timeline.you', 'You')}</span>
            {message.can_rollback ? (
              <button type="button" className="message-bubble__action" onClick={() => bridge?.requestRollback?.(message.id)}>
                {getUiText(uiText, 'conversation.timeline.rollback_here', 'Rollback to here')}
              </button>
            ) : null}
          </div>
          <RichHtml html={message.content_html} bridge={bridge} className="message-bubble__content" />
          <AttachmentGallery attachments={message.attachments} bridge={bridge} uiText={uiText} />
        </div>
      ) : (
        <div className="message-stack">
          {message.agent_steps.length ? (
            message.agent_steps.map((step) => (
              <AgentStepCard
                key={step.step_id || `${message.id}:${step.step_index}`}
                step={step}
                bridge={bridge}
                runtime={false}
                uiText={uiText}
              />
            ))
          ) : message.suggestions.length ? (
            <div className="message-bubble message-bubble--assistant">
              <div className="message-bubble__meta">
                <span>{getUiText(uiText, 'role.assistant', 'Assistant')}</span>
              </div>
              <SuggestionBlock message={message} bridge={bridge} />
            </div>
          ) : (
            <div className="message-bubble message-bubble--assistant">
              <div className="message-bubble__meta">
                <span>{getUiText(uiText, 'role.assistant', 'Assistant')}</span>
              </div>
              <RichHtml html={message.content_html} bridge={bridge} className="message-bubble__content" />
              <AttachmentGallery attachments={message.attachments} bridge={bridge} uiText={uiText} />
              {message.status_summary ? <div className="message-status">{message.status_summary}</div> : null}
            </div>
          )}
          {message.suggestions.length && message.agent_steps.length ? (
            <div className="message-bubble message-bubble--assistant message-bubble--suggestion-followup">
              <SuggestionBlock message={message} bridge={bridge} />
            </div>
          ) : null}
        </div>
      )}
    </article>
  )
})

export function ConversationTimeline({ state, bridge }: ConversationTimelineProps) {
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
            <MessageBlock key={message.id} message={message} bridge={bridge} uiText={uiText} />
          ))}
          {state.conversation.runtime_steps.map((step) => (
            <article key={step.step_id || `runtime:${step.step_index}`} className="timeline-row timeline-row--assistant">
              <div className="message-stack">
                <AgentStepCard step={step} bridge={bridge} runtime={true} uiText={uiText} />
              </div>
            </article>
          ))}
        </div>
      </div>
    </section>
  )
 }
