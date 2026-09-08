import { act, renderHook, waitFor } from '@testing-library/react'
import type { HttpAgentGateway } from './gateway'
import type { AgentMessage, AgentRun, AgentSessionDetail, AgentSseEvent } from './types'
import { useAgentWorkspace } from './useAgentWorkspace'

const NOW = '2026-09-02T00:00:00Z'

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((complete) => {
    resolve = complete
  })
  return { promise, resolve }
}

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

function session(id: string, activeRun: AgentRun): AgentSessionDetail {
  const userMessage = message(activeRun.userMessageId, id, 'user', null)
  const assistantMessage = {
    ...message(activeRun.assistantMessageId, id, 'assistant', userMessage.id),
    markdown: '',
    run: activeRun,
    processCompletedAt: null,
  }
  return {
    id,
    title: id,
    context: {},
    activeLeafMessageId: activeRun.assistantMessageId,
    createdAt: NOW,
    updatedAt: NOW,
    messages: [userMessage, assistantMessage],
    activeRun,
    nextBefore: null,
  }
}

function snapshotEvent(activeRun: AgentRun): AgentSseEvent {
  return {
    id: '1:0',
    event: 'snapshot',
    data: {
      run: {
        id: activeRun.id,
        session_id: activeRun.sessionId,
        user_message_id: activeRun.userMessageId,
        assistant_message_id: activeRun.assistantMessageId,
        kind: activeRun.kind,
        status: activeRun.status,
        stream_epoch: activeRun.streamEpoch,
        next_sequence: activeRun.nextSequence,
        provider_usage: {},
        error_code: null,
        error_message: null,
        created_at: NOW,
        updated_at: NOW,
      },
      draft_markdown: '',
      reasoning_markdown: '',
      content_parts: [],
      replace: true,
    },
  }
}

it('stops probing Agent status after the authenticated gateway disconnects', async () => {
  const status = vi.fn(async () => ({ available: true }))
  const gateway = { status, listSessions: vi.fn(async () => ({ data: [], nextCursor: null })) } as unknown as HttpAgentGateway
  const hook = renderHook(
    ({ authenticated }: { authenticated: boolean }) => useAgentWorkspace(
      authenticated ? gateway : null,
      authenticated ? 'principal-1' : 'anonymous',
    ),
    { initialProps: { authenticated: true } },
  )

  await waitFor(() => expect(status).toHaveBeenCalledTimes(1))
  hook.rerender({ authenticated: false })
  await waitFor(() => expect(hook.result.current.available).toBe(false))

  expect(status).toHaveBeenCalledTimes(1)
})

it('drops the previous Run snapshot before loading a routed session', async () => {
  const runA = run('run-a', 'session-a')
  const runB = run('run-b', 'session-b')
  const sessions = {
    'session-a': session('session-a', runA),
    'session-b': session('session-b', runB),
  }
  const streamCalls: string[] = []
  const gateway = {
    status: vi.fn(async () => ({ available: true })),
    listSessions: vi.fn(async () => ({ data: Object.values(sessions), nextCursor: null })),
    getSession: vi.fn(async (id: keyof typeof sessions) => sessions[id]),
    stream: async function* (runId: string, signal: AbortSignal) {
      streamCalls.push(runId)
      yield snapshotEvent(runId === runA.id ? runA : runB)
      await new Promise<void>((resolve) => {
        signal.addEventListener('abort', () => resolve(), { once: true })
      })
    },
  } as unknown as HttpAgentGateway

  const hook = renderHook(
    ({ routeSessionId }: { routeSessionId: string }) => (
      useAgentWorkspace(gateway, 'principal-1', routeSessionId)
    ),
    { initialProps: { routeSessionId: 'session-a' } },
  )

  await waitFor(() => expect(hook.result.current.snapshot?.run.id).toBe('run-a'))
  hook.rerender({ routeSessionId: 'session-b' })

  await waitFor(() => expect(hook.result.current.session?.id).toBe('session-b'))
  await waitFor(() => expect(streamCalls).toContain('run-b'))
  expect(streamCalls.at(-1)).toBe('run-b')
})

