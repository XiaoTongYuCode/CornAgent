import type { AgentContentPart } from './types'

export const OPERATION_STATES = ['committed', 'partial', 'draft', 'noop', 'failed', 'unknown'] as const
export type AgentOperationState = typeof OPERATION_STATES[number]
export interface AgentOperationField { label: string; before?: string; value: string }
export interface AgentOperationChange {
  resource_id: string
  resource_type: string
  title: string
  action: 'create' | 'update' | 'delete' | 'attach'
  href?: string
  fields?: AgentOperationField[]
}
export interface AgentOperationEvidence {
  id: string
  tool: string
  state: AgentOperationState
  counts: Record<AgentOperationState, number>
  changes: AgentOperationChange[]
  truncated: boolean
}

function object(value: unknown): Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown> : {}
}

export function operationHref(value: unknown): string | undefined {
  if (typeof value !== 'string') return undefined
  try {
    const decoded = decodeURIComponent(value)
    if (!decoded.startsWith('/') || decoded.startsWith('//') || decoded.includes('\\')
      || [...decoded].some((char) => char.charCodeAt(0) < 32)) return undefined
    return value
  } catch { return undefined }
}

function change(value: unknown): AgentOperationChange | null {
  const row = object(value)
  if (typeof row.resource_id !== 'string' || !row.resource_id
    || typeof row.resource_type !== 'string' || !row.resource_type
    || !['create', 'update', 'delete', 'attach'].includes(String(row.action))) return null
  const fields: AgentOperationField[] = Array.isArray(row.fields) ? row.fields.flatMap((value) => {
    const field = object(value)
    if (typeof field.label !== 'string' || typeof field.value !== 'string') return []
    return [{ label: field.label, value: field.value,
      ...(typeof field.before === 'string' ? { before: field.before } : {}) }]
  }) : []
  return { resource_id: row.resource_id, resource_type: row.resource_type,
    title: typeof row.title === 'string' ? row.title : '',
    action: row.action as AgentOperationChange['action'], fields,
    href: row.action === 'delete' ? undefined : operationHref(row.href) }
}

/** Read only server-owned metadata; model prose and raw tool results are never evidence. */
export function operationEvidence(parts: AgentContentPart[]): AgentOperationEvidence[] {
  const operations = new Map<string, AgentOperationEvidence>()
  for (const part of parts) {
    if (part.kind !== 'tool_call') continue
    const metadata = object(part.metadata)
    const outcome = object(metadata.operation_outcome)
    if (!OPERATION_STATES.includes(outcome.state as AgentOperationState)) continue
    const counts = Object.fromEntries(OPERATION_STATES.map((state) => {
      const value = object(outcome.counts)[state]
      return [state, typeof value === 'number' && Number.isSafeInteger(value) && value > 0 ? value : 0]
    })) as Record<AgentOperationState, number>
    operations.set(part.id, { id: part.id,
      tool: typeof metadata.tool_name === 'string' ? metadata.tool_name : '',
      state: outcome.state as AgentOperationState, counts,
      changes: ['committed', 'partial'].includes(String(outcome.state)) && Array.isArray(metadata.changes) ? metadata.changes.flatMap((value) => {
        const result = change(value)
        return result ? [result] : []
      }) : [], truncated: outcome.truncated === true })
  }
  return [...operations.values()]
}
