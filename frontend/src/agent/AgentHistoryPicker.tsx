import { useI18n } from '../i18n'
import { MessagesSquare, History } from 'lucide-react'

import { AttioSearchSelectPopover } from '../components/primitives/AttioSearchSelectPopover'
import type { AgentSession, AgentSessionPage } from './types'

interface AgentHistoryPickerProps {
  currentSessionId: string | null
  disabled: boolean
  loadingMore: boolean
  nextCursor: string | null
  sessions: AgentSession[]
  loadMore(): Promise<void>
  search(query: string, cursor?: string | null): Promise<AgentSessionPage>
  onSessionChange(sessionId: string): void
}

export function AgentHistoryPicker({
  currentSessionId,
  disabled,
  loadingMore,
  nextCursor,
  sessions,
  loadMore,
  search,
  onSessionChange,
}: AgentHistoryPickerProps) {
  const { t } = useI18n()
  return <AttioSearchSelectPopover
    ariaLabel={t('searchHistory')}
    disabled={disabled}
    emptyText={t('noMatchingChats')}
    icon={<History size={16} strokeWidth={1.75} aria-hidden="true" />}
    multiple={false}
    loadingMoreOptions={loadingMore}
    loadingText={t('loading')}
    loadMoreText={t('loadMoreChats')}
    onLoadMoreOptions={loadMore}
    onChange={([sessionId]) => {
      if (sessionId) onSessionChange(sessionId)
    }}
    options={sessions.map((session) => ({
      value: session.id,
      label: session.title,
      icon: <MessagesSquare size={16} strokeWidth={1.75} aria-hidden="true" />,
    }))}
    optionsNextCursor={nextCursor}
    popupClassName="agent-history-popover"
    searchPlaceholder={t('searchHistoryPlaceholder')}
    searchOptions={async (query, cursor) => {
      const page = await search(query, cursor)
      return {
        data: page.data.map((item) => ({
          value: item.id,
          label: item.title,
          icon: <MessagesSquare size={16} strokeWidth={1.75} aria-hidden="true" />,
        })),
        nextCursor: page.nextCursor,
      }
    }}
    showSelectedChips={false}
    summary={t('conversationHistory')}
    triggerClassName="agent-history-trigger"
    values={currentSessionId ? [currentSessionId] : []}
  />
}
