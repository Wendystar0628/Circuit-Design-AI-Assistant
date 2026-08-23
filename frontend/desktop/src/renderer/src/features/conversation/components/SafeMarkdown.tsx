import type { ReactNode } from 'react'

import type { ConversationActions } from '../actions'

interface SafeMarkdownProps {
  content: string
  actions: ConversationActions | null
  contextId: string
  className?: string
}

const INLINE_TOKEN = /(`[^`\n]+`|\*\*[^*\n]+\*\*|__[^_\n]+__|\[[^\]\n]+\]\([^)\s]+\)|\*[^*\n]+\*|_[^_\n]+_)/g

function isAllowedExternalLink(value: string): boolean {
  try {
    return ['http:', 'https:', 'mailto:'].includes(new URL(value).protocol)
  } catch {
    return false
  }
}

function inlineText(
  text: string,
  keyPrefix: string,
  actions: ConversationActions | null,
  contextId: string,
): ReactNode[] {
  return text.split(INLINE_TOKEN).filter(Boolean).map((token, index) => {
    const key = `${keyPrefix}-${index}`
    if (token.startsWith('`') && token.endsWith('`')) {
      return <code key={key}>{token.slice(1, -1)}</code>
    }
    if (
      (token.startsWith('**') && token.endsWith('**'))
      || (token.startsWith('__') && token.endsWith('__'))
    ) {
      return <strong key={key}>{token.slice(2, -2)}</strong>
    }
    const link = /^\[([^\]]+)\]\(([^)\s]+)\)$/.exec(token)
    if (link) {
      if (!isAllowedExternalLink(link[2])) {
        return <span key={key}>{link[1]} ({link[2]})</span>
      }
      return (
        <button
          key={key}
          type="button"
          className="conversation-markdown__link"
          onClick={() => actions?.openLink(contextId, link[2])}
          disabled={!actions || !contextId}
        >
          {link[1]}
        </button>
      )
    }
    if (
      (token.startsWith('*') && token.endsWith('*'))
      || (token.startsWith('_') && token.endsWith('_'))
    ) {
      return <em key={key}>{token.slice(1, -1)}</em>
    }
    return token
  })
}

function startsBlock(line: string): boolean {
  return !line.trim()
    || /^```/.test(line)
    || /^#{1,6}\s+/.test(line)
    || /^\s*[-*+]\s+/.test(line)
    || /^\s*\d+[.)]\s+/.test(line)
    || /^>\s?/.test(line)
    || /^\s*(?:---+|___+|\*\*\*+)\s*$/.test(line)
}

export function SafeMarkdown({
  content,
  actions,
  contextId,
  className,
}: SafeMarkdownProps) {
  const lines = content.replace(/\r\n?/g, '\n').split('\n')
  const blocks: ReactNode[] = []
  let index = 0

  while (index < lines.length) {
    const line = lines[index]
    if (!line.trim()) {
      index += 1
      continue
    }

    if (/^```/.test(line)) {
      const code: string[] = []
      const start = index
      index += 1
      while (index < lines.length && !/^```/.test(lines[index])) {
        code.push(lines[index])
        index += 1
      }
      if (index < lines.length) {
        index += 1
      }
      blocks.push(<pre key={`code-${start}`}><code>{code.join('\n')}</code></pre>)
      continue
    }

    const heading = /^(#{1,6})\s+(.+)$/.exec(line)
    if (heading) {
      const body = inlineText(heading[2], `heading-${index}`, actions, contextId)
      const level = Math.min(heading[1].length, 4)
      if (level === 1) blocks.push(<h1 key={`heading-${index}`}>{body}</h1>)
      else if (level === 2) blocks.push(<h2 key={`heading-${index}`}>{body}</h2>)
      else if (level === 3) blocks.push(<h3 key={`heading-${index}`}>{body}</h3>)
      else blocks.push(<h4 key={`heading-${index}`}>{body}</h4>)
      index += 1
      continue
    }

    if (/^\s*[-*+]\s+/.test(line)) {
      const start = index
      const items: ReactNode[] = []
      while (index < lines.length) {
        const item = /^\s*[-*+]\s+(.+)$/.exec(lines[index])
        if (!item) break
        items.push(<li key={`item-${index}`}>{inlineText(item[1], `item-${index}`, actions, contextId)}</li>)
        index += 1
      }
      blocks.push(<ul key={`list-${start}`}>{items}</ul>)
      continue
    }

    if (/^\s*\d+[.)]\s+/.test(line)) {
      const start = index
      const items: ReactNode[] = []
      while (index < lines.length) {
        const item = /^\s*\d+[.)]\s+(.+)$/.exec(lines[index])
        if (!item) break
        items.push(<li key={`item-${index}`}>{inlineText(item[1], `item-${index}`, actions, contextId)}</li>)
        index += 1
      }
      blocks.push(<ol key={`list-${start}`}>{items}</ol>)
      continue
    }

    if (/^>\s?/.test(line)) {
      const start = index
      const quote: string[] = []
      while (index < lines.length && /^>\s?/.test(lines[index])) {
        quote.push(lines[index].replace(/^>\s?/, ''))
        index += 1
      }
      blocks.push(
        <blockquote key={`quote-${start}`}>
          {inlineText(quote.join(' '), `quote-${start}`, actions, contextId)}
        </blockquote>,
      )
      continue
    }

    if (/^\s*(?:---+|___+|\*\*\*+)\s*$/.test(line)) {
      blocks.push(<hr key={`rule-${index}`} />)
      index += 1
      continue
    }

    const start = index
    const paragraph = [line.trim()]
    index += 1
    while (index < lines.length && !startsBlock(lines[index])) {
      paragraph.push(lines[index].trim())
      index += 1
    }
    blocks.push(
      <p key={`paragraph-${start}`}>
        {inlineText(paragraph.join(' '), `paragraph-${start}`, actions, contextId)}
      </p>,
    )
  }

  return (
    <div className={className ? `conversation-markdown ${className}` : 'conversation-markdown'}>
      {blocks}
    </div>
  )
}
