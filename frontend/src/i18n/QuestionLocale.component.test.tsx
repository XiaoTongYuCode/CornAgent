import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { I18nProvider, useI18n } from '../i18n'
import { UserQuestionPart } from '../agent/chat/UserQuestionPart'

function ToggleLanguage() {
  const { toggleLocale } = useI18n()
  return <button onClick={toggleLocale}>Switch language</button>
}

it('keeps the question and answer draft intact while translating its controls', async () => {
  const user = userEvent.setup()
  const respond = vi.fn(async () => undefined)
  render(
    <I18nProvider>
      <ToggleLanguage />
      <UserQuestionPart
        display="composer"
        onRespondUserQuestion={respond}
        part={{
          id: 'question-part',
          kind: 'user_question',
          content: '需要哪些项目资料？',
          metadata: {
            question_id: 'question-1',
            status: 'pending',
            options: [{ id: 'a', content: '用户提供的选项', description: '' }],
          },
        }}
      />
    </I18nProvider>,
  )
  await user.type(screen.getByPlaceholderText('输入其他回答'), '保留我的回答')
  await user.click(screen.getByRole('button', { name: 'Switch language' }))
  expect(screen.getByPlaceholderText('Enter another answer')).toHaveValue('保留我的回答')
  expect(screen.getByText('需要哪些项目资料？')).toBeVisible()
  expect(screen.getByText('用户提供的选项')).toBeVisible()
  expect(screen.getByRole('button', { name: /Skip/ })).toBeVisible()
  await user.click(screen.getByRole('button', { name: 'Submit' }))
  expect(respond).toHaveBeenCalledWith({
    questionId: 'question-1',
    action: 'answer',
    content: '保留我的回答',
    optionId: null,
  })
})
