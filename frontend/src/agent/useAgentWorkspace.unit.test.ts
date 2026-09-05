import type { Dispatch, SetStateAction } from 'react'
import { describe, expect, it } from 'vitest'
import { applyEvent } from './useAgentWorkspace'
import type { AgentSnapshot } from './types'

function snapshotState() {
  let snapshot: AgentSnapshot | null = {
    run: {
      id: 'run-1', sessionId: 'session-1', userMessageId: 'user-1', assistantMessageId: 'assistant-1',
      kind: 'create', status: 'running', streamEpoch: 1, nextSequence: 1, providerUsage: {},
      errorCode: null, errorMessage: null, createdAt: '2026-09-03T00:00:00Z', updatedAt: '2026-09-03T00:00:00Z',
    },
    draftMarkdown: '',
    reasoningMarkdown: '',
    contentParts: [],
    replace: false,
  }
  const setSnapshot = ((next: SetStateAction<AgentSnapshot | null>) => {
    snapshot = typeof next === 'function' ? next(snapshot) : next
  }) as Dispatch<SetStateAction<AgentSnapshot | null>>
  return { get: () => snapshot, setSnapshot }
}

describe('applyEvent', () => {
  it('appends compact deltas to stable per-round Markdown parts', () => {
    const state = snapshotState()
    applyEvent({
      id: '1:1', event: 'delta',
      data: { part_id: 'draft-1', content: '检查资料', kind: 'markdown' },
    }, state.setSnapshot)
    expect(state.get()?.contentParts).toEqual([
      { id: 'draft-1', kind: 'markdown', title: undefined, content: '检查资料' },
    ])

    applyEvent({
      id: '1:2', event: 'delta',
      data: {
        part_id: 'draft-1',
        content: '，继续核对',
        part_content: '，继续核对',
        kind: 'markdown',
      },
    }, state.setSnapshot)
    expect(state.get()?.contentParts).toEqual([
      { id: 'draft-1', kind: 'markdown', title: undefined, content: '检查资料，继续核对' },
    ])

    applyEvent({
      id: '1:3', event: 'delta',
      data: { part_id: 'draft-2', content: '最终结论', kind: 'markdown' },
    }, state.setSnapshot)
    expect(state.get()?.draftMarkdown).toBe('检查资料，继续核对最终结论')
    expect(state.get()?.contentParts[1]).toEqual({
      id: 'draft-2', kind: 'markdown', title: undefined, content: '最终结论',
    })
  })
})

it('upserts child progress and updates persistent waiting status without replacing content', () => {
  const state = snapshotState()
  for (const status of ['queued', 'running', 'completed']) {
    applyEvent({ id: '1:2', event: 'tool_call', data: {
      id: 'child-1', kind: 'tool_call', content: status,
      metadata: { subagent: true, task_id: 'child-1', status },
    } }, state.setSnapshot)
  }
  expect(state.get()?.contentParts).toHaveLength(1)
  expect(state.get()?.contentParts[0].content).toBe('completed')
  applyEvent({ id: '1:3', event: 'session', data: { run: {
    id: 'run-1', session_id: 'session-1', user_message_id: 'user-1', assistant_message_id: 'assistant-1',
    status: 'waiting_for_subagents', kind: 'create', stream_epoch: 1, next_sequence: 4,
    provider_usage: {}, error_code: null, error_message: null, created_at: '', updated_at: '',
  } } }, state.setSnapshot)
  expect(state.get()?.run.status).toBe('waiting_for_subagents')
  expect(state.get()?.contentParts).toHaveLength(1)
})
