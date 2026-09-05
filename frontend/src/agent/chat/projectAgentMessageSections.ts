import type { AgentChatMessageContentPart } from './types'

export interface AgentMessageSections {
  hasProcessActivity: boolean
  normalizedParts: AgentChatMessageContentPart[]
  processParts: AgentChatMessageContentPart[]
  visibleBoundaryId: string | null
  visibleParts: AgentChatMessageContentPart[]
}

function isPendingQuestion(part: AgentChatMessageContentPart): boolean {
  return part.kind === 'user_question' && part.metadata?.status === 'pending'
}

function hasRenderableContent(part: AgentChatMessageContentPart): boolean {
  if (part.kind === 'tool_call' || part.kind === 'user_question') {
    return true
  }
  return part.content.trim().length > 0
}

/**
 * Fold only the content before the latest non-empty Markdown part.
 * Keep that whole model round and everything after it in chronological order.
 */
export function projectAgentMessageSections(
  parts: AgentChatMessageContentPart[],
): AgentMessageSections {
  const normalizedParts = parts.filter(hasRenderableContent)
  const hasProcessActivity = normalizedParts.some((part) => (
    part.kind === 'reasoning'
    || part.kind === 'tool_call'
    || (part.kind === 'user_question' && !isPendingQuestion(part))
  ))

  if (!hasProcessActivity) {
    return {
      hasProcessActivity: false,
      normalizedParts,
      processParts: [],
      visibleBoundaryId: null,
      visibleParts: normalizedParts,
    }
  }

  let latestMarkdownIndex = -1
  normalizedParts.forEach((part, index) => {
    if (part.kind === 'markdown') {
      latestMarkdownIndex = index
    }
  })

  const processParts = normalizedParts.filter((part, index) => (
    (latestMarkdownIndex < 0 || index < latestMarkdownIndex) && !isPendingQuestion(part)
  ))
  const visibleParts = normalizedParts.filter((part, index) => (
    (latestMarkdownIndex >= 0 && index >= latestMarkdownIndex) || isPendingQuestion(part)
  ))

  return {
    hasProcessActivity,
    normalizedParts,
    processParts,
    visibleBoundaryId: latestMarkdownIndex >= 0
      ? normalizedParts[latestMarkdownIndex]?.id ?? null
      : null,
    visibleParts,
  }
}

export function getVisibleAssistantMarkdown(parts: AgentChatMessageContentPart[]): string {
  return projectAgentMessageSections(parts).visibleParts
    .filter((part) => part.kind === 'markdown')
    .map((part) => part.content.trim())
    .filter(Boolean)
    .join('\n\n')
}
