import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { I18nProvider, useI18n } from '../../i18n'
import type { SubagentTaskMetadata } from '../types'
import type { AgentChatMessageContentPart } from './types'
import { SubagentControlPart, SubagentTaskPart } from './SubagentTaskPart'

beforeAll(() => {
  Object.defineProperty(HTMLElement.prototype, 'scrollTo', { configurable: true, value() {} })
  Object.defineProperty(HTMLElement.prototype, 'getAnimations', { configurable: true, value() { return [] } })
})

const metadata: SubagentTaskMetadata = {
  subagent: true, task_id: 'task-1', group_id: 'group-123456', task_key: 'dispatch_1',
  title: 'Original model title', profile: 'analyst', status: 'running', required: true,
  result_available: false, delivery_status: 'pending', attempt_count: 1, duration_ms: null,
  error_code: null, preview: '',
}
const part: AgentChatMessageContentPart = {
  id: 'subagent-task-1', kind: 'tool_call', title: metadata.title,
  content: 'Original model evidence', metadata: { ...metadata },
}

function Harness({ value = part }: { value?: AgentChatMessageContentPart }) {
  const { toggleLocale } = useI18n()
  const [open, setOpen] = useState(false)
  return <><button onClick={toggleLocale}>language</button>
    <SubagentTaskPart part={value} open={open} setOpen={setOpen} /></>
}

it('updates the same task card and preserves its expansion across language changes', async () => {
  const user = userEvent.setup()
  const view = render(<I18nProvider><Harness /></I18nProvider>)
  expect(screen.queryByRole('status')).not.toBeInTheDocument()
  expect(screen.queryByText('任务组 123456')).not.toBeInTheDocument()
  await user.click(screen.getByRole('button', { name: /Original model title/ }))
  expect(await screen.findByText('Original model evidence')).toBeVisible()
  await user.click(screen.getByRole('button', { name: 'language' }))
  expect(screen.queryByRole('status')).not.toBeInTheDocument()
  expect(screen.getByText('Original model evidence')).toBeVisible()
  expect(screen.getByText('Original model title')).toBeVisible()
  view.rerender(<I18nProvider><Harness value={{ ...part, content: 'Final evidence',
    metadata: { ...metadata, status: 'completed', delivery_status: 'delivered', duration_ms: 1200 },
  }} /></I18nProvider>)
  expect(view.container.querySelectorAll('[data-task-id="task-1"]')).toHaveLength(1)
  expect(screen.queryByRole('status')).not.toBeInTheDocument()
  expect(screen.queryByText('Collected by parent')).not.toBeInTheDocument()
  expect(screen.getByText('Final evidence')).toBeVisible()
})

it.each(['failed', 'needs_input', 'cancelled', 'timed_out'] as const)('renders terminal %s tasks', (status) => {
  render(<SubagentTaskPart part={{ ...part, metadata: { ...metadata, status } }} open={false} setOpen={vi.fn()} />)
  expect(screen.getByRole('button', { name: 'Original model title' })).toBeVisible()
  expect(screen.queryByRole('status')).not.toBeInTheDocument()
})

it('renders persistent wait state and its timeout result', async () => {
  const waiting = { ...part, metadata: { tool_name: 'wait_subagents', status: 'waiting', task_count: 3 }, content: '' }
  const view = render(<SubagentControlPart part={waiting} open setOpen={vi.fn()} />)
  expect(screen.getByRole('button', { name: '正在等待子任务 · 3 个子任务' })).toBeVisible()
  view.rerender(<SubagentControlPart part={{ ...waiting, metadata: { ...waiting.metadata, status: 'completed', timed_out: true } }} open setOpen={vi.fn()} />)
  expect(await screen.findByText('本次等待已超时，主 Agent 将继续处理。')).toBeVisible()
})
