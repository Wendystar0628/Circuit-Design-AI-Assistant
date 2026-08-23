import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import { api } from '../../lib/api'
import type { BackendEvent } from '../../types/desktop'
import { createConversationActions, type ConversationActions } from './actions'
import {
  emptyConversationState,
  normalizeConversationState,
  normalizePendingSummaryState,
  type ConversationAgentStepState,
  type ConversationMainState,
  type ConversationToolCallState,
} from './types'

type ConversationAvailability = 'idle' | 'loading' | 'ready' | 'error'

interface ConversationCollectionStateResponse {
  active: unknown
}

interface PendingEditStateResponse {
  project_id: string
  state: unknown
}

interface ConversationController {
  state: ConversationMainState
  actions: ConversationActions | null
  availability: ConversationAvailability
  errorMessage: string
}

function emptyStateForProject(projectId: string): ConversationMainState {
  return {
    ...emptyConversationState,
    project_id: projectId,
  }
}

function errorText(error: unknown): string {
  return error instanceof Error && error.message
    ? error.message
    : 'Conversation service is unavailable.'
}

function eventIdentity(event: BackendEvent, key: 'context_id' | 'run_id'): string {
  const value = event[key]
  return typeof value === 'string' ? value.trim() : ''
}

function eventPayload(event: BackendEvent): Record<string, unknown> {
  return event.payload && typeof event.payload === 'object'
    ? event.payload as Record<string, unknown>
    : {}
}

function eventText(payload: Record<string, unknown>, key: string): string {
  return typeof payload[key] === 'string' ? payload[key] : ''
}

function eventStepIndex(payload: Record<string, unknown>): number {
  const value = Number(payload.step_index)
  return Number.isSafeInteger(value) && value > 0 ? value : 1
}

function emptyRuntimeStep(stepIndex: number): ConversationAgentStepState {
  return {
    step_index: stepIndex,
    step_id: `runtime-step-${stepIndex}`,
    content: '',
    reasoning_content: '',
    tool_calls: [],
    is_complete: false,
    is_partial: false,
    stop_reason: '',
  }
}

function updateRuntimeStep(
  state: ConversationMainState,
  stepIndex: number,
  updater: (step: ConversationAgentStepState) => ConversationAgentStepState,
): ConversationMainState {
  const steps = state.conversation.runtime_steps
  const existingIndex = steps.findIndex((step) => step.step_index === stepIndex)
  const nextSteps = existingIndex >= 0
    ? steps.map((step, index) => index === existingIndex ? updater(step) : step)
    : [...steps, updater(emptyRuntimeStep(stepIndex))]
  return {
    ...state,
    conversation: {
      ...state.conversation,
      runtime_steps: nextSteps,
    },
    view_flags: {
      ...state.view_flags,
      has_runtime_steps: nextSteps.length > 0,
    },
  }
}

function runningToolCall(payload: Record<string, unknown>): ConversationToolCallState {
  return {
    tool_call_id: eventText(payload, 'tool_call_id'),
    tool_name: eventText(payload, 'tool_name'),
    arguments: payload.arguments && typeof payload.arguments === 'object'
      ? payload.arguments as Record<string, unknown>
      : {},
    result_content: '',
    status: 'running',
    details: {},
  }
}

