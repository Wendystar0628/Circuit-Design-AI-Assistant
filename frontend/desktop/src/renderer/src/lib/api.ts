import type {
  BackendConnectionConfig,
  BackendEvent,
} from '../types/desktop'

export class ApiError extends Error {
  readonly status: number
  readonly details: unknown

  constructor(status: number, message: string, details?: unknown) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.details = details
  }
}

type EventHandler = (event: BackendEvent) => void

function normalizeApiPath(path: string): string {
  const normalized = String(path || '').trim()
  if (!/^\/api\/v1(?:\/|$)/.test(normalized)) {
    throw new Error(`API path must start with /api/v1: ${normalized}`)
  }
  return normalized
}

function errorMessage(payload: unknown, fallback: string): string {
  if (payload && typeof payload === 'object') {
    const record = payload as Record<string, unknown>
    for (const key of ['message', 'detail', 'error']) {
      if (typeof record[key] === 'string' && record[key]) {
        return record[key]
      }
    }
  }
  return fallback
}

class DesktopApiClient {
  private configPromise: Promise<BackendConnectionConfig> | null = null
  private readonly handlers = new Set<EventHandler>()
  private socket: WebSocket | null = null
  private reconnectTimer: number | null = null
  private reconnectAttempt = 0

  private getConfig(): Promise<BackendConnectionConfig> {
    if (!this.configPromise) {
      this.configPromise = window.circuitDesktop.getBackendConfig()
    }
    return this.configPromise
  }

  private async request<T>(
    method: string,
    path: string,
    body?: unknown,
  ): Promise<T> {
    const config = await this.getConfig()
    const response = await fetch(`${config.baseUrl}${normalizeApiPath(path)}`, {
      method,
      headers: {
        Authorization: `Bearer ${config.token}`,
        Accept: 'application/json',
        ...(body === undefined ? {} : { 'Content-Type': 'application/json' }),
      },
      body: body === undefined ? undefined : JSON.stringify(body),
      cache: 'no-store',
    })
    if (response.status === 204) {
      return undefined as T
    }
    const contentType = response.headers.get('content-type') ?? ''
    const payload: unknown = contentType.includes('application/json')
      ? await response.json()
      : await response.text()
    if (!response.ok) {
      throw new ApiError(
        response.status,
        errorMessage(payload, `${method} ${path} failed`),
        payload,
      )
    }
    return payload as T
  }

  get<T>(path: string): Promise<T> {
    return this.request<T>('GET', path)
  }

  post<T>(path: string, body?: unknown): Promise<T> {
    return this.request<T>('POST', path, body)
  }

  put<T>(path: string, body?: unknown): Promise<T> {
    return this.request<T>('PUT', path, body)
  }

  patch<T>(path: string, body?: unknown): Promise<T> {
    return this.request<T>('PATCH', path, body)
  }

  delete<T>(path: string, body?: unknown): Promise<T> {
    return this.request<T>('DELETE', path, body)
  }

  async getBlob(path: string): Promise<Blob> {
    const config = await this.getConfig()
    const response = await fetch(`${config.baseUrl}${normalizeApiPath(path)}`, {
      method: 'GET',
      headers: {
        Authorization: `Bearer ${config.token}`,
      },
      cache: 'no-store',
    })
    if (!response.ok) {
      const payload: unknown = await response.text()
      throw new ApiError(
        response.status,
        errorMessage(payload, `GET ${path} failed`),
        payload,
      )
    }
    return response.blob()
  }

  subscribe(handler: EventHandler): () => void {
    this.handlers.add(handler)
    if (this.handlers.size === 1) {
      void this.connectEvents()
    }
    return () => {
      this.handlers.delete(handler)
      if (!this.handlers.size) {
        this.disconnectEvents()
      }
    }
  }

  private async connectEvents(): Promise<void> {
    if (!this.handlers.size || this.socket) {
      return
    }
    let config: BackendConnectionConfig
    try {
      config = await this.getConfig()
    } catch {
      this.scheduleReconnect()
      return
    }
    if (!this.handlers.size || this.socket) {
      return
    }
    const socket = new WebSocket(config.wsUrl)
    this.socket = socket
    let receivedHello = false

    socket.addEventListener('open', () => {
      this.reconnectAttempt = 0
    })
    socket.addEventListener('message', (message) => {
      let payload: unknown
      try {
        payload = JSON.parse(String(message.data))
      } catch {
        return
      }
      if (!payload || typeof payload !== 'object') {
        return
      }
      const event = payload as Record<string, unknown>
      if (!receivedHello) {
        receivedHello =
          event.type === 'hello' &&
          event.api_version === 'v1' &&
          typeof event.connection_id === 'string'
        if (!receivedHello) {
          socket.close(1002, 'Expected backend hello')
        }
        return
      }
      if (
        typeof event.type !== 'string' ||
        typeof event.sequence !== 'number' ||
        !Number.isSafeInteger(event.sequence)
      ) {
        return
      }
      for (const subscriber of this.handlers) {
        subscriber(event as unknown as BackendEvent)
      }
    })
    socket.addEventListener('close', () => {
      if (this.socket === socket) {
        this.socket = null
      }
      this.scheduleReconnect()
    })
    socket.addEventListener('error', () => {
      socket.close()
    })
  }

  private scheduleReconnect(): void {
    if (!this.handlers.size || this.reconnectTimer !== null) {
      return
    }
    const delay = Math.min(5000, 250 * 2 ** this.reconnectAttempt)
    this.reconnectAttempt += 1
    this.reconnectTimer = window.setTimeout(() => {
      this.reconnectTimer = null
      void this.connectEvents()
    }, delay)
  }

  private disconnectEvents(): void {
    if (this.reconnectTimer !== null) {
      window.clearTimeout(this.reconnectTimer)
      this.reconnectTimer = null
    }
    const socket = this.socket
    this.socket = null
    socket?.close(1000, 'No subscribers')
  }
}

export const api = new DesktopApiClient()
