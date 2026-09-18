import userEvent from '@testing-library/user-event'
import { I18nProvider, useI18n } from '../i18n'
import { render, screen, waitFor, within } from '@testing-library/react'
import type { ReactNode } from 'react'
import { AgentMessageList } from './AgentMessageList'
import { groupMessageTurns } from './chat/groupMessageTurns'
import { getVisibleAssistantMarkdown } from './chat/projectAgentMessageSections'
import type { AgentMessage, AgentRun, AgentSnapshot } from './types'
import { applyEvent, type AgentWorkspace } from './useAgentWorkspace'

// Keep the real list, memoized rows, content projection, and action controls.
vi.mock('@lobehub/ui/chat', () => ({
  ChatItem: ({
    renderMessage,
    belowMessage,
  }: {
    renderMessage(): ReactNode
    belowMessage?: ReactNode
  }) => (
    <>
      {renderMessage()}
      {belowMessage}
    </>
  ),
  LoadingDots: () => null,
}))
vi.mock('@lobehub/ui/es/Markdown/index', () => ({
  default: ({ children }: { children: ReactNode }) => <span>{children}</span>,
}))
vi.mock('./chat/groupMessageTurns', async (importOriginal) => {
  const original =
    await importOriginal<typeof import('./chat/groupMessageTurns')>()
  return { groupMessageTurns: vi.fn(original.groupMessageTurns) }
})
vi.mock('./chat/projectAgentMessageSections', async (importOriginal) => {
  const original =
    await importOriginal<typeof import('./chat/projectAgentMessageSections')>()
  return { ...original, getVisibleAssistantMarkdown: vi.fn(original.getVisibleAssistantMarkdown) }
})
vi.mock('./hooks/useConversationScroll', async () => {
  const { useRef } = await import('react')
  return {
    useConversationScroll: () => ({
      viewportRef: useRef(null),
      contentRef: useRef(null),
      atBottom: true,
      onScroll: vi.fn(),
      loadOlderWithAnchor: vi.fn(),
      followLatest: vi.fn(),
    }),
  }
})

beforeAll(() => {
  Object.defineProperty(HTMLElement.prototype, 'scrollTo', {
    configurable: true,
    value() {},
  })
  Object.defineProperty(HTMLElement.prototype, 'getAnimations', {
    configurable: true,
    value: () => [],
  })
})
beforeEach(() => {
  vi.clearAllMocks()
  vi.spyOn(window, 'scrollTo').mockImplementation(() => undefined)
})

const NOW = '2026-09-18T00:00:00Z'

function message(index: number): AgentMessage {
  return {
    id: `message-${index}`,
    sessionId: 'session-1',
    role: index % 2 === 0 ? 'assistant' : 'user',
    markdown: `历史消息 ${index}`,
    attachments: [],
    contentParts: [],
    run: null,
    parentMessageId: index === 0 ? null : `message-${index - 1}`,
    versionGroupId: `message-${index}`,
    versionIndex: 1,
    previousVersionId: null,
    nextVersionId: null,
    versionCount: 1,
    supersedesMessageId: null,
    processStartedAt: null,
    processCompletedAt: NOW,
    createdAt: NOW,
    updatedAt: NOW,
  }
}

function workspaceWithHistory(count: number): AgentWorkspace {
  const messages = Array.from({ length: count }, (_, index) => message(index))
  messages.push({
    ...message(count),
    markdown: '当前回答',
  })
  return {
    session: {
      id: 'session-1',
      title: '流式渲染',
      context: {},
      activeLeafMessageId: messages.at(-1)!.id,
      createdAt: NOW,
      updatedAt: NOW,
      inputs: [],
      messages,
      activeRun: null,
      nextBefore: null,
    },
    snapshot: null,
    busy: false,
    loadingOlder: false,
    loadOlder: vi.fn(async () => undefined),
    edit: vi.fn(async () => undefined),
    regenerate: vi.fn(async () => undefined),
    switchVersion: vi.fn(async () => undefined),
  } as unknown as AgentWorkspace
}

function runningSnapshot(workspace: AgentWorkspace): AgentSnapshot {
  const assistant = workspace.session!.messages.at(-1)!
  return {
    run: {
      id: 'run-1',
      sessionId: assistant.sessionId,
      userMessageId: assistant.parentMessageId!,
      assistantMessageId: assistant.id,
      kind: 'create',
      status: 'running',
      streamEpoch: 1,
      nextSequence: 1,
      providerUsage: {},
      errorCode: null,
      errorMessage: null,
      createdAt: NOW,
      updatedAt: NOW,
    },
    draftMarkdown: '',
    reasoningMarkdown: '',
    contentParts: [],
    replace: false,
  }
}

