import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { I18nProvider, useI18n } from '../../i18n'
import type { AgentMessage } from '../types'
import { UserMessage } from './UserMessage'

const message: AgentMessage = {
  id: 'user-1', sessionId: 'session-1', role: 'user', markdown: '原始问题',
  attachments: [], contentParts: [], run: null, parentMessageId: null,
  versionGroupId: 'user-1', versionIndex: 1, versionCount: 2,
  previousVersionId: null, nextVersionId: 'user-2', supersedesMessageId: null,
  processStartedAt: null, processCompletedAt: null, createdAt: '', updatedAt: '',
}
function workspace() { return { edit: vi.fn(async () => {}), switchVersion: vi.fn(async () => {}) } }
function LocaleToggle() {
  const { toggleLocale } = useI18n()
  return <button onClick={toggleLocale}>语言</button>
}

it('copies the original text and switches user-message branches', async () => {
  const user = userEvent.setup()
  const actions = workspace()
  render(<UserMessage message={message} disabled={false} workspace={actions} />)
  await user.click(screen.getByRole('button', { name: '复制' }))
  expect(await navigator.clipboard.readText()).toBe(message.markdown)
  expect(screen.getByRole('button', { name: '已复制' })).toBeInTheDocument()
  expect(screen.getByRole('button', { name: '上一版本' })).toBeDisabled()
  await user.click(screen.getByRole('button', { name: '下一版本' }))
  expect(actions.switchVersion).toHaveBeenCalledWith('user-2')
})

it('preserves an edit draft across locale changes and supports cancellation', async () => {
  const user = userEvent.setup()
  const actions = workspace()
  render(<I18nProvider><LocaleToggle /><UserMessage message={message} disabled={false} workspace={actions} /></I18nProvider>)
  await user.click(screen.getByRole('button', { name: '编辑消息' }))
  const editor = screen.getByRole('textbox', { name: '消息内容' })
  await user.clear(editor)
  await user.type(editor, '修改后的问题')
  await user.click(screen.getByRole('button', { name: '语言' }))
  expect(screen.getByRole('textbox', { name: 'Message content' })).toHaveValue('修改后的问题')
  await user.click(screen.getByRole('button', { name: 'Cancel' }))
  expect(screen.queryByRole('textbox')).toBeNull()
  expect(screen.getByText('原始问题')).toBeVisible()
  expect(actions.edit).not.toHaveBeenCalled()
})

it('keeps the draft on failure and sends only the text so existing attachments are preserved', async () => {
  const user = userEvent.setup()
  const actions = workspace()
  actions.edit.mockRejectedValueOnce(new Error('网络连接中断')).mockResolvedValueOnce()
  render(<UserMessage message={message} disabled={false} workspace={actions} />)
  await user.click(screen.getByRole('button', { name: '编辑消息' }))
  const editor = screen.getByRole('textbox', { name: '消息内容' })
  await user.clear(editor)
  expect(screen.getByRole('button', { name: '保存并发送' })).toBeDisabled()
  await user.type(editor, '修改后的问题')
  await user.click(screen.getByRole('button', { name: '保存并发送' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('网络连接中断')
  expect(editor).toHaveValue('修改后的问题')
  await user.click(editor)
  await user.keyboard('{Enter}')
  await waitFor(() => expect(screen.queryByRole('textbox')).toBeNull())
  expect(actions.edit).toHaveBeenLastCalledWith(message.id, '修改后的问题')
})

it('blocks edits and branch changes while a run is active but still allows copying', () => {
  render(<UserMessage message={message} disabled workspace={workspace()} />)
  expect(screen.getByRole('button', { name: '编辑消息' })).toBeDisabled()
  expect(screen.getByRole('button', { name: '下一版本' })).toBeDisabled()
  expect(screen.getByRole('button', { name: '复制' })).toBeEnabled()
})
