import { render, screen } from '@testing-library/react'

import { I18nProvider } from '../i18n'
import { AgentChatPage } from './AgentChatPage'
import type { AgentWorkspace } from './useAgentWorkspace'

const loadingWorkspace = {
  available: true,
  imageInput: null,
  draftRevisionKey: 'principal:new',
  sessions: [],
  session: null,
  snapshot: null,
  busy: false,
  loadingMoreSessions: false,
  sessionsNextCursor: null,
  error: null,
  newSession: vi.fn(),
  deleteSession: vi.fn(),
  loadMoreSessions: vi.fn(),
  searchSessions: vi.fn(),
  send: vi.fn(),
  uploadImage: vi.fn(),
  deleteImage: vi.fn(),
  respond: vi.fn(),
  cancel: vi.fn(),
} as unknown as AgentWorkspace

it('keeps the new-conversation composer hidden while a routed session is loading', () => {
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(null)

  render(<I18nProvider>
    <AgentChatPage sessionId="existing-session" workspace={loadingWorkspace} onSessionChange={vi.fn()} />
  </I18nProvider>)

  expect(screen.getByRole('status')).toHaveTextContent('正在打开对话…')
  expect(screen.queryByRole('textbox', { name: 'Agent 问题输入框' })).not.toBeInTheDocument()
})

it('shows a routed session load error instead of an endless loading state', () => {
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(null)

  render(<I18nProvider>
    <AgentChatPage sessionId="missing-session" workspace={{ ...loadingWorkspace, error: '会话不存在' }} onSessionChange={vi.fn()} />
  </I18nProvider>)

  expect(screen.getByRole('alert')).toHaveTextContent('会话不存在')
  expect(screen.queryByRole('status')).not.toBeInTheDocument()
})

it('shows the unavailable state when a routed session cannot load', () => {
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(null)

  render(<I18nProvider>
    <AgentChatPage sessionId="existing-session" workspace={{ ...loadingWorkspace, available: false }} onSessionChange={vi.fn()} />
  </I18nProvider>)

  expect(screen.getByRole('heading', { name: 'Agent 暂不可用' })).toBeInTheDocument()
  expect(screen.queryByRole('status')).not.toBeInTheDocument()
})

it('does not offer session actions before a new conversation has been created', () => {
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(null)
  render(<I18nProvider>
    <AgentChatPage sessionId={null} workspace={loadingWorkspace} onSessionChange={vi.fn()} />
  </I18nProvider>)
  expect(screen.queryByRole('button', { name: '更多操作' })).not.toBeInTheDocument()
})
