import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import { ApiError } from '../../lib/api'
import {
  cancelSimulation,
  deleteSimulationResult,
  fetchSimulationJob,
  fetchWorkbench,
  fetchSimulationExportBlob,
  fetchSimulationSnapshot,
  requestCanonicalJsonExport,
  startSimulation,
  replaySimulation,
  subscribeToSimulationEvents,
  type NormalizedSimulationEvent,
} from './simulationApi'
import { buildResultViewModel, isSupportedCircuitPath } from './simulationModel'
import type {
  ResultViewModel,
  ExperimentSpec,
  SimulationFeatureProps,
  SimulationJobDto,
  SimulationJsonExportResponse,
  SimulationResultSummaryDto,
} from './types'

export type NoticeLevel = 'info' | 'success' | 'warning' | 'error'

export interface SimulationNotice {
  id: number
  level: NoticeLevel
  message: string
}

export interface SimulationController {
  loading: boolean
  snapshotReady: boolean
  resultLoading: boolean
  busyAction: string | null
  jobs: SimulationJobDto[]
  results: SimulationResultSummaryDto[]
  activeJob: SimulationJobDto | null
  blockingJob: SimulationJobDto | null
  selected: ResultViewModel | null
  notice: SimulationNotice | null
  canRun: boolean
  refresh(): Promise<void>
  run(experiment: ExperimentSpec): Promise<void>
  replay(): Promise<void>
  cancel(): Promise<void>
  selectResult(resultId: string, expectedJobId: string | null): Promise<ResultViewModel | null>
  deleteSelected(): Promise<void>
  exportCanonicalJson(): Promise<{ metadata: SimulationJsonExportResponse; blob: Blob } | null>
  clearNotice(): void
}

const LIVE_JOB_STATUSES = new Set(['pending', 'running'])

function replaceJob(jobs: SimulationJobDto[], next: SimulationJobDto): SimulationJobDto[] {
  const index = jobs.findIndex((job) => job.job_id === next.job_id)
  if (index < 0) return [next, ...jobs]
  const copy = [...jobs]
  copy[index] = next
  return copy
}

function eventStatus(event: NormalizedSimulationEvent): SimulationJobDto['status'] {
  if (event.type === 'simulation.started') return 'running'
  if (event.type === 'simulation.completed') return 'completed'
  if (event.type === 'simulation.cancelled') return 'cancelled'
  return 'failed'
}

function errorText(error: unknown): string {
  return error instanceof Error && error.message ? error.message : 'The operation failed.'
}