it('ignores a stale routed-session response after navigation', async () => {
  const runA = run('run-a', 'session-a')
  const runB = run('run-b', 'session-b')
  const sessionA = session('session-a', runA)
  const sessionB = session('session-b', runB)
  let resolveSessionA!: (detail: AgentSessionDetail) => void
  const pendingSessionA = new Promise<AgentSessionDetail>((resolve) => {
    resolveSessionA = resolve
  })
  const getSession = vi.fn((id: string) => (
    id === sessionA.id ? pendingSessionA : Promise.resolve(sessionB)
  ))
  const gateway = {
    status: vi.fn(async () => ({ available: true })),
    listSessions: vi.fn(async () => ({ data: [sessionA, sessionB], nextCursor: null })),
    getSession,
    stream: async function* (_runId: string, signal: AbortSignal) {
      await new Promise<void>((resolve) => {
        signal.addEventListener('abort', () => resolve(), { once: true })
      })
      if (!signal.aborted) yield snapshotEvent(runB)
    },
  } as unknown as HttpAgentGateway

  const hook = renderHook(
    ({ routeSessionId }: { routeSessionId: string }) => (
      useAgentWorkspace(gateway, 'principal-1', routeSessionId)
    ),
    { initialProps: { routeSessionId: sessionA.id } },
  )

  await waitFor(() => expect(getSession).toHaveBeenCalledWith(sessionA.id))
  hook.rerender({ routeSessionId: sessionB.id })
  await waitFor(() => expect(hook.result.current.session?.id).toBe(sessionB.id))

  await act(async () => {
    resolveSessionA(sessionA)
    await pendingSessionA
  })

  expect(hook.result.current.session?.id).toBe(sessionB.id)
})

it('ignores a regenerate result after navigation to another session', async () => {
  const runA = run('run-a', 'session-a')
  const runB = run('run-b', 'session-b')
  const regeneratedRunA = { ...run('run-a-regenerated', 'session-a'), kind: 'regenerate' as const }
  const sessionA = session('session-a', runA)
  const sessionB = session('session-b', runB)
  const pendingRegenerate = deferred<AgentRun>()
  const streamCalls: string[] = []
  const gateway = {
    status: vi.fn(async () => ({ available: true })),
    listSessions: vi.fn(async () => ({ data: [sessionA, sessionB], nextCursor: null })),
    getSession: vi.fn(async (id: string) => (id === sessionA.id ? sessionA : sessionB)),
    regenerate: vi.fn(() => pendingRegenerate.promise),
    stream: async function* (runId: string, signal: AbortSignal) {
      streamCalls.push(runId)
      yield snapshotEvent(runId === runA.id ? runA : runB)
      await new Promise<void>((resolve) => {
        signal.addEventListener('abort', () => resolve(), { once: true })
      })
    },
  } as unknown as HttpAgentGateway
  const hook = renderHook(
    ({ routeSessionId }: { routeSessionId: string }) => (
      useAgentWorkspace(gateway, 'principal-1', routeSessionId)
    ),
    { initialProps: { routeSessionId: sessionA.id } },
  )

  await waitFor(() => expect(hook.result.current.session?.id).toBe(sessionA.id))
  let regenerateOperation!: Promise<void>
  act(() => {
    regenerateOperation = hook.result.current.regenerate('message-a')
  })
  hook.rerender({ routeSessionId: sessionB.id })
  await waitFor(() => expect(hook.result.current.session?.id).toBe(sessionB.id))

  await act(async () => {
    pendingRegenerate.resolve(regeneratedRunA)
    await regenerateOperation
  })

  expect(hook.result.current.session?.id).toBe(sessionB.id)
  expect(hook.result.current.session?.activeRun?.id).toBe(runB.id)
  expect(hook.result.current.busy).toBe(false)
  expect(streamCalls).not.toContain(regeneratedRunA.id)
})

it('keeps the newest regenerate result when requests finish out of order', async () => {
  const currentRun = run('run-current', 'session-a')
  const firstRun = { ...run('run-first', 'session-a'), kind: 'regenerate' as const }
  const secondRun = { ...run('run-second', 'session-a'), kind: 'regenerate' as const }
  const currentSession = session('session-a', currentRun)
  const firstRegenerate = deferred<AgentRun>()
  const secondRegenerate = deferred<AgentRun>()
  const gateway = {
    status: vi.fn(async () => ({ available: true })),
    listSessions: vi.fn(async () => ({ data: [currentSession], nextCursor: null })),
    getSession: vi.fn(async () => session('session-a', secondRun)),
    regenerate: vi.fn()
      .mockReturnValueOnce(firstRegenerate.promise)
      .mockReturnValueOnce(secondRegenerate.promise),
    stream: async function* (_runId: string, signal: AbortSignal) {
      await new Promise<void>((resolve) => {
        signal.addEventListener('abort', () => resolve(), { once: true })
      })
      if (!signal.aborted) yield snapshotEvent(currentRun)
    },
  } as unknown as HttpAgentGateway
  const hook = renderHook(() => useAgentWorkspace(gateway, 'principal-1', currentSession.id))

  await waitFor(() => expect(hook.result.current.session?.id).toBe(currentSession.id))
  let firstOperation!: Promise<void>
  let secondOperation!: Promise<void>
  act(() => {
    firstOperation = hook.result.current.regenerate('message-first')
    secondOperation = hook.result.current.regenerate('message-second')
  })

  await act(async () => {
    secondRegenerate.resolve(secondRun)
    await secondOperation
  })
  expect(hook.result.current.session?.activeRun?.id).toBe(secondRun.id)

  await act(async () => {
    firstRegenerate.resolve(firstRun)
    await firstOperation
  })
  expect(hook.result.current.session?.activeRun?.id).toBe(secondRun.id)
})

