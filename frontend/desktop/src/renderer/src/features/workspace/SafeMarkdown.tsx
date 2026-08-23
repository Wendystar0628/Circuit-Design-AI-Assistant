import type { ReactNode } from 'react'

function inlineText(text: string, keyPrefix: string): ReactNode[] {
  const tokens = text.split(/(`[^`\n]+`|\*\*[^*\n]+\*\*)/g)
  return tokens.map((token, index) => {
    if (token.startsWith('`') && token.endsWith('`')) {
      return <code key={`${keyPrefix}-${index}`}>{token.slice(1, -1)}</code>
    }
    if (token.startsWith('**') && token.endsWith('**')) {
      return <strong key={`${keyPrefix}-${index}`}>{token.slice(2, -2)}</strong>
    }
    return token
  })
}

export function SafeMarkdown({ content }: { content: string }) {
  const blocks: ReactNode[] = []
  const lines = content.replace(/\r\n?/g, '\n').split('\n')
  let code: string[] | null = null

  lines.forEach((line, index) => {
    if (/^```/.test(line)) {
      if (code === null) {
        code = []
      } else {
        blocks.push(<pre key={`code-${index}`}><code>{code.join('\n')}</code></pre>)
        code = null
      }
      return
    }
    if (code !== null) {
      code.push(line)
      return
    }
    const heading = /^(#{1,4})\s+(.+)$/.exec(line)
    if (heading) {
      const body = inlineText(heading[2], `heading-${index}`)
      if (heading[1].length === 1) blocks.push(<h1 key={index}>{body}</h1>)
      else if (heading[1].length === 2) blocks.push(<h2 key={index}>{body}</h2>)
      else blocks.push(<h3 key={index}>{body}</h3>)
      return
    }
    const bullet = /^\s*[-*+]\s+(.+)$/.exec(line)
    if (bullet) {
      blocks.push(<div className="safe-markdown__bullet" key={index}>• {inlineText(bullet[1], `bullet-${index}`)}</div>)
      return
    }
    if (/^>\s?/.test(line)) {
      blocks.push(<blockquote key={index}>{inlineText(line.replace(/^>\s?/, ''), `quote-${index}`)}</blockquote>)
      return
    }
    blocks.push(line ? <p key={index}>{inlineText(line, `line-${index}`)}</p> : <br key={index} />)
  })
  const remainingCode = code as string[] | null
  if (remainingCode !== null) {
    blocks.push(<pre key="code-tail"><code>{remainingCode.join('\n')}</code></pre>)
  }

  // React escapes every text node. Links, images, raw HTML and scripts are deliberately inert.
  return <article className="safe-markdown">{blocks}</article>
}
