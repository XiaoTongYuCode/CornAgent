import { localizeSystemMessage } from '../../i18n/systemMessages'
import { useI18n } from '../../i18n'
import { ChatItem, LoadingDots } from '@lobehub/ui/chat'
import { useEffect, useMemo, useRef } from 'react'

import { celebrateAgentOutput } from '../agentCelebration'
import type { AgentMessage } from '../types'
import type { AgentWorkspace } from '../useAgentWorkspace'
import { MarkdownMessageContent } from './MarkdownMessageContent'
import { AssistantMessageActions } from './MessageActions'
import { UserMessage } from './UserMessage'
import { projectDesktopContentParts } from './projectDesktopContentParts'
import { getVisibleAssistantMarkdown } from './projectAgentMessageSections'

interface AgentMessageRowProps {
  message: AgentMessage
  runActive: boolean
  workspace: AgentWorkspace
}

export function AgentMessageRow({ message, runActive, workspace }: AgentMessageRowProps) {
  const { t, locale } = useI18n()
  const currentRun = workspace.snapshot?.run ?? workspace.session?.activeRun
  const runningThisMessage = currentRun?.assistantMessageId === message.id
  const streaming = Boolean(runningThisMessage && runActive)
  const content = runningThisMessage && workspace.snapshot
    ? workspace.snapshot.draftMarkdown
    : message.markdown
  const rawParts = runningThisMessage && workspace.snapshot
    ? workspace.snapshot.contentParts
    : message.contentParts
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
      && runningThisMessage
      && currentRun?.status === 'completed'
    wasStreaming.current = streaming
    if (!justCompleted || !copyContent.includes('🎉')) return
    return celebrateAgentOutput()
  }, [copyContent, currentRun?.id, currentRun?.status, runningThisMessage, streaming])

  if (message.role === 'user') {
    return <UserMessage message={message} disabled={Boolean(workspace.busy || runActive)} workspace={workspace} />
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
              disabled={Boolean(workspace.busy || runActive)}
              onRegenerate={() => workspace.regenerate(message.id)}
              onSwitch={workspace.switchVersion}
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
            reasoningContent={runningThisMessage ? workspace.snapshot?.reasoningMarkdown : null}
            reasoningTitle={isProcessActive ? '正在思考' : null}
            showLoadingWhenEmpty={showLoading}
            variant="chat"
          />
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
}
