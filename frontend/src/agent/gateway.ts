import { createClientId } from '../client-id'
import type { CornAgentApiTransport } from '../api/transport'
import { parseAgentSse } from './sse'
import type { AgentContentPart, AgentFile, AgentFileInputCapabilities, AgentFileMimeType, AgentMessage, AgentQuestionResponse, AgentRun, AgentSession, AgentSessionDetail, AgentSnapshot, AgentSseEvent, AgentUploadedFile } from './types'

interface BackendFile {
  file_id: string; filename: string; mime_type: AgentFileMimeType; size_bytes: number; content_url: string
  scope: 'session'; media_kind: 'image' | 'document'; inspection_status: 'validated'
  extraction_status: 'not_requested' | 'ready'
}

interface BackendMessage {
  id: string; session_id: string; role: 'user' | 'assistant'; markdown: string
  content_parts: AgentContentPart[]; parent_message_id: string | null; version_group_id: string
  version_index: number; previous_version_id: string | null; next_version_id: string | null
  version_count: number; supersedes_message_id: string | null; process_started_at: string | null
  process_completed_at: string | null; run: BackendRun | null; created_at: string; updated_at: string
  attachments: BackendFile[]
}
interface BackendRun {
  id: string; session_id: string; user_message_id: string; assistant_message_id: string
  kind: 'create' | 'regenerate'; status: AgentRun['status']; stream_epoch: number
  next_sequence: number; provider_usage: Record<string, unknown>; error_code: string | null
  error_message: string | null; created_at: string; updated_at: string
}
interface BackendSession {
  id: string; title: string; context: Record<string, unknown>; active_leaf_message_id: string | null
  created_at: string; updated_at: string
}
interface BackendSessionDetail extends BackendSession {
  messages: BackendMessage[]; active_run: BackendRun | null; next_before: string | null
}
interface BackendSessionRun { session: BackendSession; run: BackendRun }
interface BackendSnapshot {
  run: BackendRun; draft_markdown: string; reasoning_markdown: string
  content_parts: AgentContentPart[]; replace: boolean
}

export const toRun = (run: BackendRun): AgentRun => ({
  id: run.id, sessionId: run.session_id, userMessageId: run.user_message_id,
  assistantMessageId: run.assistant_message_id, kind: run.kind, status: run.status,
  streamEpoch: run.stream_epoch, nextSequence: run.next_sequence,
  providerUsage: run.provider_usage, errorCode: run.error_code, errorMessage: run.error_message,
  createdAt: run.created_at, updatedAt: run.updated_at,
})
const toSession = (session: BackendSession): AgentSession => ({
  id: session.id, title: session.title, context: session.context,
  activeLeafMessageId: session.active_leaf_message_id,
  createdAt: session.created_at, updatedAt: session.updated_at,
})
const toMessage = (
  message: BackendMessage,
  resolveProtectedUrl: (value: string) => string,
): AgentMessage => ({
  id: message.id, sessionId: message.session_id, role: message.role, markdown: message.markdown,
  contentParts: message.content_parts, run: message.run ? toRun(message.run) : null,
  attachments: message.attachments.map((file) => toFile(file, resolveProtectedUrl)),
  parentMessageId: message.parent_message_id,
  versionGroupId: message.version_group_id, versionIndex: message.version_index,
  previousVersionId: message.previous_version_id, nextVersionId: message.next_version_id,
  versionCount: message.version_count,
  supersedesMessageId: message.supersedes_message_id,
  processStartedAt: message.process_started_at, processCompletedAt: message.process_completed_at,
  createdAt: message.created_at, updatedAt: message.updated_at,
})
const toFile = (
  file: BackendFile,
  resolveProtectedUrl: (value: string) => string,
): AgentFile => ({
  fileId: file.file_id,
  filename: file.filename,
  mimeType: file.mime_type,
  sizeBytes: file.size_bytes,
  contentUrl: resolveProtectedUrl(file.content_url),
  scope: file.scope,
  mediaKind: file.media_kind,
  inspectionStatus: file.inspection_status,
  extractionStatus: file.extraction_status,
})
const toDetail = (
  session: BackendSessionDetail,
  resolveProtectedUrl: (value: string) => string,
): AgentSessionDetail => ({
  ...toSession(session),
  messages: session.messages.map((message) => toMessage(message, resolveProtectedUrl)),
  activeRun: session.active_run ? toRun(session.active_run) : null,
  nextBefore: session.next_before,
})
export const toSnapshot = (snapshot: BackendSnapshot): AgentSnapshot => ({
  run: toRun(snapshot.run), draftMarkdown: snapshot.draft_markdown,
  reasoningMarkdown: snapshot.reasoning_markdown, contentParts: snapshot.content_parts,
  replace: snapshot.replace,
})

export class HttpAgentGateway {
  constructor(private readonly api: CornAgentApiTransport) {}
  private readonly protectedUrl = (value: string) => this.api.resolveProtectedUrl?.(value) ?? value

