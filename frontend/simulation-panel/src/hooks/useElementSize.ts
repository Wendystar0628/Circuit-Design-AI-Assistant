import { useEffect, useMemo, useState } from 'react'

interface ElementSize {
  width: number
  height: number
}

const EMPTY_SIZE: ElementSize = {
  width: 0,
  height: 0,
}

export function useElementSize<T extends HTMLElement>() {
  const [element, setElement] = useState<T | null>(null)
  const [size, setSize] = useState<ElementSize>(EMPTY_SIZE)

  const ref = useMemo(() => (node: T | null) => {
    setElement(node)
  }, [])

  useEffect(() => {
    if (element === null) {
      setSize(EMPTY_SIZE)
      return undefined
    }

    const updateSize = () => {
      const nextWidth = Math.round(element.clientWidth)
      const nextHeight = Math.round(element.clientHeight)
      setSize((previous) => {
        if (previous.width === nextWidth && previous.height === nextHeight) {
          return previous
        }
        return {
          width: nextWidth,
          height: nextHeight,
        }
      })
    }

    updateSize()

    if (typeof ResizeObserver === 'undefined') {
      window.addEventListener('resize', updateSize)
      return () => {
        window.removeEventListener('resize', updateSize)
      }
    }

    const observer = new ResizeObserver(() => {
      updateSize()
    })
    observer.observe(element)

    return () => {
      observer.disconnect()
    }
  }, [element])

  return {
    ref,
    width: size.width,
    height: size.height,
  }
}
