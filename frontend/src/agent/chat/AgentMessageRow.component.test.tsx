import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import type { AgentMessage, AgentRun } from '../types'
import type { AgentWorkspace } from '../useAgentWorkspace'
import { AgentMessageRow } from './AgentMessageRow'

const NOW = '2026-09-02T00:00:00Z'

function assistantMessage(contentParts: AgentMessage['contentParts']): AgentMessage {
  return {
    id: 'message-assistant',
    sessionId: 'session-1',
    role: 'assistant',
    markdown: contentParts
      .filter((part) => part.kind === 'markdown')
      .map((part) => part.content)
      .join(''),
    attachments: [],
    contentParts,
    run: null,
    parentMessageId: 'message-user',
    versionGroupId: 'message-assistant',
    versionIndex: 1,
    previousVersionId: null,
    nextVersionId: null,
    versionCount: 1,
    supersedesMessageId: null,
    processStartedAt: NOW,
    processCompletedAt: NOW,
    createdAt: NOW,
    updatedAt: NOW,
  }
}

function assistantWorkspace(): AgentWorkspace {
  return {
    snapshot: null,
    session: null,
    regenerate: vi.fn(async () => undefined),
    switchVersion: vi.fn(async () => undefined),
  } as unknown as AgentWorkspace
}

it('marks a cancelled partial answer as incomplete', () => {
  const run: AgentRun = {
    id: 'run-cancelled',
    sessionId: 'session-1',
    userMessageId: 'message-user',
    assistantMessageId: 'message-assistant',
    kind: 'create',
    status: 'cancelled',
    streamEpoch: 1,
    nextSequence: 2,
    providerUsage: {},
    errorCode: null,
    errorMessage: null,
    createdAt: NOW,
    updatedAt: NOW,
  }
  const message: AgentMessage = {
    id: run.assistantMessageId,
    sessionId: run.sessionId,
    role: 'assistant',
    markdown: '尚未生成完整的候选人分析。',
    attachments: [],
    contentParts: [],
    run,
    parentMessageId: run.userMessageId,
    versionGroupId: run.assistantMessageId,
    versionIndex: 1,
    previousVersionId: null,
    nextVersionId: null,
    versionCount: 1,
    supersedesMessageId: null,
    processStartedAt: NOW,
    processCompletedAt: NOW,
    createdAt: NOW,
    updatedAt: NOW,
  }
  const workspace = {
    snapshot: null,
    session: null,
    regenerate: vi.fn(async () => undefined),
    switchVersion: vi.fn(async () => undefined),
  } as unknown as AgentWorkspace

  render(<AgentMessageRow message={message} runActive={false} workspace={workspace} />)

  expect(screen.getByRole('alert')).toHaveTextContent('本次生成未完成（已取消）')
  expect(screen.getByRole('alert')).toHaveTextContent('以上内容可能不完整')
})

it('renders authenticated historical files and opens image preview or PDF', async () => {
  const message: AgentMessage = {
    id: 'message-user',
    sessionId: 'session-1',
    role: 'user',
    markdown: '请比较这两张图',
    attachments: [
      {
        fileId: 'file-a', filename: 'a.png', mimeType: 'image/png', sizeBytes: 12,
        contentUrl: '/api/v1/files/file-a/content',
        scope: 'session', mediaKind: 'image', inspectionStatus: 'validated',
        extractionStatus: 'not_requested',
      },
      {
        fileId: 'file-b', filename: 'brief.pdf', mimeType: 'application/pdf', sizeBytes: 18,
        contentUrl: '/api/v1/files/file-b/content',
        scope: 'session', mediaKind: 'document', inspectionStatus: 'validated',
        extractionStatus: 'ready',
      },
    ],
    contentParts: [],
    run: null,
    parentMessageId: null,
    versionGroupId: 'message-user',
    versionIndex: 1,
    previousVersionId: null,
    nextVersionId: null,
    versionCount: 1,
    supersedesMessageId: null,
    processStartedAt: null,
    processCompletedAt: null,
    createdAt: NOW,
    updatedAt: NOW,
  }
  const workspace = {
    snapshot: null,
    session: null,
    regenerate: vi.fn(async () => undefined),
    switchVersion: vi.fn(async () => undefined),
  } as unknown as AgentWorkspace

  render(<AgentMessageRow message={message} runActive={false} workspace={workspace} />)

  expect(screen.getByRole('img')).toHaveAttribute('src', '/api/v1/files/file-a/content')
  expect(screen.getByRole('link', { name: '打开 brief.pdf' })).toHaveAttribute(
    'href',
    '/api/v1/files/file-b/content',
  )
  await userEvent.click(screen.getByRole('button', { name: '预览 a.png' }))
  expect(screen.getByRole('dialog', { name: '预览 a.png' })).toBeInTheDocument()
  await userEvent.keyboard('{Escape}')
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
})

