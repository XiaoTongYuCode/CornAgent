import { AuthGate } from './app/AuthGate'
import type { ReactNode } from 'react'
import { List } from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'
import { AgentChatPage } from './agent/AgentChatPage'
import { AgentSidebar } from './agent/AgentSidebar'
import { CornAgentProvider } from './agent/CornAgentProvider'
import { useAgent } from './agent/AgentContext'
import { navigate, useMobileLayout, usePathname } from './app/navigation'
import { ProjectContactLinks } from './app/ProjectContactLinks'
import { SidebarExamplePage } from './app/SidebarExamplePage'
import { Sidebar } from './components/Sidebar'
import { useI18n } from './i18n'
import { ProcessTransitionPreview } from './previews/ProcessTransitionPreview'

const COLLAPSED_KEY = 'cornagent:sidebar-collapsed'
function initialCollapsed() {
  try {
    return localStorage.getItem(COLLAPSED_KEY) === 'true'
  } catch {
    return false
  }
}
function Application({ path, sessionId, accountControls }: { path: string; sessionId: string | null; accountControls?: ReactNode }) {
  const { t } = useI18n()
  const mobile = useMobileLayout()
  const [sidebarCollapsed, setSidebarCollapsed] = useState(initialCollapsed)
  const [mobileOpen, setMobileOpen] = useState(false)
  const mobileToggleRef = useRef<HTMLButtonElement>(null)
  const example = path === '/sidebar'
  const renderingPreview = path === '/rendering'
  const chat = !example && !renderingPreview
  const workspace = useAgent()
  const collapsed = !mobile && sidebarCollapsed
  const currentRun = workspace.snapshot?.run ?? workspace.session?.activeRun
  const activeSessionId =
    currentRun && !['completed', 'failed', 'cancelled'].includes(currentRun.status)
      ? (workspace.session?.id ?? null)
      : null
  useEffect(() => {
    try {
      localStorage.setItem(COLLAPSED_KEY, String(sidebarCollapsed))
    } catch {
      /* Optional persistence. */
    }
  }, [sidebarCollapsed])
  const closeMobile = useCallback(() => {
    setMobileOpen(false)
    mobileToggleRef.current?.focus()
  }, [])
  const changeSession = (id: string | null) => {
    setMobileOpen(false)
    navigate(id ? `/chat/${encodeURIComponent(id)}` : '/chat')
  }
  return (
    <div
      className={`app-shell cornagent-shell${collapsed ? ' sidebar-collapsed' : ''}`}
      data-mobile-sidebar-open={mobile && mobileOpen}
    >
      <button
        ref={mobileToggleRef}
        type="button"
        className="mobile-navigation-toggle"
        aria-label={t('openNavigation')}
        aria-controls="primary-sidebar"
        aria-expanded={mobileOpen}
        onClick={() => setMobileOpen(true)}
      >
        <List size={20} />
      </button>
      {mobile && mobileOpen && (
        <button
          type="button"
          className="mobile-sidebar-backdrop"
          aria-label={t('closeNavigation')}
          tabIndex={-1}
          onClick={closeMobile}
        />
      )}
      <Sidebar
        collapsed={collapsed}
        mobile={mobile}
        mobileOpen={mobileOpen}
        onCollapse={() => setSidebarCollapsed(true)}
        onExpand={() => setSidebarCollapsed(false)}
        onCloseMobile={closeMobile}
        sessions={workspace.sessions}
        currentSessionId={chat ? sessionId : null}
        home={chat && sessionId === null}
        example={example}
        renderingPreview={renderingPreview}
        loadingMore={workspace.loadingMoreSessions}
        hasMore={Boolean(workspace.sessionsNextCursor)}
        onLoadMore={workspace.loadMoreSessions}
        onHome={() => changeSession(null)}
        onExample={() => {
          setMobileOpen(false)
          navigate('/sidebar')
        }}
        onRenderingPreview={() => {
          setMobileOpen(false)
          navigate('/rendering')
        }}
        onNewChat={() => {
          void workspace.newSession()
          changeSession(null)
        }}
        onOpenChat={changeSession}
        busy={workspace.busy}
        activeSessionId={activeSessionId}
        onDeleteChat={async (id) => {
          await workspace.deleteSession(id)
          if (window.location.pathname === `/chat/${encodeURIComponent(id)}`) changeSession(null)
        }}
      />
      <main className={`cornagent-main${renderingPreview ? ' cornagent-main--rendering' : ''}`} inert={mobile && mobileOpen}>
        {accountControls}
        {renderingPreview ? (
          <>
            <header className="topbar"><strong>{t('agentRendering')}</strong></header>
            <ProcessTransitionPreview />
          </>
        ) : example ? (
          <SidebarExamplePage />
        ) : (
          <AgentChatPage
            emptyStateFooter={sessionId === null ? <ProjectContactLinks /> : undefined}
            sessionId={sessionId}
            workspace={workspace}
            onSessionChange={changeSession}
          />
        )}
      </main>
      {example && <AgentSidebar layout="docked" />}
    </div>
  )
}
export default function App() {
  const path = usePathname()
  const match = path.match(/^\/chat\/([^/]+)$/)
  const sessionId = match ? decodeURIComponent(match[1]) : null
  return (
    <AuthGate>{(principal, controls) => <CornAgentProvider key={principal} principalKey={principal} sessionId={path === '/sidebar' || path === '/rendering' ? undefined : sessionId}>
      <Application path={path} sessionId={sessionId} accountControls={controls} />
    </CornAgentProvider>}</AuthGate>
  )
}
