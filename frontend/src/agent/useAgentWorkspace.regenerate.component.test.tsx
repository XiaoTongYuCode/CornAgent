import { act, renderHook, waitFor } from '@testing-library/react'
import type { HttpAgentGateway } from './gateway'
import { activeLineage } from './types'
import type { AgentMessage, AgentRun, AgentSessionDetail, AgentSseEvent } from './types'
import { useAgentWorkspace } from './useAgentWorkspace'

const NOW = '2026-09-02T00:00:00Z'

function run(id: string, sessionId: string): AgentRun {
  return {
    id,
    sessionId,
    userMessageId: `${id}-user`,
    assistantMessageId: `${id}-assistant`,
    kind: 'create',
    status: 'running',
    streamEpoch: 1,
    nextSequence: 1,
    providerUsage: {},
    errorCode: null,
    errorMessage: null,
    createdAt: NOW,
    updatedAt: NOW,
  }
}

function message(
  id: string,
  sessionId: string,
  role: AgentMessage['role'],
  parentMessageId: string | null,
): AgentMessage {
  return {
    id,
    sessionId,
    role,
    markdown: role === 'user' ? '测试问题' : '测试回答',
    attachments: [],
    contentParts: [],
    run: null,
    parentMessageId,
    versionGroupId: id,
    versionIndex: 1,
    previousVersionId: null,
    nextVersionId: null,
    versionCount: 1,
    supersedesMessageId: null,
    processStartedAt: NOW,
    processCompletedAt: role === 'assistant' ? NOW : null,
    createdAt: NOW,
    updatedAt: NOW,
  }
}

it('rehydrates the regenerated assistant before making it the active leaf', async () => {
  const sessionId = 'session-regenerate'
  const currentRun = run('run-current', sessionId)
  const userMessage = message(currentRun.userMessageId, sessionId, 'user', null)
  const currentAssistant = {
    ...message(currentRun.assistantMessageId, sessionId, 'assistant', userMessage.id),
    run: currentRun,
  }
  const currentSession: AgentSessionDetail = {
    id: sessionId,
    title: '重新生成测试',
    context: {},
    activeLeafMessageId: currentAssistant.id,
    createdAt: NOW,
    updatedAt: NOW,
    messages: [userMessage, currentAssistant],
    activeRun: null,
    nextBefore: null,
  }
  const regeneratedRun = {
    ...run('run-regenerated', sessionId),
    kind: 'regenerate' as const,
    status: 'pending' as const,
  }
  const regeneratedAssistant: AgentMessage = {
    ...currentAssistant,
    id: regeneratedRun.assistantMessageId,
    markdown: '',
    run: regeneratedRun,
    versionGroupId: currentAssistant.versionGroupId,
    versionIndex: 2,
    previousVersionId: currentAssistant.id,
    versionCount: 2,
    supersedesMessageId: currentAssistant.id,
    processCompletedAt: null,
  }
  const refreshedSession: AgentSessionDetail = {
    ...currentSession,
    activeLeafMessageId: regeneratedAssistant.id,
    messages: [userMessage, regeneratedAssistant],
    activeRun: regeneratedRun,
  }
  const getSession = vi.fn()
    .mockResolvedValueOnce(currentSession)
    .mockResolvedValueOnce(refreshedSession)
  const gateway = {
    status: vi.fn(async () => ({ available: true })),
    listSessions: vi.fn(async () => ({ data: [currentSession], nextCursor: null })),
    getSession,
    regenerate: vi.fn(async () => regeneratedRun),
    stream: async function* (_runId: string, signal: AbortSignal) {
      await new Promise<void>((resolve) => {
        signal.addEventListener('abort', () => resolve(), { once: true })
      })
      if (!signal.aborted) yield {} as AgentSseEvent
    },
  } as unknown as HttpAgentGateway
  const hook = renderHook(() => useAgentWorkspace(gateway, 'principal-1', sessionId))

  await waitFor(() => expect(hook.result.current.session?.id).toBe(sessionId))
  await act(() => hook.result.current.regenerate(currentAssistant.id))

  expect(getSession).toHaveBeenCalledTimes(2)
  expect(getSession).toHaveBeenLastCalledWith(sessionId)
  expect(hook.result.current.session?.activeLeafMessageId).toBe(regeneratedAssistant.id)
  expect(activeLineage(hook.result.current.session).map((item) => item.id)).toEqual([
    userMessage.id,
    regeneratedAssistant.id,
  ])
})

it('hydrates an edited user branch and retains both lineages when switching versions', async () => {
  const sessionId = 'session-edit'
  const originalUser = message('user-original', sessionId, 'user', null)
  const originalAnswer = message('answer-original', sessionId, 'assistant', originalUser.id)
  const original: AgentSessionDetail = {
    id: sessionId, title: '编辑测试', context: {}, createdAt: NOW, updatedAt: NOW,
    activeLeafMessageId: originalAnswer.id, messages: [originalUser, originalAnswer], activeRun: null, nextBefore: null,
  }
  const editRun = run('run-edit', sessionId)
  const editedUser = { ...originalUser, id: editRun.userMessageId, markdown: '修改后的问题', versionIndex: 2, versionCount: 2, previousVersionId: originalUser.id }
  const editedAnswer = { ...message(editRun.assistantMessageId, sessionId, 'assistant', editedUser.id), run: editRun }
  const edited: AgentSessionDetail = { ...original, activeLeafMessageId: editedAnswer.id, messages: [editedUser, editedAnswer], activeRun: editRun }
  const gateway = {
    status: vi.fn(async () => ({ available: true })),
    listSessions: vi.fn(async () => ({ data: [original], nextCursor: null })),
    getSession: vi.fn().mockResolvedValueOnce(original).mockResolvedValue(edited),
    edit: vi.fn(async () => editRun),
    switchVersion: vi.fn(async () => original),
    stream: async function* (_id: string, signal: AbortSignal) {
      await new Promise<void>((resolve) => signal.addEventListener('abort', () => resolve(), { once: true }))
      if (!signal.aborted) yield {} as AgentSseEvent
    },
  } as unknown as HttpAgentGateway
  const hook = renderHook(() => useAgentWorkspace(gateway, 'principal-1', sessionId))
  await waitFor(() => expect(hook.result.current.session?.id).toBe(sessionId))
  await act(() => hook.result.current.edit(originalUser.id, editedUser.markdown))
  expect(gateway.edit).toHaveBeenCalledWith(originalUser.id, editedUser.markdown)
  expect(activeLineage(hook.result.current.session).map((item) => item.id)).toEqual([editedUser.id, editedAnswer.id])
  expect(hook.result.current.session?.messages).toHaveLength(4)
  await act(() => hook.result.current.switchVersion(originalUser.id))
  expect(activeLineage(hook.result.current.session).map((item) => item.id)).toEqual([originalUser.id, originalAnswer.id])
  expect(hook.result.current.session?.messages).toHaveLength(4)
})
