import { memo, useCallback, useEffect, useRef, type MouseEvent } from 'react'
import type { ConversationBridge } from '../bridge'

export const RichHtml = memo(function RichHtml({
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
