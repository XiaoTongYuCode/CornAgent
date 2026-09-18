import { localizeSystemMessage } from '../../i18n/systemMessages'
import { useI18n } from '../../i18n'
import { ChatItem, LoadingDots } from '@lobehub/ui/chat'
import { memo, useEffect, useMemo, useRef } from 'react'

import { celebrateAgentOutput } from '../agentCelebration'
import type { AgentMessage, AgentRun, AgentSnapshot } from '../types'
import type { AgentWorkspace } from '../useAgentWorkspace'
import { MarkdownMessageContent } from './MarkdownMessageContent'
import { AssistantMessageActions } from './MessageActions'
import { UserMessage } from './UserMessage'
import { TurnChanges } from './TurnChanges'
import { projectDesktopContentParts } from './projectDesktopContentParts'
import { getVisibleAssistantMarkdown } from './projectAgentMessageSections'

interface AgentMessageRowProps {
  message: AgentMessage
  run: AgentRun | null
  snapshot: AgentSnapshot | null
  disabled: boolean
  onEdit: AgentWorkspace['edit']
  onRegenerate: AgentWorkspace['regenerate']
  onSwitch: AgentWorkspace['switchVersion']
}

export const AgentMessageRow = memo(function AgentMessageRow({ message, run, snapshot, disabled, onEdit, onRegenerate, onSwitch }: AgentMessageRowProps) {
  const { t, locale } = useI18n()
  const streaming = Boolean(run && !['completed', 'failed', 'cancelled'].includes(run.status))
  const content = snapshot?.draftMarkdown ?? message.markdown
  const rawParts = snapshot?.contentParts ?? message.contentParts
  const parts = useMemo(
    () => projectDesktopContentParts(rawParts),
    [rawParts],
  )
  const hasPendingQuestion = parts.some((part) => (
    part.kind === 'user_question' && part.metadata?.status === 'pending'
  ))
  const isProcessActive = streaming && !hasPendingQuestion
  const copyContent = getVisibleAssistantMarkdown(parts) || content.trim()
  const showLoading = streaming && !content.trim() && parts.length === 0
  const incompleteRun = message.run?.status === 'failed' || message.run?.status === 'cancelled'
    ? message.run
    : null
  const wasStreaming = useRef(streaming)

  useEffect(() => {
    const justCompleted = wasStreaming.current
      && !streaming
      && run?.status === 'completed'
    wasStreaming.current = streaming
    if (!justCompleted || !copyContent.includes('🎉')) return
    return celebrateAgentOutput()
  }, [copyContent, run?.id, run?.status, streaming])

  if (message.role === 'user') {
    return <UserMessage message={message} disabled={disabled} workspace={{ edit: onEdit, switchVersion: onSwitch }} />
  }

  return (
    <section
      className="chat-message-list__turn"
      data-message-turn-id={message.parentMessageId ?? message.id}
    >
      <ChatItem
        avatar={{ title: 'CornAgent' }}
        belowMessage={!streaming && message.processCompletedAt ? (
          <div className="chat-message-list__assistant-actions-visibility">
            <AssistantMessageActions
              copyContent={copyContent}
              message={message}
              disabled={disabled}
              onRegenerate={() => onRegenerate(message.id)}
              onSwitch={onSwitch}
            />
          </div>
        ) : undefined}
        className="chat-message-list__assistant-item"
        loading={streaming && !hasPendingQuestion && !showLoading}
        message={content || ' '}
        placement="left"
        renderMessage={() => <>
          <MarkdownMessageContent
            content={content}
            contentParts={parts}
            enableProcessSession
            fontSize={14}
            isMessageStreaming={streaming}
            isProcessActive={isProcessActive}
            processSessionEndedAt={message.processCompletedAt}
            processSessionStartedAt={message.processStartedAt}
            reasoningContent={snapshot?.reasoningMarkdown ?? null}
            reasoningTitle={isProcessActive ? '正在思考' : null}
            showLoadingWhenEmpty={showLoading}
            variant="chat"
          />
          <TurnChanges parts={rawParts} />
          {incompleteRun && <div className="chat-message-list__run-error" role="alert">
            <strong>{t(incompleteRun.status === 'cancelled' ? 'incompleteCancelled' : 'incomplete')}</strong>
            <span>{incompleteRun.errorMessage ? localizeSystemMessage(incompleteRun.errorMessage, locale) : (incompleteRun.status === 'cancelled'
              ? t('stoppedHelp')
              : t('failedHelp'))}</span>
          </div>}
        </>}
        showAvatar={false}
        showTitle={false}
        titleAddon={isProcessActive ? (
          <LoadingDots size={4} style={{ margin: '0 5px', padding: 0 }} variant="pulse" />
        ) : undefined}
        variant="docs"
      />
    </section>
  )
})
