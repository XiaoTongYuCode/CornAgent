import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { CornAgentApiError } from '../../api/transport'
import { I18nProvider, useI18n } from '../../i18n'
import { UserQuestionPart } from './UserQuestionPart'
import type { AgentChatMessageContentPart } from './types'

const content = '保留完整的原始用户选项内容，不应由界面翻译或截断后提交'
const description = '这是一段很长的说明，需要在窄面板和触屏设备上也能完整阅读。'
const part: AgentChatMessageContentPart = {
  id: 'question', kind: 'user_question', content: '请选择',
  metadata: { question_id: 'q1', status: 'pending', options: [{ id: 'a', content, description }] },
}

function Toggle() {
  const { toggleLocale } = useI18n()
  return <button onClick={toggleLocale}>Language</button>
}

it('exposes full option text on hover and submits the original content', async () => {
  const user = userEvent.setup()
  const respond = vi.fn(async () => {})
  render(<UserQuestionPart display="composer" part={part} onRespondUserQuestion={respond} />)
  const option = screen.getByRole('button', { name: new RegExp(content) })
  await user.hover(option)
  expect(await screen.findByRole('tooltip')).toHaveTextContent(content)
  expect(screen.getByRole('tooltip')).toHaveTextContent(description)
  await user.click(option)
  expect(respond).toHaveBeenCalledWith({ action: 'answer', content, optionId: 'a', questionId: 'q1' })
})

it('keeps the answer draft and translates a failed request when switching language', async () => {
  const user = userEvent.setup()
  const respond = vi.fn().mockRejectedValue(new CornAgentApiError(503, 'busy', 'raw internal error'))
  render(<I18nProvider><Toggle /><UserQuestionPart display="composer" part={part} onRespondUserQuestion={respond} /></I18nProvider>)
  const input = screen.getByRole('textbox')
  await user.type(input, '我的回答')
  await user.click(screen.getByRole('button', { name: '提交' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('服务暂时不可用')
  expect(input).toHaveValue('我的回答')
  await user.click(screen.getByRole('button', { name: 'Language' }))
  await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('The service is temporarily unavailable'))
  expect(input).toHaveValue('我的回答')
  expect(respond).toHaveBeenCalledTimes(1)
  expect(screen.getByRole('button', { name: new RegExp(content) })).toBeVisible()
})
