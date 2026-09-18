import { useMemo } from 'react'
import { ArrowDown } from 'lucide-react'
import { useI18n } from '../i18n'
import { AgentMessageRow } from './chat/AgentMessageRow'
import { groupMessageTurns } from './chat/groupMessageTurns'
import { useConversationScroll } from './hooks/useConversationScroll'
import { activeLineage } from './types'
import type { AgentWorkspace } from './useAgentWorkspace'

export function AgentMessageList({ workspace }: { workspace: AgentWorkspace }) {
  const { t } = useI18n()
  const messages = workspace.session?.messages
  const activeLeafMessageId = workspace.session?.activeLeafMessageId
  const turns = useMemo(() => groupMessageTurns(activeLineage({
    messages: messages ?? [], activeLeafMessageId: activeLeafMessageId ?? null,
  })), [messages, activeLeafMessageId])
  const latestTurnId = turns.at(-1)?.id ?? ''
  const { viewportRef, contentRef, atBottom, onScroll, loadOlderWithAnchor, followLatest } = useConversationScroll({
    sessionId: workspace.session?.id ?? '',
    turnId: latestTurnId,
    loadOlder: workspace.loadOlder,
  })
  const currentRun = workspace.snapshot?.run ?? workspace.session?.activeRun
  const runActive = Boolean(currentRun && !['completed', 'failed', 'cancelled'].includes(currentRun.status))

  return <div className="chat-message-list-shell">
    <div
      className="chat-message-list__viewport chat-message-list__viewport--scrollbar-hidden"
      onScroll={onScroll}
      ref={viewportRef}
    >
      <div className="chat-message-list" ref={contentRef}>
        {workspace.session?.nextBefore && <button
          className="chat-message-list__load-older"
          disabled={workspace.loadingOlder}
          onClick={() => void loadOlderWithAnchor()}
          type="button"
        >
          {t(workspace.loadingOlder ? 'loading' : 'loadOlder')}
        </button>}
        {turns.map((turn) => <div
          className={`chat-message-list__exchange${turn.id === latestTurnId ? ' chat-message-list__exchange--latest' : ''}`}
          data-conversation-turn-id={turn.id}
          key={turn.id}
        >
          {turn.messages.map((message) => <AgentMessageRow
            key={message.id}
            message={message}
            run={currentRun?.assistantMessageId === message.id ? currentRun : null}
            snapshot={workspace.snapshot?.run.assistantMessageId === message.id ? workspace.snapshot : null}
            disabled={Boolean(workspace.busy || runActive)}
            onEdit={workspace.edit}
            onRegenerate={workspace.regenerate}
            onSwitch={workspace.switchVersion}
          />)}
        </div>)}
      </div>
    </div>
    {!atBottom && <button className="chat-message-list__scroll-to-bottom" type="button" aria-label={t('scrollBottom')} onClick={followLatest}><ArrowDown size={16} /></button>}
  </div>
}
