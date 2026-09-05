import { fireEvent, render, screen, waitFor } from '@testing-library/react'

import { AgentConversation } from './AgentConversation'
import type { AgentWorkspace } from './useAgentWorkspace'

vi.mock('./AgentMessageList', () => ({ AgentMessageList: () => null }))

const send = vi.fn(async () => 'session-1')

function workspace(active: boolean, busy = false, sessionId = 'session-1'): AgentWorkspace {
  return {
    available: true,
    fileInput: null,
    draftRevisionKey: `principal:${sessionId}`,
    session: {
      id: sessionId,
      activeLeafMessageId: 'user-1',
      messages: [{ id: 'user-1', parentMessageId: null, contentParts: [] }],
      activeRun: active ? { id: 'run-1', status: 'running', assistantMessageId: 'assistant-1' } : null,
    },
    snapshot: null,
    busy,
    error: null,
    send,
    cancel: vi.fn(),
  } as unknown as AgentWorkspace
}

const show = (state: AgentWorkspace, focusPrompt = false) => <>
  <button type="button">其他操作</button>
  <AgentConversation workspace={state} focusPrompt={focusPrompt} />
</>
const input = () => screen.getByRole('textbox', { name: 'Agent 问题输入框' })

it.each([false, true])('restores composer focus after every run with initial focus %s', async (focusPrompt) => {
  const view = render(show(workspace(false), focusPrompt))
  if (focusPrompt) await waitFor(() => expect(input()).toHaveFocus())

  for (const content of ['第一条', '第二条']) {
    fireEvent.change(input(), { target: { value: content } })
    fireEvent.click(screen.getByRole('button', { name: '发送消息' }))
    await waitFor(() => expect(send).toHaveBeenCalledWith(content, []))
    view.rerender(show(workspace(true), focusPrompt))
    expect(input()).toBeDisabled()
    screen.getByRole('button', { name: '其他操作' }).focus()

    view.rerender(show(workspace(false, true), focusPrompt))
    expect(input()).not.toHaveFocus()
    const focus = vi.spyOn(input(), 'focus')
    view.rerender(show(workspace(false), focusPrompt))
    await waitFor(() => expect(input()).toHaveFocus())
    expect(focus).toHaveBeenCalledWith({ preventScroll: true })
    focus.mockRestore()
  }

  screen.getByRole('button', { name: '其他操作' }).focus()
  view.rerender(show({ ...workspace(false), error: '测试提示' }, focusPrompt))
  expect(input()).not.toHaveFocus()
})

it('discards a pending focus request when switching to a different historical session', async () => {
  const view = render(show(workspace(true)))
  screen.getByRole('button', { name: '其他操作' }).focus()
  const focus = vi.spyOn(HTMLTextAreaElement.prototype, 'focus')
  view.rerender(show(workspace(false, false, 'session-2')))
  await new Promise<void>((resolve) => requestAnimationFrame(() => resolve()))
  expect(input()).not.toHaveFocus()
  expect(focus).not.toHaveBeenCalled()
  focus.mockRestore()
})
