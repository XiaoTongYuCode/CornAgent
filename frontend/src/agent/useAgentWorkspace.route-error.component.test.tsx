import { act, renderHook, waitFor } from '@testing-library/react'

import type { HttpAgentGateway } from './gateway'
import type { AgentSessionDetail } from './types'
import { useAgentWorkspace } from './useAgentWorkspace'

const session = (id: string, nextBefore: string | null = null): AgentSessionDetail => ({
  id,
  title: id,
  context: {},
  activeLeafMessageId: null,
  createdAt: '2026-09-04T00:00:00Z',
  updatedAt: '2026-09-04T00:00:00Z',
  messages: [],
  activeRun: null,
  nextBefore,
})

function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (reason: Error) => void
  const promise = new Promise<T>((complete, fail) => {
    resolve = complete
    reject = fail
  })
  return { promise, reject, resolve }
}

it('ignores an older-message error that arrives after routing to another session', async () => {
  const sessionA = session('session-a', 'older')
  const sessionB = session('session-b')
  const pendingOlder = deferred<AgentSessionDetail>()
  const pendingSessionB = new Promise<AgentSessionDetail>(() => undefined)
  const gateway = {
    status: vi.fn(async () => ({ available: true })),
    listSessions: vi.fn(async () => ({ data: [sessionA, sessionB], nextCursor: null })),
    getSession: vi.fn((id: string, before?: string) => {
      if (before) return pendingOlder.promise
      return id === sessionA.id ? Promise.resolve(sessionA) : pendingSessionB
    }),
  } as unknown as HttpAgentGateway
  const hook = renderHook(
    ({ routeSessionId }: { routeSessionId: string }) => useAgentWorkspace(gateway, 'principal-1', routeSessionId),
    { initialProps: { routeSessionId: sessionA.id } },
  )

  await waitFor(() => expect(hook.result.current.session?.id).toBe(sessionA.id))
  let loadOlder!: Promise<void>
  act(() => { loadOlder = hook.result.current.loadOlder() })
  await waitFor(() => expect(gateway.getSession).toHaveBeenCalledWith(sessionA.id, 'older'))

  hook.rerender({ routeSessionId: sessionB.id })
  await waitFor(() => expect(gateway.getSession).toHaveBeenCalledWith(sessionB.id))

  await act(async () => {
    pendingOlder.reject(new Error('旧会话错误'))
    await loadOlder
  })

  expect(hook.result.current.error).toBeNull()
})

it('ignores a session-list error that arrives after routing to another session', async () => {
  const sessionA = session('session-a')
  const sessionB = session('session-b')
  const pendingMore = deferred<{ data: AgentSessionDetail[]; nextCursor: null }>()
  const pendingStatus = deferred<{ available: boolean }>()
  const listSessions = vi.fn((cursor?: string | null) => cursor
    ? pendingMore.promise
    : Promise.resolve({ data: [sessionA, sessionB], nextCursor: 'older-sessions' }))
  const status = vi.fn()
    .mockResolvedValueOnce({ available: true })
    .mockReturnValueOnce(pendingStatus.promise)
  const gateway = {
    status,
    listSessions,
    getSession: vi.fn(async () => sessionA),
  } as unknown as HttpAgentGateway
  const hook = renderHook(
    ({ routeSessionId }: { routeSessionId: string }) => useAgentWorkspace(gateway, 'principal-1', routeSessionId),
    { initialProps: { routeSessionId: sessionA.id } },
  )

  await waitFor(() => expect(hook.result.current.sessionsNextCursor).toBe('older-sessions'))
  let loadMore!: Promise<void>
  act(() => { loadMore = hook.result.current.loadMoreSessions() })
  await waitFor(() => expect(listSessions).toHaveBeenCalledWith('older-sessions'))

  hook.rerender({ routeSessionId: sessionB.id })
  await waitFor(() => expect(status).toHaveBeenCalledTimes(2))

  await act(async () => {
    pendingMore.reject(new Error('旧列表错误'))
    await loadMore
  })

  expect(hook.result.current.error).toBeNull()
})
