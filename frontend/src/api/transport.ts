export interface ApiErrorBody {
  error?: {
    code?: string
    message?: string
    details?: Record<string, unknown>
    request_id?: string | null
  }
}

export class CornAgentApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
    readonly details: Record<string, unknown> = {},
    readonly requestId: string | null = null,
  ) {
    super(message)
    this.name = 'CornAgentApiError'
  }
}

export interface MutationOptions {
  method?: 'POST' | 'PUT' | 'PATCH' | 'DELETE'
  body?: unknown
  rawBody?: BodyInit
  contentType?: string
  idempotencyKey?: string
  /** Disable the transport retry when the caller owns a bounded retry policy. */
  retryTransient?: boolean
}

export interface EventStreamOptions {
  afterSequence?: number
  path?: string
  lastEventId?: string
  signal: AbortSignal
}

export interface CornAgentApiTransport {
  readonly kind: 'cornagent-http'
  resolveProtectedUrl?(value: string): string
  get<T>(path: string, preserveEnvelope?: boolean, signal?: AbortSignal): Promise<T>
  mutate<T>(path: string, options?: MutationOptions, preserveEnvelope?: boolean, signal?: AbortSignal): Promise<T>
  openEventStream(options: EventStreamOptions): Promise<Response>
}

export function isCornAgentApiError(error: unknown): error is CornAgentApiError {
  return error instanceof CornAgentApiError
}

export function apiErrorMessage(error: unknown, fallback: string, translator?: (zh: string, en: string) => string) {
  return error instanceof Error ? error.message : translator ? translator(fallback, fallback) : fallback
}
