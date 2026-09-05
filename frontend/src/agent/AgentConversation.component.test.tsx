import { fireEvent, render, screen } from '@testing-library/react'

import { I18nProvider, useI18n } from '../i18n'
import type { AgentWorkspace } from './useAgentWorkspace'
import { AgentConversation } from './AgentConversation'

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
