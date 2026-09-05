export type AgentRunStatus = 'pending' | 'running' | 'waiting_for_user' | 'waiting_for_subagents' | 'cancelling' | 'completed' | 'failed' | 'cancelled'

export interface AgentQuestionOption {
  id: string
  content: string
  description: string
}

export interface AgentQuestionMetadata {
  question_id: string
  run_id: string
  tool_call_id: string
  status: 'pending' | 'answered' | 'cancelled'
  options: AgentQuestionOption[]
  selected_option_id?: string
  answer_content?: string
  answered_at?: string
}

export interface AgentContentPart {
  id: string
  kind: 'markdown' | 'reasoning' | 'tool_call' | 'user_question'
  title?: string | null
  content: string
  metadata?: Record<string, unknown> | AgentQuestionMetadata
}

export type AgentFileMimeType = 'image/jpeg' | 'image/png' | 'image/webp' | 'application/pdf'

export interface AgentFile {
  fileId: string
  filename: string
  mimeType: AgentFileMimeType
  sizeBytes: number
  contentUrl: string
  scope: 'session'
  mediaKind: 'image' | 'document'
  inspectionStatus: 'validated'
  extractionStatus: 'not_requested' | 'ready'
}

export interface AgentFileConstraint {
  mimeType: AgentFileMimeType
  maxBytes: number
  maxCount: number
}

export interface AgentFileInputCapabilities {
  enabled: boolean
  accepts: AgentFileConstraint[]
  maxCount: number
  maxTotalBytes: number
}

export interface AgentUploadedFile extends AgentFile {
  state: 'stored' | 'ready'
}

export interface AgentMessage {
  id: string
  sessionId: string
  role: 'user' | 'assistant'
  markdown: string
  attachments: AgentFile[]
  contentParts: AgentContentPart[]
  run: AgentRun | null
  parentMessageId: string | null
  versionGroupId: string
  versionIndex: number
  previousVersionId: string | null
  nextVersionId: string | null
  versionCount: number
  supersedesMessageId: string | null
  processStartedAt: string | null
  processCompletedAt: string | null
  createdAt: string
  updatedAt: string
}

export interface AgentRun {
  id: string
  sessionId: string
  userMessageId: string
  assistantMessageId: string
  kind: 'create' | 'regenerate'
  status: AgentRunStatus
  streamEpoch: number
  nextSequence: number
  providerUsage: Record<string, unknown>
  errorCode: string | null
  errorMessage: string | null
  createdAt: string
  updatedAt: string
}

export interface AgentSession {
  id: string
  title: string
  context: Record<string, unknown>
  activeLeafMessageId: string | null
  createdAt: string
  updatedAt: string
}

export interface AgentSessionDetail extends AgentSession {
  messages: AgentMessage[]
  activeRun: AgentRun | null
  nextBefore: string | null
}

export interface AgentSessionPage {
  data: AgentSession[]
  nextCursor: string | null
}

export interface AgentSnapshot {
  run: AgentRun
  draftMarkdown: string
  reasoningMarkdown: string
  contentParts: AgentContentPart[]
  replace: boolean
}

export interface AgentSseEvent {
  id: string
  event: 'session' | 'delta' | 'reasoning_delta' | 'tool_call' | 'user_question' | 'snapshot' | 'done' | 'error' | 'cancelled'
  data: Record<string, unknown>
}

export type AgentQuestionResponse =
  | { action: 'answer'; option_id: string }
  | { action: 'answer'; content: string }
  | { action: 'cancel' }

export function questionMetadata(part: AgentContentPart): AgentQuestionMetadata | null {
  if (part.kind !== 'user_question' || !part.metadata) return null
  const metadata = part.metadata as Partial<AgentQuestionMetadata>
  if (!metadata.question_id || !metadata.run_id || !metadata.tool_call_id || !metadata.status || !Array.isArray(metadata.options)) return null
  return metadata as AgentQuestionMetadata
}

export function activeLineage(session: AgentSessionDetail | null): AgentMessage[] {
  if (!session?.activeLeafMessageId) return []
  const byId = new Map(session.messages.map((message) => [message.id, message]))
  const lineage: AgentMessage[] = []
  let current = byId.get(session.activeLeafMessageId)
  while (current) {
    lineage.push(current)
    current = current.parentMessageId ? byId.get(current.parentMessageId) : undefined
  }
  return lineage.reverse()
}


export type SubagentTaskStatus = 'queued' | 'running' | 'completed' | 'failed' | 'needs_input' | 'cancelled' | 'timed_out'
export interface SubagentTaskMetadata extends Record<string, unknown> {
  subagent: true
  task_id: string
  group_id: string
  task_key: string
  title: string
  profile: 'researcher' | 'analyst' | 'verifier'
  status: SubagentTaskStatus
  required: boolean
  result_available: boolean
  delivery_status: 'pending' | 'delivered' | 'ignored'
  attempt_count: number
  duration_ms: number | null
  error_code: string | null
  preview: string
}

export function subagentMetadata(part: { kind: string; metadata?: unknown }): SubagentTaskMetadata | null {
  if (part.kind !== 'tool_call' || !part.metadata || typeof part.metadata !== 'object') return null
  const metadata = part.metadata as Partial<SubagentTaskMetadata>
  if (metadata.subagent !== true || typeof metadata.task_id !== 'string' || typeof metadata.group_id !== 'string'
    || typeof metadata.title !== 'string' || typeof metadata.required !== 'boolean'
    || typeof metadata.result_available !== 'boolean'
    || !['researcher', 'analyst', 'verifier'].includes(metadata.profile ?? '')
    || !['queued', 'running', 'completed', 'failed', 'needs_input', 'cancelled', 'timed_out'].includes(metadata.status ?? '')
    || !['pending', 'delivered', 'ignored'].includes(metadata.delivery_status ?? '')) return null
  return metadata as SubagentTaskMetadata
}
