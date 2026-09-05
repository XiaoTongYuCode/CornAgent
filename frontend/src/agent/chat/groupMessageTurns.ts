import type { AgentMessage } from '../types'

export interface MessageTurn {
  id: string
  messages: AgentMessage[]
}

/** Group the active branch into user/assistant turns, including partial history pages. */
export function groupMessageTurns(messages: AgentMessage[]): MessageTurn[] {
  const turns: MessageTurn[] = []
  for (const message of messages) {
    const turnId = message.role === 'user' ? message.id : message.parentMessageId ?? message.id
    const previous = turns.at(-1)
    if (previous?.id === turnId) previous.messages.push(message)
    else turns.push({ id: turnId, messages: [message] })
  }
  return turns
}
