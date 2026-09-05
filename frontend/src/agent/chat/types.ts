export interface AgentChatMessageContentPart {
  id: string
  kind: 'markdown' | 'reasoning' | 'tool_call' | 'user_question'
  content: string
  title?: string | null
  metadata?: Record<string, unknown> | null
}

export interface AgentChatUserQuestionResponse {
  action: 'answer' | 'cancel'
  content?: string
  optionId?: string | null
  questionId: string
}

export interface AgentChatMessage {
  id: string
  role: 'assistant' | 'user'
  contentParts?: AgentChatMessageContentPart[]
}
