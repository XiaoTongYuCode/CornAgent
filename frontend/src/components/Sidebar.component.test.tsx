import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useMemo, useState } from 'react'
import { I18nProvider } from '../i18n'
import { AppThemeContext } from '../app/AppThemeContext'
import { PromptPanel } from '../agent/chat/PromptPanel'
import type { AgentSession } from '../agent/types'
import { Sidebar } from './Sidebar'

const sessions = [{ id: 'chat-1', title: '保留用户会话标题' }] as AgentSession[]
function Harness({ onNewChat = vi.fn(), onOpenChat = vi.fn(), onDeleteChat = vi.fn() }) {
  const [theme, setTheme] = useState<'light' | 'dark'>('light')
  const [collapsed, setCollapsed] = useState(false)
  const value = useMemo(
    () => ({
      theme,
      toggleTheme: () => setTheme((current) => (current === 'light' ? 'dark' : 'light')),
    }),
    [theme],
  )
  return (
    <I18nProvider>
      <AppThemeContext.Provider value={value}>
        <div className={`app-shell${collapsed ? ' sidebar-collapsed' : ''}`}>
          <Sidebar
            sessions={sessions}
            currentSessionId={null}
            home
            example={false}
            renderingPreview={false}
            hasMore={false}
            loadingMore={false}
            onLoadMore={vi.fn()}
            onHome={vi.fn()}
            onExample={vi.fn()}
            onRenderingPreview={vi.fn()}
            onNewChat={onNewChat}
            onOpenChat={onOpenChat}
            onDeleteChat={onDeleteChat}
            busy={false}
            activeSessionId={null}
            mobile={false}
            mobileOpen={false}
            collapsed={collapsed}
            onCollapse={() => setCollapsed(true)}
            onExpand={() => setCollapsed(false)}
            onCloseMobile={vi.fn()}
          />
          <PromptPanel onStartResearch={vi.fn()} />
        </div>
      </AppThemeContext.Provider>
    </I18nProvider>
  )
}

it('switches language without losing the draft or translating user titles', async () => {
  const user = userEvent.setup()
  render(<Harness />)
  const navigation = screen.getByRole('navigation', { name: '主导航' })
  expect(within(navigation).getByRole('button', { name: '首页' })).toHaveAttribute(
    'aria-current',
    'page',
  )
  expect(within(navigation).getByRole('button', { name: '侧边栏示例' })).toBeVisible()
  expect(document.querySelector('.brand-mark, .cornagent-brand, .cornagent-mark')).toBeNull()
  await user.type(screen.getByRole('textbox', { name: 'Agent 问题输入框' }), 'keep this draft')
  await user.click(screen.getByRole('button', { name: 'Switch to English' }))
  expect(screen.getByRole('textbox', { name: 'Message to agent' })).toHaveValue('keep this draft')
  expect(screen.getByRole('button', { name: 'Home' })).toBeVisible()
  expect(screen.getByRole('button', { name: 'Chats' })).toBeVisible()
  expect(screen.getByRole('button', { name: sessions[0].title })).toBeVisible()
  expect(document.documentElement.lang).toBe('en')
  expect(localStorage.getItem('cornagent.locale')).toBe('en')
  await user.click(screen.getByRole('button', { name: 'Switch to dark theme' }))
  expect(screen.getByRole('button', { name: 'Switch to light theme' })).toHaveAttribute(
    'aria-pressed',
    'true',
  )
})

it('collapses chat history independently from starting and opening a conversation', async () => {
  const user = userEvent.setup()
  const onNewChat = vi.fn()
  const onOpenChat = vi.fn()
  render(<Harness onNewChat={onNewChat} onOpenChat={onOpenChat} />)
  await user.click(screen.getByRole('button', { name: sessions[0].title }))
  expect(onOpenChat).toHaveBeenCalledWith('chat-1')
  await user.click(screen.getByRole('button', { name: '聊天' }))
  expect(screen.queryByRole('button', { name: sessions[0].title })).not.toBeInTheDocument()
  expect(screen.getByRole('button', { name: '聊天' })).toHaveAttribute('aria-expanded', 'false')
  expect(localStorage.getItem('cornagent:sidebar-chats-open')).toBe('false')
  await user.click(screen.getByRole('button', { name: '新对话' }))
  expect(onNewChat).toHaveBeenCalledOnce()
})

it('resizes with the keyboard and restores the collapsed sidebar', async () => {
  const user = userEvent.setup()
  render(<Harness />)
  const handle = screen.getByRole('separator', { name: '调整导航栏宽度' })
  fireEvent.keyDown(handle, { key: 'Home' })
  expect(handle).toHaveAttribute('aria-valuenow', '200')
  expect(localStorage.getItem('cornagent-sidebar-width:v1')).toBe('200')
  await user.click(screen.getByRole('button', { name: '收起侧边栏' }))
  expect(screen.queryByRole('navigation')).not.toBeInTheDocument()
  await user.click(screen.getByRole('button', { name: '展开导航' }))
  await waitFor(() => expect(screen.getByRole('navigation', { name: '主导航' })).toBeVisible())
})

it('deletes the chosen sidebar conversation only after confirmation', async () => {
  const user = userEvent.setup()
  const onDeleteChat = vi.fn(async () => undefined)
  render(<Harness onDeleteChat={onDeleteChat} />)
  await user.click(screen.getByRole('button', { name: `管理“${sessions[0].title}”` }))
  await user.click(await screen.findByRole('menuitem', { name: '删除会话' }))
  const dialog = await screen.findByRole('dialog', { name: `删除“${sessions[0].title}”？` })
  expect(onDeleteChat).not.toHaveBeenCalled()
  await user.click(within(dialog).getByRole('button', { name: '删除会话' }))
  await waitFor(() => expect(onDeleteChat).toHaveBeenCalledWith('chat-1'))
})