  async status(signal?: AbortSignal) {
    const status = await this.api.get<{
      available: boolean
      unavailable_reason?: string | null
      file_input: {
        enabled: boolean
        accepts: Array<{ mime_type: AgentFileMimeType; max_bytes: number; max_count: number }>
        max_count: number; max_total_bytes: number
      }
    }>('/agent/status', false, signal)
    const fileInput: AgentFileInputCapabilities = {
      enabled: status.file_input.enabled,
      accepts: status.file_input.accepts.map((item) => ({
        mimeType: item.mime_type,
        maxBytes: item.max_bytes,
        maxCount: item.max_count,
      })),
      maxCount: status.file_input.max_count,
      maxTotalBytes: status.file_input.max_total_bytes,
    }
    return { available: status.available, unavailableReason: status.unavailable_reason ?? null, fileInput }
  }
  async listSessions(cursor?: string | null, query?: string) {
    const params = new URLSearchParams()
    if (cursor) params.set('cursor', cursor)
    if (query?.trim()) params.set('query', query.trim())
    const suffix = params.size ? `?${params.toString()}` : ''
    const response = await this.api.get<{ data: BackendSession[]; next_cursor: string | null }>(`/agent/sessions${suffix}`, true)
    return { data: response.data.map(toSession), nextCursor: response.next_cursor }
  }
  async startSession(content: string, fileIds: string[] = [], idempotencyKey = createClientId(), signal?: AbortSignal) {
    const response = await this.api.mutate<BackendSessionRun>('/agent/sessions', {
      body: { content, attachments: fileIds.map((file_id) => ({ file_id })) }, idempotencyKey,
    }, false, signal)
    return { session: toSession(response.session), run: toRun(response.run) }
  }
  async getSession(id: string, before?: string) {
    const query = before ? `?before=${encodeURIComponent(before)}` : ''
    return toDetail(
      await this.api.get<BackendSessionDetail>(`/agent/sessions/${encodeURIComponent(id)}${query}`),
      this.protectedUrl,
    )
  }
  async deleteSession(id: string) {
    return this.api.mutate<{ id: string; deleted: boolean }>(`/agent/sessions/${encodeURIComponent(id)}`, {
      method: 'DELETE',
    })
  }
  async startRun(sessionId: string, content: string, fileIds: string[] = [], signal?: AbortSignal) {
    return toRun(await this.api.mutate<BackendRun>(`/agent/sessions/${encodeURIComponent(sessionId)}/messages`, { body: { content, attachments: fileIds.map((file_id) => ({ file_id })) } }, false, signal))
  }
  async regenerate(messageId: string) {
    return toRun(await this.api.mutate<BackendRun>(`/agent/messages/${encodeURIComponent(messageId)}/regenerate`, { body: {} }))
  }
  async edit(messageId: string, content: string) {
    return toRun(await this.api.mutate<BackendRun>(`/agent/messages/${encodeURIComponent(messageId)}/edit`, { body: { content } }))
  }
  async uploadFile(
    file: File,
    signal: AbortSignal,
    onInitiated?: (fileId: string) => void,
    existingFileId?: string,
    onPhase?: (phase: 'uploading' | 'processing') => void,
  ): Promise<AgentUploadedFile> {
    const fileId = existingFileId ?? (await this.api.mutate<{
      id: string; filename: string; mime_type: AgentFileMimeType; size_bytes: number | null; state: 'pending'
    }>('/files', {
      body: {
        purpose: 'session_attachment',
        filename: file.name,
        mime_type: file.type || 'application/octet-stream',
        size_bytes: file.size,
      },
    }, false, signal)).id
    onInitiated?.(fileId)
    onPhase?.('uploading')
    const stored = await this.api.mutate<{
      id: string; filename: string; mime_type: AgentFileMimeType; size_bytes: number; state: 'stored' | 'ready'
      inspection_status: 'validated'; extraction_status: 'not_requested' | 'pending' | 'ready'
    }>(`/files/${encodeURIComponent(fileId)}/content`, {
      method: 'PUT',
      rawBody: file,
      contentType: file.type || 'application/octet-stream',
    }, false, signal)
    const completed = stored.mime_type === 'application/pdf'
      ? await (async () => {
        onPhase?.('processing')
        return this.api.mutate<typeof stored>(`/files/${encodeURIComponent(stored.id)}/extract`, {
          body: {},
        }, false, signal)
      })()
      : stored
    return {
      fileId: completed.id,
      filename: completed.filename,
      mimeType: completed.mime_type,
      sizeBytes: completed.size_bytes,
      state: completed.state,
      contentUrl: this.protectedUrl(
        `/api/v1/files/${encodeURIComponent(completed.id)}/content`,
      ),
      scope: 'session',
      mediaKind: completed.mime_type === 'application/pdf' ? 'document' : 'image',
      inspectionStatus: 'validated',
      extractionStatus: completed.mime_type === 'application/pdf' ? 'ready' : 'not_requested',
    }
  }
  async deleteFile(fileId: string, signal?: AbortSignal) {
    await this.api.mutate(`/files/${encodeURIComponent(fileId)}`, { method: 'DELETE' }, false, signal)
  }
  async switchVersion(sessionId: string, messageId: string) {
    return toDetail(
      await this.api.mutate<BackendSessionDetail>(`/agent/sessions/${encodeURIComponent(sessionId)}/active-version`, { body: { message_id: messageId } }),
      this.protectedUrl,
    )
  }
  async respond(questionId: string, payload: AgentQuestionResponse, idempotencyKey = createClientId()) {
    return this.api.mutate(`/agent/questions/${encodeURIComponent(questionId)}/respond`, {
      body: payload, idempotencyKey, retryTransient: false,
    })
  }
  async cancel(runId: string) { await this.api.mutate(`/agent/runs/${encodeURIComponent(runId)}/cancel`, { body: {} }) }
  async *stream(runId: string, signal: AbortSignal, lastEventId?: string): AsyncGenerator<AgentSseEvent> {
    const response = await this.api.openEventStream({
      path: `/agent/runs/${encodeURIComponent(runId)}/stream`, signal, lastEventId,
    })
    yield* parseAgentSse(response)
  }
}
