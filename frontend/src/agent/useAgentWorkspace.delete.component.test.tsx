import { act, renderHook, waitFor } from '@testing-library/react'
import type { HttpAgentGateway } from './gateway'
import type { AgentSessionDetail } from './types'
import { useAgentWorkspace } from './useAgentWorkspace'

const NOW = '2026-09-03T00:00:00Z'

function session(id: string): AgentSessionDetail {
  return {
    id,
    title: id,
    context: {},
    activeLeafMessageId: null,
    createdAt: NOW,
    updatedAt: NOW,
    messages: [],
    activeRun: null,
    nextBefore: null,
  }
}

function deferred() {
  let resolve!: () => void
  const promise = new Promise<void>((complete) => { resolve = complete })
  return { promise, resolve }
}

it('removes a deleted Agent session from the current workspace', async () => {
  const current = session('session-delete')
  const gateway = {
    status: vi.fn(async () => ({ available: true })),
    listSessions: vi.fn(async () => ({ data: [current], nextCursor: null })),
    getSession: vi.fn(async () => current),
    deleteSession: vi.fn(async () => ({ id: current.id, deleted: true })),
  } as unknown as HttpAgentGateway
  const hook = renderHook(() => useAgentWorkspace(gateway, 'principal-1', current.id))

  await waitFor(() => expect(hook.result.current.session?.id).toBe(current.id))
  await act(() => hook.result.current.deleteSession(current.id))

  expect(gateway.deleteSession).toHaveBeenCalledWith(current.id)
  expect(hook.result.current.session).toBeNull()
  expect(hook.result.current.sessions).toEqual([])
  expect(hook.result.current.busy).toBe(false)
})

it('does not clear a newer routed session when an old delete finishes late', async () => {
  const oldSession = session('session-old')
  const nextSession = session('session-next')
  const pendingDelete = deferred()
  const gateway = {
    status: vi.fn(async () => ({ available: true })),
    listSessions: vi.fn(async () => ({ data: [oldSession, nextSession], nextCursor: null })),
    getSession: vi.fn(async (id: string) => id === oldSession.id ? oldSession : nextSession),
    deleteSession: vi.fn(() => pendingDelete.promise),
  } as unknown as HttpAgentGateway
  const hook = renderHook(
    ({ routeSessionId }: { routeSessionId: string }) => useAgentWorkspace(gateway, 'principal-1', routeSessionId),
    { initialProps: { routeSessionId: oldSession.id } },
  )

  await waitFor(() => expect(hook.result.current.session?.id).toBe(oldSession.id))
  let deleteOperation!: Promise<void>
  act(() => { deleteOperation = hook.result.current.deleteSession(oldSession.id) })
  hook.rerender({ routeSessionId: nextSession.id })
  await waitFor(() => expect(hook.result.current.session?.id).toBe(nextSession.id))

  await act(async () => {
    pendingDelete.resolve()
    await deleteOperation
  })

  expect(hook.result.current.session?.id).toBe(nextSession.id)
  expect(hook.result.current.sessions.map((item) => item.id)).toEqual([nextSession.id])
  expect(hook.result.current.busy).toBe(false)
})
