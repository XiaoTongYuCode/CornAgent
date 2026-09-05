import { LoadingDots } from '@lobehub/ui/chat'
import { Typography } from 'antd'
import { AnimatePresence } from 'motion/react'
import { AnimatedMessageBody } from './AnimatedMessageBody'
import { memo, useMemo } from 'react'

import {
  MessageRenderPlanContent,
  ProcessSessionBlock,
  StandaloneReasoningPanel,
} from './MessageContentPartRenderer'
import {
  MarkdownRenderer,
  type MarkdownVariant,
} from './markdown/MarkdownRenderer'
import type { AgentMarkdownLinkPayload } from './markdown/MarkdownRenderer'
import {
  useInterleavedReasoningExpansion,
  useProcessSessionRenderModel,
  useStandaloneReasoningExpansion,
  useToolCallExpansion,
} from './hooks/useMarkdownMessageContent'
import type { AgentChatMessageContentPart } from './types'
import {
  getActiveAgentReasoningPartId,
  isStandaloneAgentReasoningActive,
} from './utils/agentReasoningTitle'
import { createMessageRenderPlan } from './utils/messageRenderPlan'
import { normalizeReasoningValue } from './utils/reasoningValue'

type MessageContentDisplay = 'markdown' | 'title'
const COMPACT_TITLE_LENGTH_THRESHOLD = 20

interface MarkdownMessageContentProps {
  content: string
  contentParts?: AgentChatMessageContentPart[]
  reasoningContent?: string | null
  reasoningTitle?: string | null
  isMessageStreaming?: boolean
  isProcessActive?: boolean
  variant?: MarkdownVariant
  fontSize?: number
  className?: string
  display?: MessageContentDisplay
  showLoadingWhenEmpty?: boolean
  suppressReasoningAutoExpand?: boolean
  enableProcessSession?: boolean
  processSessionStartedAt?: string | null
  processSessionEndedAt?: string | null
  onLinkClick?: (payload: AgentMarkdownLinkPayload) => void
}