function normalizedCircuitPath(path: string): string {
  return path.trim().replaceAll('\\', '/').replace(/^\.\//, '').toLowerCase()
}

export function useSimulationController({
  active,
  projectId,
  activeDocumentPath,
}: SimulationFeatureProps): SimulationController {
  const [loading, setLoading] = useState(false)
  const [resultLoading, setResultLoading] = useState(false)
  const [busyAction, setBusyAction] = useState<string | null>(null)
  const [jobs, setJobs] = useState<SimulationJobDto[]>([])
  const [results, setResults] = useState<SimulationResultSummaryDto[]>([])
  const [loadedSnapshotProjectId, setLoadedSnapshotProjectId] = useState<string | null>(null)
  const [activeJobId, setActiveJobId] = useState<string | null>(null)
  const [selected, setSelected] = useState<ResultViewModel | null>(null)
  const [notice, setNotice] = useState<SimulationNotice | null>(null)
  const generationRef = useRef(0)
  const snapshotRequestRef = useRef(0)
  const loadingRequestRef = useRef(0)
  const resultRequestRef = useRef(0)
  const noticeSequenceRef = useRef(0)
  const eventSequenceRef = useRef(-1)
  const activeJobIdRef = useRef<string | null>(null)
  const projectIdRef = useRef(projectId)
  const selectedRef = useRef<ResultViewModel | null>(null)

  projectIdRef.current = projectId

  useEffect(() => {
    activeJobIdRef.current = activeJobId
  }, [activeJobId])
  useEffect(() => { selectedRef.current = selected }, [selected])

  const publishNotice = useCallback((level: NoticeLevel, message: string) => {
    noticeSequenceRef.current += 1
    setNotice({ id: noticeSequenceRef.current, level, message })
  }, [])

  const applySnapshot = useCallback((snapshot: Awaited<ReturnType<typeof fetchSimulationSnapshot>>) => {
    setJobs(snapshot.jobs)
    setResults(snapshot.results)
    setSelected((current) => {
      if (!current || snapshot.results.some((result) => result.result_path === current.resultPath)) {
        return current
      }
      selectedRef.current = null
      return null
    })
    setLoadedSnapshotProjectId(snapshot.project_id)
  }, [])

  const refreshForProject = useCallback(async (expectedProjectId: string, generation: number) => {
    if (
      generationRef.current !== generation
      || projectIdRef.current !== expectedProjectId
    ) return
    const request = snapshotRequestRef.current + 1
    snapshotRequestRef.current = request
    const snapshot = await fetchSimulationSnapshot(expectedProjectId)
    if (
      generationRef.current !== generation
      || snapshotRequestRef.current !== request
      || projectIdRef.current !== expectedProjectId
    ) return
    applySnapshot(snapshot)
  }, [applySnapshot])

  const refresh = useCallback(async () => {
    if (!projectId) return
    const generation = generationRef.current
    const loadingRequest = loadingRequestRef.current + 1
    loadingRequestRef.current = loadingRequest
    setLoading(true)
    try {
      await refreshForProject(projectId, generation)
    } catch (error) {
      if (
        generationRef.current === generation
        && loadingRequestRef.current === loadingRequest
        && projectIdRef.current === projectId
      ) {
        publishNotice('error', errorText(error))
      }
    } finally {
      if (
        generationRef.current === generation
        && loadingRequestRef.current === loadingRequest
        && projectIdRef.current === projectId
      ) {
        setLoading(false)
      }
    }
  }, [projectId, publishNotice, refreshForProject])

  useEffect(() => {
    generationRef.current += 1
    snapshotRequestRef.current += 1
    loadingRequestRef.current += 1
    resultRequestRef.current += 1
    eventSequenceRef.current = -1
    setJobs([])
    setResults([])
    setLoadedSnapshotProjectId(null)
    setActiveJobId(null)
    activeJobIdRef.current = null
    setSelected(null)
    selectedRef.current = null
    setNotice(null)
    setBusyAction(null)
    setResultLoading(false)
    if (!projectId) {
      setLoading(false)
      return
    }
    const generation = generationRef.current
    const loadingRequest = loadingRequestRef.current + 1
    loadingRequestRef.current = loadingRequest
    setLoading(true)
    void refreshForProject(projectId, generation)
      .catch((error) => {
        if (
          generationRef.current === generation
          && loadingRequestRef.current === loadingRequest
          && projectIdRef.current === projectId
        ) {
          publishNotice('error', errorText(error))
        }
      })
      .finally(() => {
        if (
          generationRef.current === generation
          && loadingRequestRef.current === loadingRequest
          && projectIdRef.current === projectId
        ) {
          setLoading(false)
        }
      })
  }, [projectId, publishNotice, refreshForProject])

  const loadResultForIdentity = useCallback(async (
    expectedProjectId: string,
    resultId: string,
    expectedJobId: string | null,
  ) => {
    const generation = generationRef.current
    const request = resultRequestRef.current + 1
    resultRequestRef.current = request
    setResultLoading(true)
    try {
      const resultResponse = await fetchWorkbench(expectedProjectId, resultId)
      if (
        generationRef.current !== generation
        || resultRequestRef.current !== request
        || projectIdRef.current !== expectedProjectId
      ) return null
      if (resultResponse.job_id !== expectedJobId) {
        throw new Error('The selected history row no longer points to the same simulation job.')
      }
      const view = buildResultViewModel(resultResponse)
      selectedRef.current = view
      setSelected(view)
      return view
    } catch (error) {
      if (
        generationRef.current === generation
        && resultRequestRef.current === request
        && projectIdRef.current === expectedProjectId
      ) {
        setSelected(null)
        selectedRef.current = null
        publishNotice('error', errorText(error))
      }
      return null
    } finally {
      if (
        generationRef.current === generation
        && resultRequestRef.current === request
        && projectIdRef.current === expectedProjectId
      ) {
        setResultLoading(false)
      }
    }
  }, [publishNotice])

  const selectResult = useCallback(async (resultId: string, expectedJobId: string | null) => {
    if (!projectId || !resultId) return null
    return loadResultForIdentity(projectId, resultId, expectedJobId)
  }, [loadResultForIdentity, projectId])

  useEffect(() => subscribeToSimulationEvents((event) => {
    const expectedProjectId = projectIdRef.current
    if (!expectedProjectId || event.projectId !== expectedProjectId) return
    if (event.sequence <= eventSequenceRef.current) return
    eventSequenceRef.current = event.sequence
    if (event.jobId !== activeJobIdRef.current) return

    const status = eventStatus(event)
    setJobs((current) => current.map((job) => job.job_id === event.jobId
      ? {
          ...job,
          status,
          result_id: event.resultId ?? job.result_id,
          error_message: event.message ?? job.error_message,
          cancel_requested: status === 'cancelled' ? true : job.cancel_requested,
        }
      : job))

    if (event.type === 'simulation.started') {
      publishNotice('info', 'Simulation started.')
      return
    }

    if (event.type === 'simulation.completed') {
      if (!event.resultId) {
        publishNotice('error', 'Simulation completed without a result identity.')
      } else {
        publishNotice('success', 'Simulation completed.')
        void loadResultForIdentity(expectedProjectId, event.resultId, event.jobId)
      }
    } else if (event.type === 'simulation.cancelled') {
      publishNotice('warning', 'Simulation cancelled.')
      if (event.resultId) {
        void loadResultForIdentity(expectedProjectId, event.resultId, event.jobId)
      }
    } else {
      publishNotice('error', event.message ?? 'Simulation failed.')
      if (event.resultId) {
        void loadResultForIdentity(expectedProjectId, event.resultId, event.jobId)
      }
    }
    setActiveJobId(null)
    activeJobIdRef.current = null
    const generation = generationRef.current
    void refreshForProject(expectedProjectId, generation).catch(() => undefined)
  }), [loadResultForIdentity, publishNotice, refreshForProject])

  const run = useCallback(async (experiment: ExperimentSpec) => {
    if (
      !projectId
      || !activeDocumentPath
      || !isSupportedCircuitPath(activeDocumentPath)
      || activeJobIdRef.current
      || jobs.some((job) => (
        LIVE_JOB_STATUSES.has(job.status)
        && normalizedCircuitPath(job.circuit_file) === normalizedCircuitPath(activeDocumentPath)
      ))
      || loading
      || resultLoading
      || busyAction !== null
    ) return
    const generation = generationRef.current
    setBusyAction('run')
    resultRequestRef.current += 1
    setResultLoading(false)
    setSelected(null)
    selectedRef.current = null
    try {
      const response = await startSimulation(projectId, activeDocumentPath, experiment)
      if (
        generationRef.current !== generation
        || projectIdRef.current !== projectId
      ) return
      if (
        response.job.origin !== 'ui_editor'
        || normalizedCircuitPath(response.job.circuit_file) !== normalizedCircuitPath(activeDocumentPath)
      ) {
        throw new Error('The simulation start response does not match the submitted editor circuit.')
      }
      snapshotRequestRef.current += 1
      setJobs((current) => replaceJob(current, response.job))
      setActiveJobId(response.job.job_id)
      activeJobIdRef.current = response.job.job_id
      publishNotice('info', response.job.status === 'running' ? 'Simulation started.' : 'Simulation queued.')
      const reconciled = await fetchSimulationJob(projectId, response.job.job_id)
      if (
        generationRef.current !== generation
        || projectIdRef.current !== projectId
        || activeJobIdRef.current !== response.job.job_id
      ) return
      setJobs((current) => replaceJob(current, reconciled.job))
      if (LIVE_JOB_STATUSES.has(reconciled.job.status)) return
      snapshotRequestRef.current += 1
      setActiveJobId(null)
      activeJobIdRef.current = null
      if (reconciled.job.status === 'completed') {
        if (!reconciled.job.result_id) {
          publishNotice('error', 'Simulation completed without a result identity.')
        } else {
          publishNotice('success', 'Simulation completed.')
        }
      } else if (reconciled.job.status === 'failed') {
        publishNotice('error', reconciled.job.error_message ?? 'Simulation failed.')
      } else if (reconciled.job.status === 'cancelled') {
        publishNotice('warning', 'Simulation cancelled.')
      }
      if (reconciled.job.result_id) {
        await loadResultForIdentity(projectId, reconciled.job.result_id, reconciled.job.job_id)
      }
      void refreshForProject(projectId, generation).catch(() => undefined)
    } catch (error) {
      if (generationRef.current === generation && projectIdRef.current === projectId) {
        publishNotice('error', errorText(error))
      }
    } finally {
      if (generationRef.current === generation && projectIdRef.current === projectId) {
        setBusyAction(null)
      }
    }
  }, [activeDocumentPath, busyAction, jobs, loadResultForIdentity, loading, projectId, publishNotice, refreshForProject, resultLoading])

  const replay = useCallback(async () => {
    const current = selectedRef.current
    if (!projectId || !current || !current.provenance.available || activeJobIdRef.current || busyAction !== null) return
    const generation = generationRef.current
    setBusyAction('replay')
    try {
      const response = await replaySimulation(projectId, current.identity.resultId)
      if (generationRef.current !== generation || projectIdRef.current !== projectId) return
      setJobs((items) => replaceJob(items, response.job))
      setActiveJobId(response.job.job_id)
      activeJobIdRef.current = response.job.job_id
      publishNotice('info', 'Replaying the saved inputs and experiment.')
    } catch (error) {
      if (generationRef.current === generation) publishNotice('error', errorText(error))
    } finally {
      if (generationRef.current === generation) setBusyAction(null)
    }
  }, [busyAction, projectId, publishNotice])

  const cancel = useCallback(async () => {
    const expectedProjectId = projectId
    const expectedJobId = activeJobIdRef.current
    if (!expectedProjectId || !expectedJobId) return
    const generation = generationRef.current
    setBusyAction('cancel')
    try {
      await cancelSimulation(expectedProjectId, expectedJobId)
      if (
        generationRef.current !== generation
        || projectIdRef.current !== expectedProjectId
        || activeJobIdRef.current !== expectedJobId
      ) return
      setJobs((current) => current.map((job) => job.job_id === expectedJobId
        ? { ...job, cancel_requested: true }
        : job))
      publishNotice('info', 'Cancellation requested.')
    } catch (error) {
      if (generationRef.current === generation && projectIdRef.current === expectedProjectId) {
        publishNotice('error', errorText(error))
      }
    } finally {
      if (generationRef.current === generation && projectIdRef.current === expectedProjectId) {
        setBusyAction(null)
      }
    }
  }, [projectId, publishNotice])

  const deleteSelected = useCallback(async () => {
    const current = selected
    if (!current || current.identity.projectId !== projectId) return
    const generation = generationRef.current
    setBusyAction('delete')
    try {
      await deleteSimulationResult(current.identity.projectId, current.identity.resultId)
      if (
        generationRef.current !== generation
        || projectIdRef.current !== current.identity.projectId
        || selectedRef.current?.identity.resultId !== current.identity.resultId
      ) return
      setSelected(null)
      selectedRef.current = null
      snapshotRequestRef.current += 1
      setResults((items) => items.filter((item) => item.result_id !== current.identity.resultId))
      publishNotice('success', 'Simulation result deleted.')
    } catch (error) {
      if (generationRef.current === generation && projectIdRef.current === current.identity.projectId) {
        publishNotice('error', errorText(error))
      }
    } finally {
      if (generationRef.current === generation && projectIdRef.current === current.identity.projectId) {
        setBusyAction(null)
      }
    }
  }, [projectId, publishNotice, selected])

  const exportCanonicalJson = useCallback(async () => {
    const current = selected
    if (!current || current.identity.projectId !== projectId) return null
    const generation = generationRef.current
    setBusyAction('export-json')
    try {
      const response = await requestCanonicalJsonExport(
        current.identity.projectId,
        current.identity.resultId,
        current.identity.jobId,
      )
      if (
        generationRef.current !== generation
        || projectIdRef.current !== current.identity.projectId
        || selectedRef.current?.identity.resultId !== current.identity.resultId
      ) return null
      const blob = await fetchSimulationExportBlob(response.download_url)
      if (
        generationRef.current !== generation
        || projectIdRef.current !== current.identity.projectId
        || selectedRef.current?.identity.resultId !== current.identity.resultId
      ) return null
      publishNotice('success', 'Canonical result-data JSON export is ready.')
      return { metadata: response, blob }
    } catch (error) {
      if (generationRef.current === generation && projectIdRef.current === current.identity.projectId) {
        publishNotice('error', errorText(error))
      }
      return null
    } finally {
      if (generationRef.current === generation && projectIdRef.current === current.identity.projectId) {
        setBusyAction(null)
      }
    }
  }, [projectId, publishNotice, selected])

  const activeJob = useMemo(
    () => jobs.find((job) => job.job_id === activeJobId) ?? null,
    [activeJobId, jobs],
  )
  const blockingJob = useMemo(() => {
    if (!activeDocumentPath) return null
    const expectedCircuit = normalizedCircuitPath(activeDocumentPath)
    return jobs.find((job) => (
      LIVE_JOB_STATUSES.has(job.status)
      && normalizedCircuitPath(job.circuit_file) === expectedCircuit
    )) ?? null
  }, [activeDocumentPath, jobs])
  const recoverableEditorJob = useMemo(() => {
    if (!activeDocumentPath) return null
    const expectedCircuit = normalizedCircuitPath(activeDocumentPath)
    return jobs
      .filter((job) => (
        job.origin === 'ui_editor'
        && LIVE_JOB_STATUSES.has(job.status)
        && normalizedCircuitPath(job.circuit_file) === expectedCircuit
      ))
      .sort((left, right) => right.submitted_at.localeCompare(left.submitted_at))[0] ?? null
  }, [activeDocumentPath, jobs])

  useEffect(() => {
    if (activeJobIdRef.current || !recoverableEditorJob) return
    activeJobIdRef.current = recoverableEditorJob.job_id
    setActiveJobId(recoverableEditorJob.job_id)
  }, [recoverableEditorJob])

  useEffect(() => {
    const expectedProjectId = projectId
    const observedJobId = activeJobId ?? blockingJob?.job_id ?? null
    if (!expectedProjectId || !observedJobId) return
    const generation = generationRef.current
    let stopped = false
    let timer: number | null = null

    const schedule = () => {
      if (!stopped) timer = window.setTimeout(() => void poll(), 900)
    }
    const poll = async () => {
      try {
        const response = await fetchSimulationJob(expectedProjectId, observedJobId)
        if (
          stopped
          || generationRef.current !== generation
          || projectIdRef.current !== expectedProjectId
        ) return
        setJobs((current) => replaceJob(current, response.job))
        if (LIVE_JOB_STATUSES.has(response.job.status)) {
          schedule()
          return
        }

        snapshotRequestRef.current += 1
        const owned = activeJobIdRef.current === observedJobId
        if (owned) {
          activeJobIdRef.current = null
          setActiveJobId(null)
          if (response.job.status === 'completed') {
            publishNotice(
              response.job.result_id ? 'success' : 'error',
              response.job.result_id
                ? 'Simulation completed.'
                : 'Simulation completed without a result identity.',
            )
          } else if (response.job.status === 'failed') {
            publishNotice('error', response.job.error_message ?? 'Simulation failed.')
          } else {
            publishNotice('warning', 'Simulation cancelled.')
          }
          if (response.job.result_id) {
            await loadResultForIdentity(expectedProjectId, response.job.result_id, response.job.job_id)
          }
        }
        void refreshForProject(expectedProjectId, generation).catch(() => undefined)
      } catch (error) {
        if (
          stopped
          || generationRef.current !== generation
          || projectIdRef.current !== expectedProjectId
        ) return
        if (error instanceof ApiError && error.status === 404) {
          setJobs((current) => current.filter((job) => job.job_id !== observedJobId))
          if (activeJobIdRef.current === observedJobId) {
            activeJobIdRef.current = null
            setActiveJobId(null)
            publishNotice('error', 'The active simulation job is no longer available.')
          }
          void refreshForProject(expectedProjectId, generation).catch(() => undefined)
          return
        }
        schedule()
      }
    }

    schedule()
    return () => {
      stopped = true
      if (timer !== null) window.clearTimeout(timer)
    }
  }, [activeJobId, blockingJob?.job_id, loadResultForIdentity, projectId, publishNotice, refreshForProject])

  const canRun = Boolean(
    active
    && projectId
    && isSupportedCircuitPath(activeDocumentPath)
    && !activeJobId
    && !blockingJob
    && !loading
    && !resultLoading
    && busyAction === null,
  )

  return {
    loading,
    snapshotReady: projectId !== null && loadedSnapshotProjectId === projectId,
    resultLoading,
    busyAction,
    jobs,
    results,
    activeJob,
    blockingJob,
    selected,
    notice,
    canRun,
    refresh,
    run,
    replay,
    cancel,
    selectResult,
    deleteSelected,
    exportCanonicalJson,
    clearNotice: () => setNotice(null),
  }
}
