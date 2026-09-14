import clsx from 'clsx'
import { Plus, X } from 'lucide-react'
import type { CSSProperties } from 'react'
import { useI18n } from '../i18n'
import { AgentHistoryPicker } from './AgentHistoryPicker'
import type { AgentSidebarProps, AgentSidebarRenderContext } from './AgentSidebar.types'
import type { AgentWorkspace } from './useAgentWorkspace'

type HeaderProps = Pick<AgentSidebarProps, 'title' | 'icon' | 'renderHeader' | 'renderActions'> & {
  workspace: AgentWorkspace
  close: () => void
  className?: string
  style?: CSSProperties
}

export function AgentPanelHeader({ workspace, close, title, icon, renderHeader, renderActions, className, style }: HeaderProps) {
  const { t } = useI18n()
  const currentRun = workspace.snapshot?.run ?? workspace.session?.activeRun
  const active = Boolean(currentRun && !['completed', 'failed', 'cancelled'].includes(currentRun.status))
  const busy = active || workspace.busy
  const actions = {
    newChat: <button type="button" className="agent-icon-button" aria-label={t('newChat')} disabled={busy} onClick={() => void workspace.newSession()}><Plus size={16} strokeWidth={1.75} aria-hidden="true" /></button>,
    history: <AgentHistoryPicker
      currentSessionId={workspace.session?.id ?? null}
      disabled={busy}
      loadingMore={workspace.loadingMoreSessions}
      nextCursor={workspace.sessionsNextCursor}
      sessions={workspace.sessions}
      loadMore={workspace.loadMoreSessions}
      search={workspace.searchSessions}
      onSessionChange={(sessionId) => { void workspace.selectSession(sessionId) }}
    />,
    close: <button type="button" className="agent-icon-button" aria-label={t('closeAgent')} onClick={close}><X size={16} strokeWidth={1.75} aria-hidden="true" /></button>,
  }
  const defaultActions = <>{actions.newChat}{actions.history}{actions.close}</>
  const context: AgentSidebarRenderContext = { workspace, close, busy, actions, defaultContent: defaultActions }
  const defaultHeader = <>
    <div className="agent-panel-identity">
      {icon}
      <strong>{title}</strong>
    </div>
    <span className="spacer" />
    {renderActions ? renderActions(context) : defaultActions}
  </>
  const header = renderHeader ? renderHeader({ ...context, defaultContent: defaultHeader }) : defaultHeader
  return header != null && header !== false
    ? <header className={clsx('agent-panel-header', className)} style={style}>{header}</header>
    : null
}
