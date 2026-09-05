export const AGENT_THINKING_STREAMING_TITLE = '正在思考'
export const AGENT_THINKING_DONE_TITLE = '已思考'

interface AgentReasoningPartLike {
  id: string
  kind: string
}

export function resolveAgentStreamingReasoningTitle(
  reasoningStatus?: string | null,
  pendingReasoningTitle?: string | null,
): string {
  const normalizedStatus = reasoningStatus?.trim()
  if (normalizedStatus) {
    return normalizedStatus
  }

  const normalizedPendingTitle = pendingReasoningTitle?.trim()
  if (normalizedPendingTitle) {
    return normalizedPendingTitle
  }

  return AGENT_THINKING_STREAMING_TITLE
}

export function finishAgentReasoningTitle(title?: string | null): string {
  const normalizedTitle = title?.trim()
  if (!normalizedTitle) {
    return AGENT_THINKING_DONE_TITLE
  }
  if (normalizedTitle === AGENT_THINKING_STREAMING_TITLE) {
    return AGENT_THINKING_DONE_TITLE
  }
  const runningSuffix = normalizedTitle.startsWith('正在')
    ? normalizedTitle.slice('正在'.length)
    : ''
  if (runningSuffix) {
    return `已${runningSuffix}`
  }
  return normalizedTitle
}

export function getActiveAgentReasoningPartId(
  parts: readonly AgentReasoningPartLike[],
  isProcessActive: boolean,
): string | null {
  if (!isProcessActive) {
    return null
  }

  const lastPart = parts[parts.length - 1]
  return lastPart?.kind === 'reasoning' ? lastPart.id : null
}

export function isStandaloneAgentReasoningActive(
  parts: readonly AgentReasoningPartLike[],
  isProcessActive: boolean,
  hasAnswerContent: boolean,
): boolean {
  if (!isProcessActive || hasAnswerContent) {
    return false
  }

  const lastPart = parts[parts.length - 1]
  return !lastPart || lastPart.kind === 'reasoning'
}

export function resolveAgentReasoningPartTitle(
  title: string | null | undefined,
  isActive: boolean,
): string {
  return isActive
    ? resolveAgentStreamingReasoningTitle(title)
    : finishAgentReasoningTitle(title)
}