it('ignores a switch-version result after the principal changes', async () => {
  const sessionId = 'session-shared-id'
  const oldSession = {
    ...session(sessionId, run('run-old-principal', sessionId)),
    title: 'old principal',
    activeLeafMessageId: null,
    activeRun: null,
  }
  const newSession = {
    ...oldSession,
    title: 'new principal',
  }
  const staleSwitchedSession = {
    ...oldSession,
    title: 'stale switched session',
  }
  const pendingSwitch = deferred<AgentSessionDetail>()
  let activePrincipal = 'principal-old'
  const gateway = {
    status: vi.fn(async () => ({ available: true })),
    listSessions: vi.fn(async () => ({
      data: [activePrincipal === 'principal-old' ? oldSession : newSession],
      nextCursor: null,
    })),
    getSession: vi.fn(async () => (activePrincipal === 'principal-old' ? oldSession : newSession)),
    switchVersion: vi.fn(() => pendingSwitch.promise),
  } as unknown as HttpAgentGateway
  const hook = renderHook(
    ({ principalKey }: { principalKey: string }) => useAgentWorkspace(gateway, principalKey, sessionId),
    { initialProps: { principalKey: activePrincipal } },
  )

  await waitFor(() => expect(hook.result.current.session?.title).toBe(oldSession.title))
  let switchOperation!: Promise<void>
  act(() => {
    switchOperation = hook.result.current.switchVersion('message-old-principal')
  })
  activePrincipal = 'principal-new'
  hook.rerender({ principalKey: activePrincipal })
  await waitFor(() => expect(hook.result.current.session?.title).toBe(newSession.title))

  await act(async () => {
    pendingSwitch.resolve(staleSwitchedSession)
    await switchOperation
  })

  expect(hook.result.current.session?.title).toBe(newSession.title)
  expect(hook.result.current.busy).toBe(false)
})

it('ignores a stale session list after the principal changes', async () => {
  const oldSession = session('session-old-principal', run('run-old-principal', 'session-old-principal'))
  const newSession = session('session-new-principal', run('run-new-principal', 'session-new-principal'))
  let resolveOldList!: (page: { data: AgentSessionDetail[]; nextCursor: null }) => void
  const pendingOldList = new Promise<{ data: AgentSessionDetail[]; nextCursor: null }>((resolve) => {
    resolveOldList = resolve
  })
  const listSessions = vi.fn()
    .mockReturnValueOnce(pendingOldList)
    .mockResolvedValue({ data: [newSession], nextCursor: null })
  const gateway = {
    status: vi.fn(async () => ({ available: true })),
    listSessions,
    getSession: vi.fn(async () => newSession),
  } as unknown as HttpAgentGateway
  const hook = renderHook(
    ({ principalKey }: { principalKey: string }) => useAgentWorkspace(gateway, principalKey),
    { initialProps: { principalKey: 'principal-old' } },
  )

  await waitFor(() => expect(listSessions).toHaveBeenCalledTimes(1))
  hook.rerender({ principalKey: 'principal-new' })
  await waitFor(() => expect(hook.result.current.sessions.map((item) => item.id)).toEqual([newSession.id]))

  await act(async () => {
    resolveOldList({ data: [oldSession], nextCursor: null })
    await pendingOldList
  })

  expect(hook.result.current.sessions.map((item) => item.id)).toEqual([newSession.id])
})

