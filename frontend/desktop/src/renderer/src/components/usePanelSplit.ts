import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type RefObject,
} from 'react'

export interface PanelSplitOptions {
  storageKey: string
  dimension: 'width' | 'height'
  defaultPercent: number
  minPercent: number
  maxPercent: number
  minPrimaryPixels: number
  minSecondaryPixels: number
  maxPrimaryPixels?: number
  handlePixels?: number
}

interface PanelSplitState {
  percent: number
  minPercent: number
  maxPercent: number
  setPercent: (percent: number) => void
  percentFromPointer: (position: number) => number
}

function clamp(value: number, minimum: number, maximum: number): number {
  return Math.min(maximum, Math.max(minimum, value))
}

function storedPercent(storageKey: string, fallback: number): number {
  try {
    const value = Number(window.localStorage.getItem(storageKey))
    return Number.isFinite(value) ? value : fallback
  } catch {
    return fallback
  }
}

export function usePanelSplit(
  containerRef: RefObject<HTMLElement | null>,
  options: PanelSplitOptions,
): PanelSplitState {
  const {
    storageKey,
    dimension,
    defaultPercent,
    minPercent: configuredMinimum,
    maxPercent: configuredMaximum,
    minPrimaryPixels,
    minSecondaryPixels,
    maxPrimaryPixels,
    handlePixels = 5,
  } = options
  const [containerPixels, setContainerPixels] = useState(0)
  const [percent, setPercentState] = useState(() => clamp(
    storedPercent(storageKey, defaultPercent),
    configuredMinimum,
    configuredMaximum,
  ))
  const pendingPercentRef = useRef<number | null>(null)
  const animationFrameRef = useRef<number | null>(null)

  const bounds = useMemo(() => {
    if (containerPixels <= handlePixels) {
      return { minimum: configuredMinimum, maximum: configuredMaximum }
    }
    const pixelMinimum = (minPrimaryPixels / containerPixels) * 100
    const secondaryMaximum = (
      (containerPixels - handlePixels - minSecondaryPixels) / containerPixels
    ) * 100
    const primaryMaximum = maxPrimaryPixels === undefined
      ? configuredMaximum
      : (maxPrimaryPixels / containerPixels) * 100
    const minimum = Math.max(configuredMinimum, pixelMinimum)
    const maximum = Math.min(configuredMaximum, secondaryMaximum, primaryMaximum)
    if (maximum >= minimum) return { minimum, maximum }
    const fallback = clamp(defaultPercent, configuredMinimum, configuredMaximum)
    return { minimum: fallback, maximum: fallback }
  }, [
    configuredMaximum,
    configuredMinimum,
    containerPixels,
    defaultPercent,
    handlePixels,
    maxPrimaryPixels,
    minPrimaryPixels,
    minSecondaryPixels,
  ])

  const constrained = useCallback(
    (value: number) => clamp(value, bounds.minimum, bounds.maximum),
    [bounds.maximum, bounds.minimum],
  )

  const setPercent = useCallback((value: number) => {
    if (!Number.isFinite(value)) return
    pendingPercentRef.current = constrained(value)
    if (animationFrameRef.current !== null) return
    animationFrameRef.current = window.requestAnimationFrame(() => {
      animationFrameRef.current = null
      const pending = pendingPercentRef.current
      pendingPercentRef.current = null
      if (pending === null) return
      setPercentState((current) => current === pending ? current : pending)
    })
  }, [constrained])

  const percentFromPointer = useCallback((position: number) => {
    const element = containerRef.current
    if (!element) return percent
    const rect = element.getBoundingClientRect()
    const size = dimension === 'width' ? rect.width : rect.height
    const start = dimension === 'width' ? rect.left : rect.top
    if (size <= 0) return percent
    return constrained(((position - start) / size) * 100)
  }, [constrained, containerRef, dimension, percent])

  useEffect(() => {
    const element = containerRef.current
    if (!element) return undefined
    const updateSize = () => {
      const rect = element.getBoundingClientRect()
      const nextSize = dimension === 'width' ? rect.width : rect.height
      setContainerPixels((current) => Math.abs(current - nextSize) < 0.5 ? current : nextSize)
    }
    updateSize()
    const observer = new ResizeObserver(updateSize)
    observer.observe(element)
    return () => observer.disconnect()
  }, [containerRef, dimension])

  useEffect(() => {
    setPercentState((current) => {
      const next = constrained(current)
      return next === current ? current : next
    })
  }, [constrained])

  useEffect(() => {
    try {
      window.localStorage.setItem(storageKey, String(percent))
    } catch {
      // A writable layout preference is optional; resizing remains available in memory.
    }
  }, [percent, storageKey])

  useEffect(() => () => {
    if (animationFrameRef.current !== null) {
      window.cancelAnimationFrame(animationFrameRef.current)
    }
  }, [])

  return {
    percent,
    minPercent: bounds.minimum,
    maxPercent: bounds.maximum,
    setPercent,
    percentFromPointer,
  }
}
