import {
  memo,
  useCallback,
  useEffect,
  useRef,
  useState,
  type MouseEvent,
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

function stopReasonLabel(reason: string): string {
  return {
    user_requested: '已由用户停止',
    timeout: '响应超时，已中断',
    error: '生成出现错误，内容为部分结果',
    session_switch: '会话切换，中断了当前输出',
    app_shutdown: '应用关闭，中断了当前输出',
  }[reason] ?? '该回复未完整生成'
}

function searchStateLabel(state: string): string {
  return {
    idle: '未开始',
    running: '搜索中',
    complete: '已完成',
    error: '失败',
  }[state] ?? '处理中'
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

function summarizeSearchResult(result: Record<string, unknown>): {
  title: string
  url: string
  snippet: string
  details: string
} {
  const title = String(result.title ?? result.name ?? result.display_name ?? '搜索结果')
  const url = String(result.url ?? result.link ?? '')
  const snippet = String(result.snippet ?? result.summary ?? result.description ?? '')
  return {
    title,
    url,
    snippet,
    details: stringifyValue(result),
  }
}

const RichHtml = memo(function RichHtml({
  html,
  bridge,
  className,
}: {
  html: string
  bridge: ConversationBridge | null
  className?: string
}) {
  const containerRef = useRef<HTMLDivElement | null>(null)

  const handleClick = useCallback(
    (event: MouseEvent<HTMLDivElement>) => {
      const target = event.target as HTMLElement | null
      if (!target) {
        return
      }

      const actionTarget = target.closest<HTMLElement>('[data-cai-action]')
      if (actionTarget?.dataset.caiAction === 'open-file' && actionTarget.dataset.caiPath) {
        event.preventDefault()
        bridge?.openFile?.(actionTarget.dataset.caiPath)
        return
      }

      const anchor = target.closest<HTMLAnchorElement>('a[href]')
      if (!anchor) {
        return
      }

      const href = anchor.getAttribute('href') ?? ''
      if (!href) {
        return
      }

      event.preventDefault()
      if (href.startsWith('file://')) {
        bridge?.openFile?.(href.replace(/^file:\/\//, ''))
        return
      }
      bridge?.openLink?.(href)
    },
    [bridge],
  )

  useEffect(() => {
    const container = containerRef.current
    if (!container || typeof window.renderMathInElement !== 'function') {
      return
    }
    window.renderMathInElement(container, {
      delimiters: [
        { left: '$$', right: '$$', display: true },
        { left: '$', right: '$', display: false },
      ],
      throwOnError: false,
    })
  }, [html])

  if (!html) {
    return null
  }

  return (
    <div
      ref={containerRef}
      className={className ? `rich-html ${className}` : 'rich-html'}
      onClick={handleClick}
      dangerouslySetInnerHTML={{ __html: html }}
    />
  )
})

const AttachmentGallery = memo(function AttachmentGallery({
  attachments,
  bridge,
}: {
  attachments: ConversationAttachmentState[]
  bridge: ConversationBridge | null
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
            <div className="attachment-card__icon">文件</div>
          )}
          <div className="attachment-card__meta">
            <div className="attachment-card__name" title={attachment.name}>
              {attachment.name || '未命名附件'}
            </div>
            <div className="attachment-card__path" title={attachment.path}>
              {attachment.path || '未解析路径'}
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
}: {
  title: string
  subtitle?: string
  children: ReactNode
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
        <span className="detail-card__toggle">{expanded ? '收起' : '展开'}</span>
      </button>
      <div className="detail-card__body-wrap">
        <div className="detail-card__body">{children}</div>
      </div>
    </section>
  )
})

const ToolCallView = memo(function ToolCallView({ toolCall }: { toolCall: ConversationToolCallState }) {
  return (
    <div className={`tool-call ${toolCall.is_error ? 'tool-call--error' : ''}`}>
      <div className="tool-call__header">
        <span className="tool-call__name">{toolCall.tool_name || '工具'}</span>
        <span className="tool-call__status">{toolCall.is_error ? '失败' : '完成'}</span>
      </div>
      <div className="tool-call__section">
        <div className="tool-call__label">参数</div>
        <pre className="tool-call__code">{stringifyValue(toolCall.arguments)}</pre>
      </div>
      {toolCall.result_content ? (
        <div className="tool-call__section">
          <div className="tool-call__label">结果</div>
          <pre className="tool-call__code">{toolCall.result_content}</pre>
        </div>
      ) : null}
    </div>
  )
})

const SearchResultsView = memo(function SearchResultsView({
  results,
  bridge,
}: {
  results: Array<Record<string, unknown>>
  bridge: ConversationBridge | null
}) {
  if (!results.length) {
    return <div className="search-results__empty">暂无结果</div>
  }

  return (
    <div className="search-results">
      {results.map((result, index) => {
        const summary = summarizeSearchResult(result)
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
                  打开链接
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
}: {
  step: ConversationAgentStepState
  bridge: ConversationBridge | null
  runtime: boolean
}) {
  const hasSearchDetails = Boolean(step.web_search_query || step.web_search_message || step.web_search_results.length)
  const hasToolDetails = step.tool_calls.length > 0

  return (
    <div className={`message-bubble message-bubble--assistant ${runtime ? 'message-bubble--runtime' : ''}`}>
      <div className="message-bubble__meta">
        <span>{runtime ? '运行中 Step' : `Step ${step.step_index}`}</span>
        <span>{step.is_complete ? '完成' : '进行中'}</span>
      </div>
      {step.content_html ? (
        <RichHtml html={step.content_html} bridge={bridge} className="message-bubble__content" />
      ) : (
        <div className="step-placeholder">{runtime ? '正在生成内容…' : '暂无内容'}</div>
      )}
      {step.is_partial ? <div className="partial-badge">{stopReasonLabel(step.stop_reason)}</div> : null}
      <div className="detail-card-list">
        {step.reasoning_content_html ? (
          <DetailCard title="思考过程" subtitle={step.is_complete ? '已完成' : '进行中'}>
            <RichHtml html={step.reasoning_content_html} bridge={bridge} />
          </DetailCard>
        ) : null}
        {hasSearchDetails ? (
          <DetailCard title="搜索过程" subtitle={searchStateLabel(step.web_search_state)}>
            {step.web_search_query ? (
              <div className="detail-label-group">
                <span className="detail-label">查询</span>
                <span className="detail-label__value">{step.web_search_query}</span>
              </div>
            ) : null}
            {step.web_search_message ? <div className="detail-note">{step.web_search_message}</div> : null}
            <SearchResultsView results={step.web_search_results} bridge={bridge} />
          </DetailCard>
        ) : null}
        {hasToolDetails ? (
          <DetailCard title="工具调用" subtitle={`${step.tool_calls.length} 个调用`}>
            <div className="tool-call-list">
              {step.tool_calls.map((toolCall) => (
                <ToolCallView key={toolCall.tool_call_id || toolCall.tool_name} toolCall={toolCall} />
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
}: {
  message: ConversationMessageState
  bridge: ConversationBridge | null
}) {
  const isUser = message.role === 'user'
  const messageClassName = `timeline-row ${isUser ? 'timeline-row--user' : 'timeline-row--assistant'}`

  return (
    <article className={messageClassName}>
      {isUser ? (
        <div className="message-bubble message-bubble--user">
          <div className="message-bubble__meta">
            <span>你</span>
            {message.can_rollback ? (
              <button type="button" className="message-bubble__action" onClick={() => bridge?.requestRollback?.(message.id)}>
                撤回到此处
              </button>
            ) : null}
          </div>
          <RichHtml html={message.content_html} bridge={bridge} className="message-bubble__content" />
          <AttachmentGallery attachments={message.attachments} bridge={bridge} />
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
              />
            ))
          ) : message.suggestions.length ? (
            <div className="message-bubble message-bubble--assistant">
              <div className="message-bubble__meta">
                <span>助手</span>
              </div>
              <SuggestionBlock message={message} bridge={bridge} />
            </div>
          ) : (
            <div className="message-bubble message-bubble--assistant">
              <div className="message-bubble__meta">
                <span>助手</span>
              </div>
              <RichHtml html={message.content_html} bridge={bridge} className="message-bubble__content" />
              <AttachmentGallery attachments={message.attachments} bridge={bridge} />
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
             <div className="timeline-empty-state__title">开始一段新的对话</div>
             <div className="timeline-empty-state__description">发送消息、拖入文件，或让助手继续处理你的工作区变更。</div>
           </div>
         ) : null}
         {state.conversation.messages.map((message) => (
           <MessageBlock key={message.id} message={message} bridge={bridge} />
         ))}
         {state.conversation.runtime_steps.map((step) => (
           <article key={step.step_id || `runtime:${step.step_index}`} className="timeline-row timeline-row--assistant">
             <div className="message-stack">
               <AgentStepCard step={step} bridge={bridge} runtime={true} />
             </div>
           </article>
         ))}
       </div>
      </div>
    </section>
  )
 }
