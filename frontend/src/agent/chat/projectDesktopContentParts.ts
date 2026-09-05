import type { AgentContentPart } from '../types'
import type { AgentChatMessageContentPart } from './types'

function projectContentPart(part: AgentContentPart): AgentChatMessageContentPart {
  return {
    ...part,
    metadata: part.metadata ? { ...part.metadata } : null,
  }
}

export function projectDesktopContentParts(
  parts: AgentContentPart[],
): AgentChatMessageContentPart[] {
  return parts.map(projectContentPart)
}