export function useConversationController(
  projectId: string | null,
  active: boolean,
  onOpenSettings: () => void,
  onOpenWorkspaceFile: (path: string) => void,
): ConversationController {
  const normalizedProjectId = String(projectId ?? '').trim()
  const [state, setState] = useState<ConversationMainState>(() => (
    emptyStateForProject(normalizedProjectId)
  ))
  const [availability, setAvailability] = useState<ConversationAvailability>('idle')
  const [errorMessage, setErrorMessage] = useState('')
  const stateRef = useRef(state)
  const projectIdRef = useRef(normalizedProjectId)
  const lastSequenceRef = useRef(-1)
  const generationRef = useRef(0)

  const replaceState = useCallback((nextState: ConversationMainState) => {
    stateRef.current = nextState
    setState(nextState)
  }, [])

  const updateState = useCallback((
    updater: (current: ConversationMainState) => ConversationMainState,
  ) => {
    const current = stateRef.current
    const next = updater(current)
    if (next.project_id !== projectIdRef.current) {
      return
    }
    replaceState(next)
  }, [replaceState])

  const applyInitialState = useCallback((rawState: unknown, preserveLiveRag = false): boolean => {
    const expectedProjectId = projectIdRef.current
    const next = normalizeConversationState(rawState)
    if (
      !expectedProjectId
      || next.project_id !== expectedProjectId
      || !next.context_id
      || !next.session.id
    ) {
      return false
    }
    replaceState(preserveLiveRag ? { ...next, rag: stateRef.current.rag } : next)
    setAvailability('ready')
    setErrorMessage('')
    return true
  }, [replaceState])

  const applyServerState = useCallback((
    rawState: unknown,
    expectedContextId: string,
    allowContextTransition = false,
  ): boolean => {
    const current = stateRef.current
    if (
      !expectedContextId
      || current.project_id !== projectIdRef.current
      || current.context_id !== expectedContextId
    ) {
      return false
    }
    const next = normalizeConversationState(rawState)
    if (
      next.project_id !== projectIdRef.current
      || !next.context_id
      || !next.session.id
      || (!allowContextTransition && next.context_id !== expectedContextId)
    ) {
      return false
    }
    replaceState(next)
    setAvailability('ready')
    setErrorMessage('')
    return true
  }, [replaceState])

  const reportError = useCallback((error: unknown) => {
    const message = errorText(error)
    setErrorMessage(message)
    updateState((current) => ({
      ...current,
      overlays: {
        ...current.overlays,
        notice: {
          is_open: true,
          title: 'Conversation action failed',
          message,
          tone: 'error',
        },
      },
    }))
  }, [updateState])

  useEffect(() => {
    generationRef.current += 1
    const generation = generationRef.current
    const projectChanged = projectIdRef.current !== normalizedProjectId
    projectIdRef.current = normalizedProjectId
    lastSequenceRef.current = -1
    if (projectChanged) {
      replaceState(emptyStateForProject(normalizedProjectId))
    }
    setErrorMessage('')

    if (!active || !normalizedProjectId) {
      setAvailability('idle')
      return
    }

    setAvailability('loading')
    let receivedStateEvent = false
    let receivedRagEvent = false
    let latestRagSequence = -1
    const conversationsUrl = `/api/v1/projects/${encodeURIComponent(normalizedProjectId)}/conversations`

    const refreshRagSnapshot = (triggerSequence: number) => {
      void api.get<ConversationCollectionStateResponse>(conversationsUrl).then((response) => {
        if (
          generationRef.current !== generation
          || latestRagSequence !== triggerSequence
        ) {
          return
        }
        const next = normalizeConversationState(response.active)
        if (next.project_id !== normalizedProjectId || !next.context_id || !next.session.id) {
          return
        }
        updateState((current) => ({ ...current, rag: next.rag }))
      }).catch(() => {
        // The event state remains usable; the next project snapshot will refresh details.
      })
    }

    const unsubscribe = api.subscribe((event: BackendEvent) => {
      if (
        generationRef.current !== generation
        || (!event.type.startsWith('conversation.') && !event.type.startsWith('rag.'))
        || event.project_id !== normalizedProjectId
        || event.sequence <= lastSequenceRef.current
      ) {
        return
      }

      if (event.type.startsWith('rag.')) {
        if (
          event.type !== 'rag.index_started'
          && event.type !== 'rag.index_progress'
          && event.type !== 'rag.index_complete'
          && event.type !== 'rag.index_error'
        ) {
          return
        }
        receivedRagEvent = true
        latestRagSequence = event.sequence
        lastSequenceRef.current = event.sequence
        const payload = eventPayload(event)
        updateState((current) => {
          if (event.type === 'rag.index_started') {
            const total = Math.max(0, Number(payload.total_files) || 0)
            return {
              ...current,
              rag: {
                ...current.rag,
                status: { phase: 'indexing', label: 'Indexing', tone: 'info' },
                progress: { is_visible: true, processed: 0, total, current_file: '' },
                actions: {
                  ...current.rag.actions,
                  can_reindex: false,
                  can_clear: false,
                  can_search: false,
                  is_indexing: true,
                },
                info: { message: '', tone: 'neutral' },
              },
            }
          }
          if (event.type === 'rag.index_progress') {
            return {
              ...current,
              rag: {
                ...current.rag,
                progress: {
                  is_visible: true,
                  processed: Math.max(0, Number(payload.processed) || 0),
                  total: Math.max(0, Number(payload.total) || 0),
                  current_file: eventText(payload, 'current_file'),
                },
              },
            }
          }
          if (event.type === 'rag.index_complete') {
            const processed = Math.max(0, Number(payload.total_indexed) || 0)
            const failed = Math.max(0, Number(payload.failed) || 0)
            return {
              ...current,
              rag: {
                ...current.rag,
                status: { phase: 'ready', label: 'Ready', tone: failed ? 'error' : 'success' },
                stats: {
                  ...current.rag.stats,
                  processed,
                  failed,
                },
                progress: { ...current.rag.progress, is_visible: false, current_file: '' },
                actions: {
                  ...current.rag.actions,
                  can_reindex: true,
                  can_clear: true,
                  can_search: true,
                  is_indexing: false,
                },
                info: {
                  message: failed ? `Index completed with ${failed} failed files.` : 'Index completed.',
                  tone: failed ? 'error' : 'success',
                },
              },
            }
          }
          if (event.type === 'rag.index_error') {
            return {
              ...current,
              rag: {
                ...current.rag,
                status: { phase: 'error', label: 'Index failed', tone: 'error' },
                progress: { ...current.rag.progress, is_visible: false },
                actions: {
                  ...current.rag.actions,
                  can_reindex: true,
                  can_clear: true,
                  can_search: true,
                  is_indexing: false,
                },
                info: {
                  message: eventText(payload, 'error') || 'Indexing failed.',
                  tone: 'error',
                },
              },
            }
          }
          return current
        })
        if (event.type === 'rag.index_complete' || event.type === 'rag.index_error') {
          refreshRagSnapshot(event.sequence)
        }
        return
      }

      const contextId = eventIdentity(event, 'context_id')
      const runId = eventIdentity(event, 'run_id')
      const current = stateRef.current
      if (!contextId || (current.context_id && current.context_id !== contextId)) {
        return
      }
      if (runId && (!current.active_run_id || current.active_run_id !== runId)) {
        return
      }
      lastSequenceRef.current = event.sequence

      if (event.type === 'conversation.state') {
        const next = normalizeConversationState(event.state)
        if (
          next.project_id !== normalizedProjectId
          || next.context_id !== contextId
          || !next.session.id
          || (runId && next.active_run_id !== runId && next.active_run_id !== '')
        ) {
          return
        }

        receivedStateEvent = true
        replaceState(next)
        setAvailability('ready')
        setErrorMessage('')
        return
      }

      const payload = eventPayload(event)
      const stepIndex = eventStepIndex(payload)
      updateState((state) => {
        if (state.context_id !== contextId || state.active_run_id !== runId) {
          return state
        }
        if (event.type === 'conversation.turn_start') {
          const withCompletedPredecessors = {
            ...state,
            conversation: {
              ...state.conversation,
              runtime_steps: state.conversation.runtime_steps.map((step) => (
                step.step_index < stepIndex ? { ...step, is_complete: true } : step
              )),
            },
          }
          return updateRuntimeStep(withCompletedPredecessors, stepIndex, (step) => step)
        }
        if (event.type === 'conversation.stream_chunk') {
          const text = eventText(payload, 'text')
          const chunkType = eventText(payload, 'chunk_type')
          if (!text || (chunkType !== 'content' && chunkType !== 'reasoning')) {
            return state
          }
          return updateRuntimeStep(state, stepIndex, (step) => ({
            ...step,
            ...(chunkType === 'reasoning'
              ? { reasoning_content: step.reasoning_content + text }
              : { content: step.content + text }),
          }))
        }
        if (event.type === 'conversation.tool_execution_start') {
          const incoming = runningToolCall(payload)
          if (!incoming.tool_call_id) {
            return state
          }
          return updateRuntimeStep(state, stepIndex, (step) => ({
            ...step,
            tool_calls: [
              ...step.tool_calls.filter((tool) => tool.tool_call_id !== incoming.tool_call_id),
              incoming,
            ],
          }))
        }
        if (event.type === 'conversation.tool_execution_end') {
          const toolCallId = eventText(payload, 'tool_call_id')
          if (!toolCallId) {
            return state
          }
          return updateRuntimeStep(state, stepIndex, (step) => {
            const existing = step.tool_calls.find((tool) => tool.tool_call_id === toolCallId)
              ?? runningToolCall(payload)
            const completed: ConversationToolCallState = {
              ...existing,
              tool_name: eventText(payload, 'tool_name') || existing.tool_name,
              result_content: eventText(payload, 'result_content'),
              status: payload.status === 'failed' ? 'failed' : 'completed',
              details: payload.details && typeof payload.details === 'object'
                ? payload.details as Record<string, unknown>
                : {},
            }
            return {
              ...step,
              tool_calls: [
                ...step.tool_calls.filter((tool) => tool.tool_call_id !== toolCallId),
                completed,
              ],
            }
          })
        }
        if (event.type === 'conversation.completed') {
          const terminalStepIndex = state.conversation.runtime_steps.at(-1)?.step_index ?? stepIndex
          return updateRuntimeStep(state, terminalStepIndex, (step) => ({
            ...step,
            content: eventText(payload, 'content') || step.content,
            reasoning_content: eventText(payload, 'reasoning_content') || step.reasoning_content,
            is_complete: true,
          }))
        }
        if (event.type === 'conversation.stopped' || event.type === 'conversation.failed') {
          const terminalStepIndex = state.conversation.runtime_steps.at(-1)?.step_index ?? stepIndex
          return updateRuntimeStep(state, terminalStepIndex, (step) => ({
            ...step,
            is_complete: true,
            is_partial: true,
            stop_reason: event.type === 'conversation.failed' ? 'error' : 'user_requested',
          }))
        }
        return state
      })
    })

    void api.get<ConversationCollectionStateResponse>(conversationsUrl).then((response) => {
      if (generationRef.current !== generation || receivedStateEvent) {
        return
      }
      if (!applyInitialState(response.active, receivedRagEvent)) {
        throw new Error('Conversation state identity is invalid.')
      }
    }).catch((error: unknown) => {
      if (generationRef.current !== generation || receivedStateEvent) {
        return
      }
      const message = errorText(error)
      setAvailability('error')
      setErrorMessage(message)
    })

    void api.get<PendingEditStateResponse>(
      `/api/v1/projects/${encodeURIComponent(normalizedProjectId)}/pending-edits`,
    ).then((response) => {
      if (
        generationRef.current !== generation
        || response.project_id !== normalizedProjectId
      ) {
        return
      }
      const summary = normalizePendingSummaryState(response.state)
      updateState((current) => ({
        ...current,
        composer: {
          ...current.composer,
          pending_workspace_edit_summary: summary,
        },
        view_flags: {
          ...current.view_flags,
          has_pending_workspace_edits: summary.file_count > 0,
        },
      }))
    }).catch(() => {
      // The active conversation snapshot already carries a pending-edit summary.
    })

    return unsubscribe
  }, [active, applyInitialState, normalizedProjectId, replaceState, updateState])

  const actions = useMemo(() => {
    if (!normalizedProjectId) {
      return null
    }
    return createConversationActions({
      projectId: normalizedProjectId,
      onOpenSettings,
      onOpenWorkspaceFile,
      getState: () => stateRef.current,
      updateState,
      applyServerState,
      reportError,
    })
  }, [
    applyServerState,
    normalizedProjectId,
    onOpenSettings,
    onOpenWorkspaceFile,
    reportError,
    updateState,
  ])

  return { state, actions, availability, errorMessage }
}
