import { ChartNoAxesCombined, ChevronDown, House, MessagesSquare, PanelRight, Plus, SquarePlay, UserRound } from 'lucide-react'
import { useEffect, useState } from 'react'
import type { AgentSession } from '../../agent/types'
import { AgentSessionActionsMenu } from '../../agent/AgentSessionActionsMenu'
import { useI18n } from '../../i18n'
import { SidebarNavItem } from './SidebarNavItem'

export interface SidebarNavigationProps {
  sessions: AgentSession[]
  currentSessionId: string | null
  home: boolean
  example: boolean
  renderingPreview: boolean
  usage?: boolean
  onUsage?(): void
  profile?: boolean
  onProfile?(): void
  loadingMore: boolean
  hasMore: boolean
  onHome(): void
  onExample(): void
  onRenderingPreview(): void
  onNewChat(): void
  onOpenChat(id: string): void
  onLoadMore(): Promise<void>
  onDeleteChat(id: string): Promise<void>
  busy: boolean
  activeSessionId: string | null
}
const CHATS_OPEN_KEY = 'cornagent:sidebar-chats-open'
function initialChatsOpen() {
  try {
    return localStorage.getItem(CHATS_OPEN_KEY) !== 'false'
  } catch {
    return true
  }
}
export function SidebarNavigation({
  sessions,
  currentSessionId,
  home,
  example,
  renderingPreview,
  usage = false,
  onUsage,
  profile = false,
  onProfile,
  loadingMore,
  hasMore,
  onHome,
  onExample,
  onRenderingPreview,
  onNewChat,
  onOpenChat,
  onLoadMore,
  onDeleteChat,
  busy,
  activeSessionId,
}: SidebarNavigationProps) {
  const { t } = useI18n()
  const [chatsOpen, setChatsOpen] = useState(initialChatsOpen)
  const [visibleChatCount, setVisibleChatCount] = useState(5)
  const visibleSessions = sessions.slice(0, visibleChatCount)
  const canLoadMore = visibleSessions.length < sessions.length || hasMore
  useEffect(() => {
    try {
      localStorage.setItem(CHATS_OPEN_KEY, String(chatsOpen))
    } catch {
      /* Optional persistence. */
    }
  }, [chatsOpen])
  const loadMore = () => {
    setVisibleChatCount((count) => count + 10)
    if (visibleChatCount >= sessions.length && hasMore) void onLoadMore()
  }
  return (
    <nav className="nav-scroll" aria-label={t('navigation')}>
      <div className="nav-group compact">
        <SidebarNavItem
          active={home}
          onClick={onHome}
          icon={<House size={16} strokeWidth={1.75} aria-hidden="true" />}
        >
          {t('home')}
        </SidebarNavItem>
        <SidebarNavItem
          active={example}
          onClick={onExample}
          icon={<PanelRight size={16} strokeWidth={1.75} aria-hidden="true" />}
        >
          {t('sidebarExample')}
        </SidebarNavItem>
        <SidebarNavItem
          active={renderingPreview}
          onClick={onRenderingPreview}
          icon={<SquarePlay size={16} strokeWidth={1.75} aria-hidden="true" />}
        >
          {t('agentRendering')}
        </SidebarNavItem>
        {onUsage && <SidebarNavItem active={usage} onClick={onUsage}
          icon={<ChartNoAxesCombined size={16} strokeWidth={1.75} aria-hidden="true" />}>
          {t('usageTitle')}
        </SidebarNavItem>}
        {onProfile && (
          <SidebarNavItem active={profile} onClick={onProfile}
            icon={<UserRound size={16} strokeWidth={1.75} aria-hidden="true" />}>
            {t('myProfile')}
          </SidebarNavItem>
        )}
      </div>
      <section className={chatsOpen ? 'nav-section open' : 'nav-section'}>
        <div className="nav-section-heading">
          <button
            type="button"
            className="nav-section-toggle"
            aria-expanded={chatsOpen}
            aria-controls="sidebar-chat-navigation"
            onClick={() => setChatsOpen((open) => !open)}
          >
            <ChevronDown
              className={chatsOpen ? 'nav-section-caret open' : 'nav-section-caret'}
              size={12}
              strokeWidth={1.75}
              aria-hidden="true"
            />
            <span>{t('chats')}</span>
          </button>
          <span className="nav-actions">
            <button
              type="button"
              aria-label={t('newChat')}
              title={t('newChat')}
              onClick={onNewChat}
            >
              <Plus size={14} strokeWidth={1.75} aria-hidden="true" />
            </button>
          </span>
        </div>
        <div id="sidebar-chat-navigation" className="nav-section-content" hidden={!chatsOpen}>
          <div className="nav-group list-nav-group chat-session-nav-list">
            {visibleSessions.map((session) => (
              <div
                className={session.id === currentSessionId ? 'nav-chat-row active' : 'nav-chat-row'}
                key={session.id}
              >
                <SidebarNavItem
                  active={session.id === currentSessionId}
                  onClick={() => onOpenChat(session.id)}
                  title={session.title}
                  icon={<MessagesSquare size={16} strokeWidth={1.75} aria-hidden="true" />}
                >
                  {session.title}
                </SidebarNavItem>
                <AgentSessionActionsMenu
                  sessionTitle={session.title}
                  triggerClassName="nav-chat-actions"
                  triggerLabel={t('chatActions', { title: session.title })}
                  disabled={busy || session.id === activeSessionId}
                  disabledReason={t(
                    session.id === activeSessionId ? 'stopBeforeAction' : 'waitBeforeAction',
                  )}
                  onDelete={() => onDeleteChat(session.id)}
                />
              </div>
            ))}
            {sessions.length === 0 && <span className="nav-chat-empty">{t('noChats')}</span>}
            {canLoadMore && (
              <button
                type="button"
                className="nav-item nav-chat-load-more"
                disabled={loadingMore}
                onClick={loadMore}
              >
                {t(loadingMore ? 'loading' : 'loadMore')}
              </button>
            )}
          </div>
        </div>
      </section>
    </nav>
  )
}
