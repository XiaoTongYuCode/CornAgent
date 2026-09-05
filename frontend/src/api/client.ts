import { createClientId } from '../client-id'
import { CornAgentApiError, type ApiErrorBody, type CornAgentApiTransport, type EventStreamOptions, type MutationOptions } from './transport'

async function responseError(response: Response) {
  let payload: ApiErrorBody | null = null
  try { payload = await response.json() as ApiErrorBody } catch { /* Non-JSON proxy error. */ }
  return new CornAgentApiError(response.status, payload?.error?.code ?? `http_${response.status}`,
    payload?.error?.message ?? `Request failed with ${response.status}.`, payload?.error?.details)
}

/** JSON requests, idempotent mutations and SSE transport for CornAgent. */
export class HttpAgentTransport implements CornAgentApiTransport {
  readonly kind = 'cornagent-http' as const
  private readonly apiBaseUrl: string

  constructor(apiBaseUrl = '/api/v1') {
    this.apiBaseUrl = apiBaseUrl.replace(/\/+$/, '')
  }

  resolveProtectedUrl(value: string) {
    return value.startsWith('/api/v1/') ? `${this.apiBaseUrl}${value.slice('/api/v1'.length)}` : value
  }

  private async request<T>(path: string, init: RequestInit, preserveEnvelope = false): Promise<T> {
    const headers = new Headers(init.headers)
    if (!headers.has('Accept')) headers.set('Accept', 'application/json')
    if (init.body && !headers.has('Content-Type')) headers.set('Content-Type', 'application/json')
    const response = await fetch(`${this.apiBaseUrl}${path}`, { ...init, headers, credentials: 'omit' })
    if (!response.ok) throw await responseError(response)
    if (response.status === 204) return undefined as T
    const payload = await response.json()
    return (!preserveEnvelope && payload && typeof payload === 'object' && 'data' in payload
      ? payload.data : payload) as T
  }

  get<T>(path: string, preserveEnvelope = false, signal?: AbortSignal) {
    return this.request<T>(path, { signal }, preserveEnvelope)
  }

  async mutate<T>(path: string, options: MutationOptions = {}, preserveEnvelope = false, signal?: AbortSignal): Promise<T> {
    const headers = new Headers({ 'Idempotency-Key': options.idempotencyKey ?? createClientId() })
    if (options.contentType) headers.set('Content-Type', options.contentType)
    const init: RequestInit = { method: options.method ?? 'POST', headers, signal,
      body: options.rawBody ?? (options.body !== undefined ? JSON.stringify(options.body) : undefined) }
    try {
      return await this.request<T>(path, init, preserveEnvelope)
    } catch (error) {
      const retryable = error instanceof CornAgentApiError
        ? error.status === 408 || error.status === 429 || error.status >= 500
        : error instanceof TypeError || error instanceof SyntaxError
      if (options.retryTransient === false || !retryable || signal?.aborted) throw error
      return this.request<T>(path, init, preserveEnvelope)
    }
  }

  async openEventStream({ path, lastEventId, signal }: EventStreamOptions) {
    const headers = new Headers({ Accept: 'text/event-stream' })
    if (lastEventId !== undefined) headers.set('Last-Event-ID', lastEventId)
    const response = await fetch(`${this.apiBaseUrl}${path}`, { headers, signal, credentials: 'omit' })
    if (!response.ok) throw await responseError(response)
    return response
  }
}