it('loads older session messages through the server cursor', async () => {
  const activeRun = run('run-paged', 'session-paged')
  const current = {
    ...session('session-paged', activeRun),
    activeLeafMessageId: null,
    activeRun: null,
    nextBefore: 'message-cursor',
  }
  const older = { ...current, nextBefore: null }
  const getSession = vi.fn(async (_id: string, before?: string) => (
    before ? older : current
  ))
  const gateway = {
    status: vi.fn(async () => ({ available: true })),
    listSessions: vi.fn(async () => ({ data: [current], nextCursor: null })),
    getSession,
  } as unknown as HttpAgentGateway
  const hook = renderHook(() => useAgentWorkspace(gateway, 'principal-1', current.id))

  await waitFor(() => expect(hook.result.current.session?.nextBefore).toBe('message-cursor'))
  await act(() => hook.result.current.loadOlder())

  expect(getSession).toHaveBeenLastCalledWith(current.id, 'message-cursor')
  expect(hook.result.current.session?.nextBefore).toBeNull()
})

it('loads and merges older session pages', async () => {
  const first = session('session-new', run('run-new', 'session-new'))
  const older = session('session-old', run('run-old', 'session-old'))
  const listSessions = vi.fn(async (cursor?: string | null) => (
    cursor
      ? { data: [older], nextCursor: null }
      : { data: [first], nextCursor: 'older-sessions' }
  ))
  const gateway = {
    status: vi.fn(async () => ({ available: true })),
    listSessions,
    getSession: vi.fn(async () => first),
  } as unknown as HttpAgentGateway
  const hook = renderHook(() => useAgentWorkspace(gateway, 'principal-1'))

  await waitFor(() => expect(hook.result.current.sessionsNextCursor).toBe('older-sessions'))
  await act(() => hook.result.current.loadMoreSessions())

  expect(listSessions).toHaveBeenLastCalledWith('older-sessions')
  expect(hook.result.current.sessions.map((item) => item.id)).toEqual([
    first.id,
    older.id,
  ])
  expect(hook.result.current.sessionsNextCursor).toBeNull()
})

it('keeps authoritative detail loading and deduplicates sends while the sidebar refresh runs in background', async () => {
  const activeRun = run('created', 'created-session')
  const detail = session(activeRun.sessionId, activeRun)
  const pendingDetail = deferred<AgentSessionDetail>()
  const pendingList = deferred<{ data: AgentSessionDetail[]; nextCursor: null }>()
  const status = vi.fn(async () => ({ available: true }))
  const startSession = vi.fn(async () => ({ session: detail, run: activeRun }))
  const gateway = {
    status, startSession,
    listSessions: vi.fn().mockResolvedValueOnce({ data: [], nextCursor: null }).mockReturnValue(pendingList.promise),
    getSession: vi.fn(() => pendingDetail.promise),
  } as unknown as HttpAgentGateway
  const hook = renderHook(() => useAgentWorkspace(gateway, 'principal-1', null))
  await waitFor(() => expect(hook.result.current.available).toBe(true))
  let first!: Promise<string>
  let duplicate!: Promise<string>
  act(() => {
    first = hook.result.current.ask('问题', ['file-1'])
    duplicate = hook.result.current.ask('问题', ['file-1'])
  })
  await waitFor(() => expect(gateway.getSession).toHaveBeenCalled())
  expect(status).toHaveBeenCalledTimes(1)
  expect(startSession).toHaveBeenCalledTimes(1)
  expect(startSession.mock.calls[0]).toEqual(['问题', ['file-1'], expect.any(String), expect.any(AbortSignal)])
  expect(hook.result.current.session).toBeNull()
  expect(hook.result.current.busy).toBe(true)
  await act(async () => {
    pendingDetail.resolve(detail)
    expect(await first).toBe(detail.id)
    expect(await duplicate).toBe(detail.id)
  })
  expect(hook.result.current.session?.messages).toEqual(detail.messages)
  expect(hook.result.current.busy).toBe(false)
  await act(async () => { pendingList.resolve({ data: [detail], nextCursor: null }) })
})

it.each([false, null])('rechecks availability %s before admitting a send', async (initial) => {
  const activeRun = run('new', 'session-new')
  const detail = session(activeRun.sessionId, activeRun)
  const initialStatus = deferred<{ available: boolean }>()
  const status = vi.fn().mockReturnValueOnce(initial === null ? initialStatus.promise : Promise.resolve({ available: initial }))
    .mockResolvedValue({ available: false })
  const startSession = vi.fn()
  const gateway = { status, startSession, listSessions: vi.fn(async () => ({ data: [detail], nextCursor: null })) } as unknown as HttpAgentGateway
  const hook = renderHook(() => useAgentWorkspace(gateway, 'principal-1', null))
  await waitFor(() => expect(status).toHaveBeenCalledTimes(1))
  if (initial === false) await waitFor(() => expect(hook.result.current.available).toBe(false))
  await act(async () => { await expect(hook.result.current.ask('问题')).rejects.toThrow('尚未配置') })
  expect(status).toHaveBeenCalledTimes(2)
  expect(startSession).not.toHaveBeenCalled()
})

