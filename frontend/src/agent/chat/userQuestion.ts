import type { AgentChatMessageContentPart } from './types'

export interface UserQuestionOption {
  content: string
  description: string
  id: string
}

export function getMetadataString(
  metadata: Record<string, unknown> | null | undefined,
  key: string,
): string {
  const value = metadata?.[key]
  return typeof value === 'string' ? value.trim() : ''
}

export function getUserQuestionStatus(part: AgentChatMessageContentPart): string {
  return getMetadataString(part.metadata, 'status') || 'pending'
}

export function getUserQuestionOptions(
  metadata: Record<string, unknown> | null | undefined,
): UserQuestionOption[] {
  const rawOptions = metadata?.options
  if (!Array.isArray(rawOptions)) {
    return []
  }
  return rawOptions.flatMap((item, index) => {
    if (!item || typeof item !== 'object' || Array.isArray(item)) {
      return []
    }
    const option = item as Record<string, unknown>
    const content = getMetadataString(option, 'content')
    if (!content) {
      return []
    }
    return [{
      id: getMetadataString(option, 'id') || `option-${index + 1}`,
      content,
      description: getMetadataString(option, 'description'),
    }]
  })
}
