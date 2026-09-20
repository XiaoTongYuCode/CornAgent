import { fireEvent, render, screen } from '@testing-library/react'

import { I18nProvider, useI18n } from '../i18n'
import type { AgentWorkspace } from './useAgentWorkspace'
import { AgentConversation } from './AgentConversation'

const originalScrollTo = Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'scrollTo')

const workspace = {
  available: true,
  fileInput: null,
  draftRevisionKey: 'principal:new-session',
  session: null,
  snapshot: null,
  busy: false,
  error: null,
  send: vi.fn(),
  uploadFile: vi.fn(),
  deleteFile: vi.fn(),
  respond: vi.fn(),
  cancel: vi.fn(),
} as unknown as AgentWorkspace

beforeEach(() => {
  localStorage.setItem('cornagent.locale', 'en')
  vi.useFakeTimers()
  vi.setSystemTime(new Date(2026, 8, 3, 14, 0, 0))
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(null)
})

afterEach(() => {
  vi.useRealTimers()
  vi.restoreAllMocks()
  if (originalScrollTo) Object.defineProperty(HTMLElement.prototype, 'scrollTo', originalScrollTo)
  else Reflect.deleteProperty(HTMLElement.prototype, 'scrollTo')
  localStorage.removeItem('cornagent.locale')
})

it('places the 32px composing orb before the empty-session title', () => {
  const { container } = render(<I18nProvider><AgentConversation workspace={workspace} userName="Alex" /></I18nProvider>)

  const title = screen.getByRole('heading', { level: 1, name: 'Good afternoon, Alex' })
  const titleRow = title.closest('.agent-new-conversation__title')
  const orb = container.querySelector('.agent-new-conversation__orb')
  expect(titleRow).not.toBeNull()
  expect(titleRow?.firstElementChild).toBe(orb)
  expect(orb).toHaveAttribute('aria-hidden', 'true')
  expect(orb).toHaveStyle({ width: '32px', height: '32px' })
})

it('updates the empty-session greeting when the locale changes', () => {
  function LocaleHarness() {
    const { toggleLocale } = useI18n()
    return <>
      <button type="button" onClick={toggleLocale}>切换语言</button>
      <AgentConversation workspace={workspace} userName="Alex" />
    </>
  }

  render(<I18nProvider><LocaleHarness /></I18nProvider>)

  expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent(/^Good afternoon, Alex$/)
  fireEvent.click(screen.getByRole('button', { name: '切换语言' }))
  expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent(/^下午好，Alex$/)
})

it.each(['history', 'snapshot'] as const)('hides secondary controls while a %s question is pending and restores the draft', (source) => {
  Object.defineProperty(HTMLElement.prototype, 'scrollTo', { configurable: true, value: vi.fn() })
  const receipt = { id: 'write', kind: 'tool_call' as const, content: 'Saved', metadata: {
    tool_name: 'save_record', operation_outcome: { state: 'committed', counts: { committed: 1 } },
  } }
  const question = { id: 'question', kind: 'user_question' as const, content: 'Choose a task', metadata: {
    question_id: 'q1', run_id: 'run', tool_call_id: 'ask', status: 'pending', options: [{ id: 'a', content: 'Review', description: '' }],
  } }
  const run = { id: 'run', assistantMessageId: 'assistant', status: 'running' }
  const state = {
    ...workspace,
    session: { id: 'session', activeLeafMessageId: 'assistant', activeRun: run,
      messages: [{ id: 'assistant', role: 'assistant', parentMessageId: null, markdown: 'Working', contentParts: [receipt] }],
      inputs: [{ id: 'queued', session_id: 'session', version: 1, status: 'pending', mode: 'queue', content: 'Next task', file_ids: [] }],
    },
  } as unknown as AgentWorkspace
  const show = (next: AgentWorkspace) => <I18nProvider><AgentConversation workspace={next} /></I18nProvider>
  const view = render(show(state))
  const prompt = view.container.querySelector('.agent-conversation-prompt textarea')!
  fireEvent.change(prompt, { target: { value: 'Keep my draft' } })
  expect(view.container.querySelector('.agent-turn-changes')).toBeVisible()
  const parts = [receipt, question]
  const waiting = source === 'snapshot'
    ? { ...state, snapshot: { run: { ...run, status: 'waiting_for_user' }, contentParts: parts, draftMarkdown: 'Working' } }
    : { ...state, session: { ...state.session!, activeRun: { ...run, status: 'waiting_for_user' }, messages: [{ ...state.session!.messages[0], contentParts: parts }] } }
  view.rerender(show(waiting as AgentWorkspace))
  expect(screen.getByText('Choose a task')).toBeVisible()
  expect(prompt).not.toBeVisible()
  expect(screen.getByText('Next task')).not.toBeVisible()
  expect(view.container.querySelector('.agent-turn-changes')).toBeNull()
  view.rerender(show(state))
  expect(prompt).toBeVisible()
  expect(prompt).toHaveValue('Keep my draft')
  expect(screen.getByText('Next task')).toBeVisible()
  expect(view.container.querySelector('.agent-turn-changes')).toBeVisible()
})
