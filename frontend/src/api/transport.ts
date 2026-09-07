import { messages, type MessageKey } from '../i18n/catalog'

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
  let key: MessageKey | undefined
  if (error instanceof CornAgentApiError) {
    key = errorCodes[error.code] ?? errorStatuses[error.status]
    if (!key && error.status >= 500) key = 'errorUnavailable'
  } else if (error instanceof TypeError) key = 'errorNetwork'
  if (!key) return fallback
  const [zh, en] = messages[key]
  return translator ? translator(zh, en) : en
}

const errorCodes: Readonly<Record<string, MessageKey>> = {
  file_operations_busy: 'errorFileBusy',
  file_upload_timeout: 'errorUploadTimeout',
  file_too_large: 'errorFileSize',
  file_size_mismatch: 'errorFileSize',
  file_format_invalid: 'errorFileFormat',
  file_integrity_error: 'errorFileIntegrity',
  file_content_conflict: 'errorFileIntegrity',
  file_not_writable: 'errorFileClaimed',
  file_already_claimed: 'errorFileClaimed',
  session_file_extraction_failed: 'errorPdfExtraction',
  session_file_extraction_timeout: 'errorPdfTimeout',
  agent_question_already_resolved: 'errorQuestionResolved',
  agent_run_not_waiting: 'errorQuestionResolved',
  agent_run_active: 'errorRunActive',
}
const errorStatuses: Readonly<Record<number, MessageKey>> = {
  401: 'errorUnauthorized', 403: 'errorForbidden', 404: 'errorNotFound',
  408: 'errorTimeout', 409: 'errorConflict', 413: 'errorFileSize',
  422: 'errorInvalidInput', 429: 'errorRateLimit',
}
