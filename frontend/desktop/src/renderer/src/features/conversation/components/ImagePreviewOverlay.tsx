import { useEffect, useState } from 'react'

import { api } from '../../../lib/api'
import type { ConversationActions } from '../actions'
import type { ConversationImagePreviewOverlayState } from '../types'
import { getUiText } from '../uiText'
import { useDialogFocus } from './dialogFocus'

interface ImagePreviewOverlayProps {
  overlay: ConversationImagePreviewOverlayState
  actions: ConversationActions | null
  available: boolean
  contextId: string
  uiText: Record<string, string>
}

const MIN_ZOOM = 0.5
const MAX_ZOOM = 4
const ZOOM_STEP = 0.25

function clampZoom(value: number): number {
  return Math.max(MIN_ZOOM, Math.min(MAX_ZOOM, value))
}

export function ImagePreviewOverlay({
  overlay,
  actions,
  available,
  contextId,
  uiText,
}: ImagePreviewOverlayProps) {
  const [zoom, setZoom] = useState(1)
  const [loadFailed, setLoadFailed] = useState(false)
  const [objectUrl, setObjectUrl] = useState('')
  const canClose = available && Boolean(actions) && Boolean(contextId)
  const close = () => {
    if (canClose) {
      actions?.closeImagePreview(contextId)
    }
  }
  const dialogRef = useDialogFocus(overlay.is_open, close)

  useEffect(() => {
    let cancelled = false
    let createdObjectUrl = ''
    setZoom(1)
    setLoadFailed(false)
    setObjectUrl('')

    if (!overlay.source_url) {
      setLoadFailed(true)
      return undefined
    }

    void api.getBlob(overlay.source_url).then((blob) => {
      if (cancelled) {
        return
      }
      createdObjectUrl = URL.createObjectURL(blob)
      setObjectUrl(createdObjectUrl)
    }).catch(() => {
      if (!cancelled) {
        setLoadFailed(true)
      }
    })

    return () => {
      cancelled = true
      if (createdObjectUrl) {
        URL.revokeObjectURL(createdObjectUrl)
      }
    }
  }, [contextId, overlay.source_url])

  return (
    <div className="conversation-overlay conversation-overlay--modal image-preview-overlay">
      <button
        type="button"
        className="conversation-overlay__backdrop"
        onClick={close}
        disabled={!canClose}
        aria-label={getUiText(uiText, 'btn.close', 'Close')}
      />
      <div
        ref={dialogRef}
        className="conversation-modal conversation-modal--image-preview"
        role="dialog"
        aria-modal="true"
        aria-labelledby="image-preview-title"
        tabIndex={-1}
      >
        <div className="conversation-modal__header image-preview__header">
          <div className="image-preview__heading">
            <div id="image-preview-title" className="conversation-modal__title">
              {getUiText(uiText, 'dialog.image_preview.title', 'Image Preview')}
            </div>
            <div className="conversation-drawer__subtitle" title={overlay.file_name}>{overlay.file_name}</div>
          </div>
          <button
            data-dialog-initial-focus
            type="button"
            className="icon-button"
            onClick={close}
            disabled={!canClose}
            aria-label={getUiText(uiText, 'btn.close', 'Close')}
          >
            ×
          </button>
        </div>

        <div className="image-preview__canvas">
          {loadFailed ? (
            <div className="conversation-overlay-alert conversation-overlay-alert--error" role="alert">
              {getUiText(uiText, 'dialog.image_preview.load_failed', 'The image could not be loaded.')}
            </div>
          ) : !objectUrl ? (
            <div className="conversation-overlay-empty" role="status">
              {getUiText(uiText, 'common.loading', 'Loading…')}
            </div>
          ) : (
            <div className="image-preview__stage" style={{ width: `${zoom * 100}%`, height: `${zoom * 100}%` }}>
              <img
                src={objectUrl}
                alt={overlay.file_name || getUiText(uiText, 'dialog.image_preview.title', 'Image Preview')}
                onError={() => setLoadFailed(true)}
              />
            </div>
          )}
        </div>

        <div className="conversation-modal__footer image-preview__controls">
          <button
            type="button"
            className="secondary-button"
            onClick={() => setZoom((value) => clampZoom(value - ZOOM_STEP))}
            disabled={zoom <= MIN_ZOOM}
            aria-label={getUiText(uiText, 'dialog.image_preview.zoom_out', 'Zoom out')}
          >
            −
          </button>
          <button type="button" className="secondary-button" onClick={() => setZoom(1)}>
            {Math.round(zoom * 100)}%
          </button>
          <button
            type="button"
            className="secondary-button"
            onClick={() => setZoom((value) => clampZoom(value + ZOOM_STEP))}
            disabled={zoom >= MAX_ZOOM}
            aria-label={getUiText(uiText, 'dialog.image_preview.zoom_in', 'Zoom in')}
          >
            +
          </button>
          <button type="button" className="primary-button" onClick={close} disabled={!canClose}>
            {getUiText(uiText, 'btn.close', 'Close')}
          </button>
        </div>
      </div>
    </div>
  )
}
