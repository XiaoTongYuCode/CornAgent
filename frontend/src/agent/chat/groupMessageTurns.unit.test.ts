import type { AgentMessage, AgentSessionDetail } from '../types'
import { activeLineage } from '../types'
import { groupMessageTurns } from './groupMessageTurns'

function message(id: string, role: AgentMessage['role'], parentMessageId: string | null): AgentMessage {
  return {
    id, role, parentMessageId, sessionId: 'session', markdown: id, attachments: [], contentParts: [],
    run: null, versionGroupId: id, versionIndex: 1, versionCount: 1,
    previousVersionId: null, nextVersionId: null, supersedesMessageId: null,
    processStartedAt: null, processCompletedAt: null, createdAt: '', updatedAt: '',
  }
}

it('keeps a partial history turn stable when its user message is loaded later', () => {
  const user = message('user-1', 'user', null)
  const reply = message('reply-1', 'assistant', user.id)
  const pendingUser = message('user-2', 'user', reply.id)
  const partial = groupMessageTurns([reply, pendingUser])
  const complete = groupMessageTurns([user, reply, pendingUser])
  expect(partial.map((turn) => turn.id)).toEqual(complete.map((turn) => turn.id))
  expect(complete.map((turn) => turn.messages.map((item) => item.id))).toEqual([
    ['user-1', 'reply-1'], ['user-2'],
  ])
})

it('renders the selected edit branch as turns without including the other answer', () => {
  const session: AgentSessionDetail = {
    id: 'session', title: '', context: {}, activeLeafMessageId: 'edited-answer', activeRun: null,
    nextBefore: null, createdAt: '', updatedAt: '', messages: [
      message('user-1', 'user', null), message('answer-1', 'assistant', 'user-1'),
      message('user-2', 'user', 'answer-1'), message('answer-2', 'assistant', 'user-2'),
      message('edited-user', 'user', 'answer-1'), message('edited-answer', 'assistant', 'edited-user'),
    ],
  }
  expect(groupMessageTurns(activeLineage(session)).map((turn) => turn.messages.map((item) => item.id))).toEqual([
    ['user-1', 'answer-1'], ['edited-user', 'edited-answer'],
  ])
  expect(groupMessageTurns(activeLineage({ ...session, activeLeafMessageId: 'answer-2' })).at(-1)?.id).toBe('user-2')
})
