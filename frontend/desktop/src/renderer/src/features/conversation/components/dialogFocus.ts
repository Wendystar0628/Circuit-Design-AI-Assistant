import { useEffect, useRef } from 'react'

const DIALOG_FOCUSABLE_SELECTOR = [
  'a[href]',
  'button:not([disabled])',
  'input:not([disabled])',
  'select:not([disabled])',
  'textarea:not([disabled])',
  '[contenteditable="true"]',
  '[tabindex]:not([tabindex="-1"])',
].join(',')

function dialogFocusableElements(dialog: HTMLElement): HTMLElement[] {
  return Array.from(dialog.querySelectorAll<HTMLElement>(DIALOG_FOCUSABLE_SELECTOR))
    .filter((element) => element.getClientRects().length > 0 && element.getAttribute('aria-hidden') !== 'true')
}

/** Keyboard behavior shared by the few concrete conversation overlays. */
export function useDialogFocus(active: boolean, onClose: () => void) {
  const dialogRef = useRef<HTMLDivElement | null>(null)
  const closeRef = useRef(onClose)
  closeRef.current = onClose

  useEffect(() => {
    const dialog = dialogRef.current
    if (!active || !dialog) {
      return
    }

    const previousFocus = document.activeElement instanceof HTMLElement
      ? document.activeElement
      : null
    const focusHandle = window.requestAnimationFrame(() => {
      const initialFocus = dialog.querySelector<HTMLElement>('[data-dialog-initial-focus]')
        ?? dialogFocusableElements(dialog)[0]
        ?? dialog
      initialFocus.focus({ preventScroll: true })
    })

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault()
        event.stopPropagation()
        closeRef.current()
        return
      }
      if (event.key !== 'Tab') {
        return
      }

      event.stopPropagation()
      const focusableElements = dialogFocusableElements(dialog)
      if (!focusableElements.length) {
        event.preventDefault()
        dialog.focus({ preventScroll: true })
        return
      }

      const firstElement = focusableElements[0]
      const lastElement = focusableElements[focusableElements.length - 1]
      const activeElement = document.activeElement
      if (event.shiftKey && (activeElement === firstElement || !dialog.contains(activeElement))) {
        event.preventDefault()
        lastElement.focus({ preventScroll: true })
      } else if (!event.shiftKey && activeElement === lastElement) {
        event.preventDefault()
        firstElement.focus({ preventScroll: true })
      }
    }

    dialog.addEventListener('keydown', handleKeyDown)
    return () => {
      window.cancelAnimationFrame(focusHandle)
      dialog.removeEventListener('keydown', handleKeyDown)
      if (previousFocus?.isConnected) {
        previousFocus.focus({ preventScroll: true })
      }
    }
  }, [active])

  return dialogRef
}