export const MarkdownMessageContent = memo(function MarkdownMessageContent({
  content,
  contentParts,
  reasoningContent = null,
  reasoningTitle = null,
  isMessageStreaming = false,
  isProcessActive = false,
  variant = 'chat',
  fontSize = 16,
  className,
  display = 'markdown',
  showLoadingWhenEmpty = false,
  suppressReasoningAutoExpand = false,
  enableProcessSession = false,
  processSessionStartedAt = null,
  processSessionEndedAt = null,
  onLinkClick,
}: MarkdownMessageContentProps) {
  const normalizedContent = content.trim()
  const hasContent = normalizedContent.length > 0
  const shouldUseCompactTitle =
    display === 'title' && Array.from(normalizedContent).length >= COMPACT_TITLE_LENGTH_THRESHOLD
  const normalizedReasoningContent = normalizeReasoningValue(reasoningContent)
  const normalizedReasoningTitle = normalizeReasoningValue(reasoningTitle)
  const hasReasoningContent = normalizedReasoningContent.length > 0
  const shouldShowReasoningPanel =
    hasReasoningContent || (!enableProcessSession && isProcessActive && normalizedReasoningTitle.length > 0)
  const {
    collapseBoundaryId,
    hasInterleavedParts,
    isWaitingForFirstToken,
    hasVisibleContent,
    hasVisibleInterleavedParts,
    normalizedContentParts,
    processHasBody,
    processParts,
    shouldRenderProcessSession,
    shouldRenderStandaloneLoading,
    shouldRenderStandaloneReasoningInProcess,
    shouldRenderStandaloneReasoningOutside,
    visibleContent,
    visibleContentParts,
  } = useProcessSessionRenderModel({
    content,
    contentParts,
    display,
    enableProcessSession,
    hasReasoningContent,
    hasProcessTiming: Boolean(processSessionStartedAt || processSessionEndedAt),
    isProcessActive,
    showLoadingWhenEmpty,
    shouldShowReasoningPanel,
  })
  const { isReasoningExpanded, setIsReasoningExpanded } = useStandaloneReasoningExpansion({
    hasContent,
    hasInterleavedParts,
    hasReasoningContent,
    suppressReasoningAutoExpand,
  })
  const { openReasoningPartIds, setReasoningPartOpen } = useInterleavedReasoningExpansion({
    hasInterleavedParts,
    isProcessActive,
    normalizedContentParts,
    suppressReasoningAutoExpand,
  })
  const { openToolCallPartIds, setToolCallPartOpen } = useToolCallExpansion({
    hasInterleavedParts,
    normalizedContentParts,
  })
  const processRenderPlan = useMemo(
    () => createMessageRenderPlan(processParts),
    [processParts],
  )
  const visibleRenderPlan = useMemo(
    () => createMessageRenderPlan(visibleContentParts),
    [visibleContentParts],
  )
  const activeReasoningPartId = getActiveAgentReasoningPartId(
    normalizedContentParts,
    isProcessActive,
  )
  const isStandaloneReasoningStreaming = isStandaloneAgentReasoningActive(
    normalizedContentParts,
    isProcessActive,
    hasContent,
  )

  const renderMarkdownValue = (value: string) => (
    <MarkdownRenderer
      fontSize={fontSize}
      onLinkClick={onLinkClick}
      streaming={isMessageStreaming}
      value={value}
      variant={variant}
    />
  )

  const renderStandaloneReasoningPanel = () => (
    <StandaloneReasoningPanel
      isReasoningExpanded={isReasoningExpanded}
      isReasoningStreaming={isStandaloneReasoningStreaming}
      normalizedReasoningContent={normalizedReasoningContent}
      normalizedReasoningTitle={normalizedReasoningTitle}
      setIsReasoningExpanded={setIsReasoningExpanded}
    />
  )

  const renderPlanContent = (
    plan: ReturnType<typeof createMessageRenderPlan>,
    parts: AgentChatMessageContentPart[],
  ) => (
    <MessageRenderPlanContent
      activeReasoningPartId={activeReasoningPartId}
      fontSize={fontSize}
      isMessageStreaming={isMessageStreaming}
      isProcessActive={isProcessActive}
      normalizedContentParts={normalizedContentParts}
      openReasoningPartIds={openReasoningPartIds}
      openToolCallPartIds={openToolCallPartIds}
      onLinkClick={onLinkClick}
      parts={parts}
      plan={plan}
      setReasoningPartOpen={setReasoningPartOpen}
      setToolCallPartOpen={setToolCallPartOpen}
      variant={variant}
    />
  )

  const processBody = processHasBody ? (
    <>
      {renderPlanContent(processRenderPlan, processParts)}
      {shouldRenderStandaloneReasoningInProcess ? renderStandaloneReasoningPanel() : null}
    </>
  ) : null

  const visibleBody = hasVisibleInterleavedParts ? (
    renderPlanContent(visibleRenderPlan, visibleContentParts)
  ) : shouldRenderStandaloneReasoningOutside ? (
    renderStandaloneReasoningPanel()
  ) : !hasInterleavedParts && hasContent && display === 'title' ? (
    <Typography.Title
      className={
        shouldUseCompactTitle
          ? 'chat-markdown-message-content__title chat-markdown-message-content__title--compact'
          : 'chat-markdown-message-content__title'
      }
      level={3}
    >
      {normalizedContent}
    </Typography.Title>
  ) : !hasVisibleInterleavedParts && hasVisibleContent ? (
    renderMarkdownValue(visibleContent)
  ) : shouldRenderStandaloneLoading ? (
    <LoadingDots size={6} style={{ padding: '10px 0' }} />
  ) : null

  const shouldAnimateVisibleBody = Boolean(
    shouldRenderProcessSession && collapseBoundaryId && visibleBody,
  )

  return (
    <div className={['chat-markdown-message-content', className].filter(Boolean).join(' ')}>
      {shouldRenderProcessSession ? (
        <ProcessSessionBlock
          collapseBoundaryId={collapseBoundaryId}
          endedAt={processSessionEndedAt}
          isStreaming={isProcessActive}
          isWaitingForFirstToken={isWaitingForFirstToken}
          startedAt={processSessionStartedAt}
        >
          {processBody}
        </ProcessSessionBlock>
      ) : null}
      {shouldAnimateVisibleBody ? (
        <AnimatePresence initial={false}>
          <AnimatedMessageBody
            className="chat-markdown-message-content__visible"
            key={collapseBoundaryId}
          >
            {visibleBody}
          </AnimatedMessageBody>
        </AnimatePresence>
      ) : visibleBody}
    </div>
  )
})
