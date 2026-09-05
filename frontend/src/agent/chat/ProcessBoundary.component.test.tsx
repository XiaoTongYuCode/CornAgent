import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { MarkdownMessageContent } from './MarkdownMessageContent'
import type { AgentChatMessageContentPart } from './types'

it('keeps the trailing tool group outside the process until a new body moves the boundary', async () => {
  const parts: AgentChatMessageContentPart[] = [
    { id: 'before', kind: 'tool_call', title: '前置检查', content: '检查完成。' },
    { id: 'body-1', kind: 'markdown', content: '正在执行后续操作。' },
    ...Array.from({ length: 4 }, (_, index) => ({
      id: `after-${index}`, kind: 'tool_call' as const, title: `后置工具 ${index + 1}`, content: '工具结果。',
    })),
  ]
  const show = (contentParts: AgentChatMessageContentPart[], streaming = true) => <MarkdownMessageContent
    content="" contentParts={contentParts} enableProcessSession
    isMessageStreaming={streaming} isProcessActive={streaming}
  />
  const { rerender, unmount } = render(show(parts))
  const group = screen.getByRole('button', { name: '已处理 4 个步骤' })
  expect(group.closest('.chat-markdown-message-content__process')).toBeNull()
  expect(screen.queryByText('前置检查')).not.toBeInTheDocument()
  const body = screen.getByText((_, element) => element?.tagName === 'P' && element.textContent === '正在执行后续操作。')
  expect(body.compareDocumentPosition(group) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  await userEvent.click(group)
  expect(group).toHaveAttribute('aria-expanded', 'true')
  rerender(show([...parts, { id: 'body-2', kind: 'markdown', content: '  \n' }]))
  expect(screen.getByRole('button', { name: '已处理 4 个步骤' })).toBe(group)
  expect(group).toHaveAttribute('aria-expanded', 'true')

  rerender(show([...parts, { id: 'body-2', kind: 'markdown', content: '全部完成。' }]))
  expect(screen.getByText((_, element) => element?.tagName === 'P' && element.textContent === '全部完成。')).toBeInTheDocument()
  await waitFor(() => expect(screen.queryByRole('button', { name: '已处理 4 个步骤' })).not.toBeInTheDocument())
  const process = screen.getByRole('button', { name: '已处理' })
  expect(process).toHaveAttribute('aria-expanded', 'false')
  await userEvent.click(process)
  const restoredGroup = await screen.findByRole('button', { name: '已处理 4 个步骤' })
  expect(restoredGroup.closest('.chat-markdown-message-content__process')).not.toBeNull()
  await userEvent.click(restoredGroup)
  expect(await screen.findByRole('button', { name: '后置工具 1' })).toBeInTheDocument()

  unmount()
  render(show(JSON.parse(JSON.stringify(parts)), false))
  expect(screen.getByRole('button', { name: '已处理 4 个步骤' }).closest('.chat-markdown-message-content__process')).toBeNull()
  expect(screen.getByText('正在执行后续操作。')).toBeInTheDocument()
})