it('keeps a static processed heading for a body-only answer with process timing', () => {
  render(
    <AgentMessageRow
      message={assistantMessage([
        { id: 'body-1', kind: 'markdown', content: '第一段。\n\n第二段。' },
      ])}
      runActive={false}
      workspace={assistantWorkspace()}
    />,
  )

  expect(screen.getByText('第一段。')).toBeInTheDocument()
  expect(screen.getByText('第二段。')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: /^已处理/u })).toBeDisabled()
})

it('keeps a completed process expanded when no renderable answer follows it', async () => {
  render(<AgentMessageRow
    message={assistantMessage([
      { id: 'tool-1', kind: 'tool_call', title: '读取附件', content: '已读取。' },
      { id: 'body-1', kind: 'markdown', content: '  \n ' },
    ])}
    runActive={false}
    workspace={assistantWorkspace()}
  />)
  const toggle = screen.getByRole('button', { name: /^已处理/u })
  expect(toggle).toHaveAttribute('aria-expanded', 'true')
  expect(toggle).toBeDisabled()
  expect(screen.getByRole('button', { name: '读取附件' })).toBeInTheDocument()
  await userEvent.click(toggle)
  expect(toggle).toHaveAttribute('aria-expanded', 'true')
})

it('allows process collapse only while a rendered answer is present', () => {
  const workspace = assistantWorkspace()
  const process: AgentMessage['contentParts'] = [
    { id: 'tool-1', kind: 'tool_call', title: '读取附件', content: '已读取。' },
  ]
  const renderRow = (parts: AgentMessage['contentParts']) => <AgentMessageRow
    message={assistantMessage(parts)} runActive={false} workspace={workspace}
  />
  const { rerender } = render(renderRow(process))
  const toggle = screen.getByRole('button', { name: /^已处理/u })
  expect(toggle).toBeDisabled()
  rerender(renderRow([...process, { id: 'body-1', kind: 'markdown', content: '附件摘要。' }]))
  expect(toggle).toBeEnabled()
  expect(toggle).toHaveAttribute('aria-expanded', 'false')
  expect(screen.getByText('附件摘要。')).toBeInTheDocument()
  rerender(renderRow(process))
  expect(toggle).toBeDisabled()
  expect(toggle).toHaveAttribute('aria-expanded', 'true')
})

it('keeps only the latest body visible and collapses again at a new body boundary', async () => {
  const workspace = assistantWorkspace()
  const initialParts: AgentMessage['contentParts'] = [
    { id: 'body-1', kind: 'markdown', content: '先搜索现有公司。' },
    { id: 'tool-1', kind: 'tool_call', title: '搜索记录', content: '找到 0 条记录。' },
    { id: 'body-2', kind: 'markdown', content: '公司已创建。' },
  ]
  const { rerender } = render(
    <AgentMessageRow
      message={assistantMessage(initialParts)}
      runActive={false}
      workspace={workspace}
    />,
  )

  const processedToggle = screen.getByRole('button', { name: /^已处理/u })
  expect(processedToggle).toHaveAttribute('aria-expanded', 'false')
  expect(screen.getByText('公司已创建。')).toBeInTheDocument()
  expect(screen.queryByText('先搜索现有公司。')).not.toBeInTheDocument()

  await userEvent.click(processedToggle)
  expect(await screen.findByText('先搜索现有公司。')).toBeInTheDocument()

  rerender(
    <AgentMessageRow
      message={assistantMessage([
        ...initialParts.slice(0, 2),
        { id: 'body-2', kind: 'markdown', content: '公司已创建，正在补充详情。' },
      ])}
      runActive={false}
      workspace={workspace}
    />,
  )
  expect(processedToggle).toHaveAttribute('aria-expanded', 'true')

  rerender(
    <AgentMessageRow
      message={assistantMessage([
        ...initialParts,
        { id: 'tool-2', kind: 'tool_call', title: '更新记录', content: '更新完成。' },
        { id: 'body-3', kind: 'markdown', content: '资料已经补齐。' },
      ])}
      runActive={false}
      workspace={workspace}
    />,
  )

  await waitFor(() => {
    expect(processedToggle).toHaveAttribute('aria-expanded', 'false')
  })
  expect(screen.getByText('资料已经补齐。')).toBeInTheDocument()
})