it.each(['delta', 'reasoning_delta'] as const)(
  'updates only the current row for five %s events with 100 historical messages',
  async (event) => {
    let workspace = workspaceWithHistory(100)
    let snapshot: AgentSnapshot | null = runningSnapshot(workspace)
    workspace = { ...workspace, snapshot }
    const view = render(<AgentMessageList workspace={workspace} />)
    const historicalNode = screen.getByText('历史消息 0')
    expect(getVisibleAssistantMarkdown).toHaveBeenCalledTimes(101)
    expect(groupMessageTurns).toHaveBeenCalledOnce()
    vi.mocked(getVisibleAssistantMarkdown).mockClear()
    vi.mocked(groupMessageTurns).mockClear()

    for (let index = 1; index <= 5; index += 1) {
      applyEvent(
        {
          id: String(index),
          event,
          data: { content: '新', part_id: 'stream-part' },
        },
        (update) => {
          snapshot = typeof update === 'function' ? update(snapshot) : update
        },
      )
      workspace = { ...workspace, snapshot }
      view.rerender(<AgentMessageList workspace={workspace} />)
      await waitFor(() =>
        expect(screen.getByText('新'.repeat(index))).toBeVisible(),
      )
      expect(getVisibleAssistantMarkdown).toHaveBeenCalledTimes(index)
    }

    expect(groupMessageTurns).not.toHaveBeenCalled()
    expect(screen.getByText('历史消息 0')).toBe(historicalNode)
    expect(
      vi
        .mocked(getVisibleAssistantMarkdown)
        .mock.calls.every(([parts]) =>
          parts.some((part) => part.id === 'stream-part'),
        ),
    ).toBe(true)
  },
)

it('refreshes historical edit and regenerate controls when a run or busy state changes', () => {
  let workspace = workspaceWithHistory(2)
  const view = render(<AgentMessageList workspace={workspace} />)
  const edit = screen.getByRole('button', { name: '编辑消息' })
  const regenerate = within(
    screen.getByText('历史消息 0').closest('section')!,
  ).getByRole('button', { name: '重新生成' })
  expect(edit).toBeEnabled()
  expect(regenerate).toBeEnabled()

  const run = runningSnapshot(workspace).run
  const setState = (activeRun: AgentRun | null, busy = false) => {
    workspace = {
      ...workspace,
      busy,
      session: { ...workspace.session!, activeRun },
    }
    view.rerender(<AgentMessageList workspace={workspace} />)
  }
  setState(run)
  expect(edit).toBeDisabled()
  expect(regenerate).toBeDisabled()
  setState({ ...run, status: 'completed' })
  expect(edit).toBeEnabled()
  expect(regenerate).toBeEnabled()
  setState(null, true)
  expect(edit).toBeDisabled()
  expect(regenerate).toBeDisabled()
  setState(null)
  expect(edit).toBeEnabled()
  expect(regenerate).toBeEnabled()
  expect(groupMessageTurns).toHaveBeenCalledOnce()
})

it('invalidates cached rows and lineage when historical content or the active branch changes', () => {
  let workspace = workspaceWithHistory(2)
  const view = render(<AgentMessageList workspace={workspace} />)
  workspace = {
    ...workspace,
    session: {
      ...workspace.session!,
      messages: workspace.session!.messages.map((item) =>
        item.id === 'message-0'
          ? { ...item, markdown: '历史内容已更新' }
          : item,
      ),
    },
  }
  view.rerender(<AgentMessageList workspace={workspace} />)
  expect(screen.getByText('历史内容已更新')).toBeVisible()
  expect(screen.queryByText('历史消息 0')).not.toBeInTheDocument()

  const alternative: AgentMessage = {
    ...message(2),
    id: 'alternative',
    markdown: '另一个回答版本',
  }
  workspace = {
    ...workspace,
    session: {
      ...workspace.session!,
      messages: [...workspace.session!.messages, alternative],
    },
  }
  view.rerender(<AgentMessageList workspace={workspace} />)
  expect(screen.getByText('当前回答')).toBeVisible()
  expect(screen.queryByText('另一个回答版本')).not.toBeInTheDocument()
  workspace = {
    ...workspace,
    session: { ...workspace.session!, activeLeafMessageId: alternative.id },
  }
  view.rerender(<AgentMessageList workspace={workspace} />)
  expect(screen.getByText('另一个回答版本')).toBeVisible()
  expect(screen.queryByText('当前回答')).not.toBeInTheDocument()
  expect(screen.getByText('历史内容已更新')).toBeVisible()
})

it('refreshes operation receipts from SSE while keeping historical rows stable', () => {
  let workspace = workspaceWithHistory(2)
  let snapshot: AgentSnapshot | null = runningSnapshot(workspace)
  workspace = { ...workspace, snapshot }
  const view = render(<AgentMessageList workspace={workspace} />)
  vi.mocked(getVisibleAssistantMarkdown).mockClear()
  applyEvent({ id: '1:2', event: 'tool_call', data: {
    id: 'write', kind: 'tool_call', content: 'Saved', metadata: {
      operation_outcome: { state: 'committed', counts: { committed: 1 } },
      changes: [{ resource_id: 'record', resource_type: 'record', title: 'Saved record', action: 'update' }],
    },
  } }, update => { snapshot = typeof update === 'function' ? update(snapshot) : update })
  workspace = { ...workspace, snapshot }
  view.rerender(<AgentMessageList workspace={workspace} />)
  expect(screen.getByText('已提交 1')).toBeVisible()
  expect(getVisibleAssistantMarkdown).toHaveBeenCalledOnce()
})

function LanguageToggle() {
  const { toggleLocale } = useI18n()
  return <button onClick={toggleLocale}>language</button>
}

it('updates localized controls inside memoized historical rows', async () => {
  const workspace = workspaceWithHistory(2)
  render(<I18nProvider><LanguageToggle /><AgentMessageList workspace={workspace} /></I18nProvider>)
  expect(screen.getByRole('button', { name: '编辑消息' })).toBeVisible()
  await userEvent.click(screen.getByRole('button', { name: 'language' }))
  expect(screen.getByRole('button', { name: 'Edit message' })).toBeVisible()
  expect(screen.getByText('历史消息 0')).toBeVisible()
})
