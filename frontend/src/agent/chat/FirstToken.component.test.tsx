import { render, screen, waitFor } from '@testing-library/react'

import { MarkdownMessageContent } from './MarkdownMessageContent'
import type { AgentChatMessageContentPart } from './types'

// jsdom does not implement the browser APIs used by the reasoning scroll area.
beforeAll(() => {
  Object.defineProperty(HTMLElement.prototype, 'scrollTo', { configurable: true, value() {} })
  Object.defineProperty(HTMLElement.prototype, 'getAnimations', { configurable: true, value() { return [] } })
})

const startedAt = '2026-09-05T10:00:00Z'
const show = (parts: AgentChatMessageContentPart[], endedAt = startedAt) => <MarkdownMessageContent
  content="" contentParts={parts} enableProcessSession isProcessActive
  reasoningTitle="正在思考" processSessionStartedAt={startedAt} processSessionEndedAt={endedAt}
/>

it.each<AgentChatMessageContentPart>([
  { id: 'first', kind: 'reasoning', content: '先' },
  { id: 'first', kind: 'markdown', content: '你' },
  { id: 'first', kind: 'tool_call', title: '正在读取', content: '' },
])('swaps the same iconless waiting heading on the first $kind token', async (part) => {
  const { container, rerender } = render(show([]))
  const heading = screen.getByRole('button', { name: '正在思考' })
  const process = heading.parentElement
  expect(heading).toBeDisabled()
  expect(heading.querySelector('svg')).toBeNull()
  expect(container.querySelectorAll('.chat-collapsible-content')).toHaveLength(1)
  expect(process).toHaveClass('chat-markdown-message-content__process--waiting')

  rerender(show([{ id: 'empty', kind: 'reasoning', content: ' \n' }]))
  expect(screen.getByRole('button', { name: '正在思考' })).toBe(heading)
  expect(process).toHaveClass('chat-markdown-message-content__process--waiting')

  rerender(show([part]))
  expect(screen.getByRole('button', { name: '已处理' })).toBe(heading)
  expect(process).not.toHaveClass('chat-markdown-message-content__process--waiting')
  expect(heading.querySelector('.text-swap__frame')).toHaveTextContent('正在思考')
  await waitFor(() => expect(heading.querySelector('.text-swap__frame')).toHaveTextContent('已处理'))
  await waitFor(() => expect(heading.querySelector('.text-swap__frame')).toHaveStyle({ opacity: 1 }))
  const settledTitle = heading.querySelector('.text-swap__frame')

  rerender(show([{ ...part, content: `${part.content}后续内容` }], '2026-09-05T10:00:02Z'))
  await waitFor(() => expect(heading).toHaveAccessibleName('已处理 2 s'))
  expect(heading.querySelector('.text-swap__frame')).toBe(settledTitle)
  expect(settledTitle).toHaveStyle({ opacity: 1 })
})

it('uses the same status heading for standalone reasoning and direct Markdown streams', () => {
  const showStandalone = (content: string, reasoningContent = '') => <MarkdownMessageContent
    content={content} reasoningContent={reasoningContent} reasoningTitle="正在思考"
    enableProcessSession isProcessActive
  />
  const { rerender } = render(showStandalone(''))
  const heading = screen.getByRole('button', { name: '正在思考' })
  rerender(showStandalone('', '先明确问题'))
  expect(screen.getByRole('button', { name: '已处理' })).toBe(heading)
  expect(heading).toBeDisabled()
  expect(heading).toHaveAttribute('aria-expanded', 'true')
  rerender(showStandalone('首段回答', '先明确问题'))
  expect(screen.getByRole('button', { name: '已处理' })).toBe(heading)
  expect(heading).toBeEnabled()
  expect(heading).toHaveAttribute('aria-expanded', 'false')
})