it('propagates server admission failure even with cached availability', async () => {
  const gateway = {
    status: vi.fn(async () => ({ available: true })),
    listSessions: vi.fn(async () => ({ data: [], nextCursor: null })),
    startSession: vi.fn(async () => { throw new Error('server admission rejected') }),
    getSession: vi.fn(),
  } as unknown as HttpAgentGateway
  const hook = renderHook(() => useAgentWorkspace(gateway, 'principal-1', null))
  await waitFor(() => expect(hook.result.current.available).toBe(true))
  await act(async () => { await expect(hook.result.current.ask('问题')).rejects.toThrow('server admission rejected') })
  expect(hook.result.current.busy).toBe(false)
  expect(hook.result.current.session).toBeNull()
  expect(gateway.getSession).not.toHaveBeenCalled()
})

it('stops a stale availability check from creating a Run after navigation', async () => {
  const pending = deferred<{ available: boolean }>()
  const gateway = {
    status: vi.fn().mockResolvedValueOnce({ available: false }).mockReturnValueOnce(pending.promise).mockResolvedValue({ available: false }),
    startSession: vi.fn(),
  } as unknown as HttpAgentGateway
  const hook = renderHook(({ route }: { route: string | null }) => useAgentWorkspace(gateway, 'principal-1', route), { initialProps: { route: null as string | null } })
  await waitFor(() => expect(hook.result.current.available).toBe(false))
  let outcome!: Promise<unknown>
  act(() => { outcome = hook.result.current.ask('问题').catch((error: Error) => error.name) })
  hook.rerender({ route: 'different-session' })
  await act(async () => { pending.resolve({ available: true }); expect(await outcome).toBe('AbortError') })
  expect(gateway.startSession).not.toHaveBeenCalled()
  expect(hook.result.current.available).toBe(false)
})


it('reports a sidebar refresh failure without rejecting a successfully created Run', async () => {
  const activeRun = run('new', 'session-new')
  const detail = session(activeRun.sessionId, activeRun)
  const gateway = {
    status: vi.fn(async () => ({ available: true })),
    listSessions: vi.fn().mockResolvedValueOnce({ data: [], nextCursor: null }).mockRejectedValue(new Error('list failed')),
    startSession: vi.fn(async () => ({ session: detail, run: activeRun })),
    getSession: vi.fn(async () => detail),
  } as unknown as HttpAgentGateway
  const hook = renderHook(() => useAgentWorkspace(gateway, 'principal-1', null))
  await waitFor(() => expect(hook.result.current.available).toBe(true))
  await act(async () => { expect(await hook.result.current.ask('问题')).toBe(detail.id) })
  expect(hook.result.current.session?.activeRun?.id).toBe(activeRun.id)
  expect(hook.result.current.busy).toBe(false)
  expect(hook.result.current.error).toBe('对话历史刷新失败。')
})

it('discards a created Run response after the principal changes', async () => {
  const activeRun = run('new', 'session-new')
  const detail = session(activeRun.sessionId, activeRun)
  const pending = deferred<{ session: AgentSessionDetail; run: AgentRun }>()
  const gateway = {
    status: vi.fn(async () => ({ available: true })),
    listSessions: vi.fn(async () => ({ data: [], nextCursor: null })),
    startSession: vi.fn(() => pending.promise),
    getSession: vi.fn(),
  } as unknown as HttpAgentGateway
  const hook = renderHook(({ principal }: { principal: string }) => useAgentWorkspace(gateway, principal, null), { initialProps: { principal: 'old' } })
  await waitFor(() => expect(hook.result.current.available).toBe(true))
  let outcome!: Promise<unknown>
  act(() => { outcome = hook.result.current.ask('问题').catch((error: Error) => error.name) })
  hook.rerender({ principal: 'new' })
  await act(async () => { pending.resolve({ session: detail, run: activeRun }); expect(await outcome).toBe('AbortError') })
  expect(gateway.getSession).not.toHaveBeenCalled()
  expect(hook.result.current.session).toBeNull()
  expect(hook.result.current.busy).toBe(false)
})
