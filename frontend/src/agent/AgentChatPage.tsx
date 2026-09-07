import type { ReactNode } from 'react'
import { Plus } from 'lucide-react'
import { AgentConversation } from './AgentConversation'
import { AgentHistoryPicker } from './AgentHistoryPicker'
import { AgentSessionActionsMenu } from './AgentSessionActionsMenu'
import { useI18n } from '../i18n'
import type { AgentWorkspace } from './useAgentWorkspace'

interface AgentChatPageProps {
  sessionId: string | null
  userName?: string
  emptyStateFooter?: ReactNode
  workspace: AgentWorkspace
  onSessionChange(sessionId: string | null): void
}

export function AgentChatPage({ sessionId, userName, workspace, onSessionChange, emptyStateFooter }: AgentChatPageProps) {
  const { text, t } = useI18n()
  const currentSession = workspace.session?.id === sessionId ? workspace.session : null
  const listedSession = workspace.sessions.find((session) => session.id === sessionId)
  const currentRun = workspace.snapshot?.run ?? currentSession?.activeRun
  const active = Boolean(currentRun && !['completed', 'failed', 'cancelled'].includes(currentRun.status))
  const focusPrompt = sessionId === null || (currentSession ?? listedSession)?.activeLeafMessageId === null

  const createSession = async () => {
    await workspace.newSession()
    onSessionChange(null)
  }

  const deleteSession = async () => {
    if (!sessionId) return
    await workspace.deleteSession(sessionId)
    onSessionChange(null)
  }

  return <div className="agent-chat-page" data-testid="agent-chat-page">
    <header className="topbar agent-chat-header">
      <strong>{sessionId === null ? t('newChat') : currentSession?.title ?? t('openingChat')}</strong>
      <span className="spacer" />
      <button className="agent-chat-header-button" type="button" aria-label={t('newChat')} disabled={active || workspace.busy} onClick={() => void createSession()}><Plus size={16} strokeWidth={1.75} aria-hidden="true" /></button>
      <AgentHistoryPicker
        currentSessionId={currentSession?.id ?? null}
        disabled={active || workspace.busy}
        loadingMore={workspace.loadingMoreSessions}
        nextCursor={workspace.sessionsNextCursor}
        sessions={workspace.sessions}
        loadMore={workspace.loadMoreSessions}
        search={workspace.searchSessions}
        onSessionChange={onSessionChange}
      />
      {sessionId !== null && <AgentSessionActionsMenu
        disabled={!currentSession || active || workspace.busy}
        disabledReason={!currentSession
          ? text('会话加载完成后可执行操作', 'Actions are available after the conversation loads.')
          : active
            ? text('请先停止当前生成', 'Stop the current generation first.')
            : workspace.busy
              ? text('请等待当前操作完成', 'Wait for the current action to finish.')
              : undefined}
        sessionTitle={currentSession?.title ?? text('当前会话', 'Current conversation')}
        onDelete={deleteSession}
      />}
    </header>
    {sessionId !== null && !currentSession && workspace.available !== false && !workspace.error
      ? <div className="workspace-loading" role="status"><span className="spinner" aria-hidden="true" /><span>{t('openingChat')}</span></div>
      : <AgentConversation emptyStateFooter={emptyStateFooter} focusPrompt={focusPrompt} onSessionChange={onSessionChange} userName={userName} workspace={workspace} />}
  </div>
}
