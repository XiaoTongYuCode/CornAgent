import { Component, RotateCwSquare, type LucideIcon } from 'lucide-react'
import { TextSwap } from '../../components/TextSwap'
import { useI18n } from '../../i18n'
import { subagentMetadata } from '../types'
import { SubagentTaskPart, SubagentControlPart, SUBAGENT_CONTROL_KEYS } from './SubagentTaskPart'
import type { Dispatch, ReactNode, SetStateAction } from 'react'

import { CollapsibleContent } from './CollapsibleContent'
import { getCollapsibleTitleIcon } from './collapsibleTitleIcon'
import {
  MarkdownRenderer,
  type AgentMarkdownLinkHandlers,
  type MarkdownVariant,
} from './markdown/MarkdownRenderer'
import {
  getActiveToolCallPartId,
  getCompanyEntityLookupDisplay,
  getStreamingGroupTitleInGroup,
  hasFollowingContentAfterGroup,
  isFailedToolCallPart,
  isStreamingTitle,
  resolveCollapsibleGroupTitle,
  resolveToolCallDisplayTitle,
} from './messageRenderGroupTitle'
import { getToolApprovalDisplay } from './toolApprovalDisplay'
import { normalizeReasoningValue } from './utils/reasoningValue'
import { ToolRunGroup } from './ToolRunGroup'
import { UserQuestionPart } from './UserQuestionPart'
import { useProcessSessionBlockState } from './hooks/useMarkdownMessageContent'
import type { AgentChatMessageContentPart } from './types'
import { resolveAgentReasoningPartTitle } from './utils/agentReasoningTitle'
import type {
  MessageRenderGroupItem,
  MessageRenderPlanItem,
} from './utils/messageRenderPlan'

interface ProcessSessionBlockProps {
  children: ReactNode
  collapseBoundaryId: string | null
  endedAt?: string | null
  isStreaming: boolean
  isWaitingForFirstToken: boolean
  startedAt?: string | null
}

interface StandaloneReasoningPanelProps {
  isReasoningExpanded: boolean
  isReasoningStreaming: boolean
  normalizedReasoningContent: string
  normalizedReasoningTitle: string
  setIsReasoningExpanded: Dispatch<SetStateAction<boolean>>
}

interface MessageRenderPlanContentProps extends AgentMarkdownLinkHandlers {
  activeReasoningPartId: string | null
  fontSize: number
  isMessageStreaming: boolean
  isProcessActive: boolean
  normalizedContentParts: AgentChatMessageContentPart[]
  openReasoningPartIds: Record<string, boolean>
  openToolCallPartIds: Record<string, boolean>
  parts: AgentChatMessageContentPart[]
  plan: MessageRenderPlanItem[]
  setReasoningPartOpen: (partId: string, open: boolean) => void
  setToolCallPartOpen: (partId: string, open: boolean) => void
  variant: MarkdownVariant
}

function getReasoningPanelTitle(title: string): string {
  return title || '深度思考'
}

export function ProcessSessionBlock({
  children,
  collapseBoundaryId,
  endedAt,
  isStreaming,
  isWaitingForFirstToken,
  startedAt,
}: ProcessSessionBlockProps) {
  const { t } = useI18n()
  const { isCollapsible, openState, setIsOpen, elapsedDuration } = useProcessSessionBlockState({
    collapseBoundaryId,
    endedAt,
    isStreaming,
    startedAt,
  })

  return (
    <CollapsibleContent
      bodyClassName="chat-markdown-message-content__process-body"
      className={`chat-markdown-message-content__process${isWaitingForFirstToken ? ' chat-markdown-message-content__process--waiting' : ''}`}
      collapsible={isCollapsible}
      content=""
      fontSize={14}
      onClose={() => { setIsOpen(false) }}
      onOpen={() => { setIsOpen(true) }}
      open={openState}
      scrollable={false}
      title={<span className="chat-markdown-message-content__process-status">
        <TextSwap text={t(isWaitingForFirstToken ? 'thinking' : 'processed')} shimmer={isWaitingForFirstToken} durationMs={50} />
        {!isWaitingForFirstToken && elapsedDuration && <span>{elapsedDuration}</span>}
      </span>}
      titleIcon={null}
      variant="chat"
    >
      {children}
    </CollapsibleContent>
  )
}

export function StandaloneReasoningPanel({
  isReasoningExpanded,
  isReasoningStreaming,
  normalizedReasoningContent,
  normalizedReasoningTitle,
  setIsReasoningExpanded,
}: StandaloneReasoningPanelProps) {
  const displayTitle = resolveAgentReasoningPartTitle(
    normalizedReasoningTitle,
    isReasoningStreaming,
  )
  return (
    <CollapsibleContent
      bodyClassName="chat-markdown-message-content__reasoning-body"
      className="chat-markdown-message-content__reasoning"
      content={normalizedReasoningContent}
      enableEnterAnimation
      fontSize={12}
      onClose={() => { setIsReasoningExpanded(false) }}
      onOpen={() => { setIsReasoningExpanded(true) }}
      open={isReasoningExpanded}
      scrollable
      streaming={isReasoningStreaming}
      title={getReasoningPanelTitle(displayTitle)}
      titleStreaming={isReasoningStreaming && isStreamingTitle(displayTitle)}
      variant="chat"
    />
  )
}

export function MessageRenderPlanContent({
  activeReasoningPartId,
  fontSize,
  isMessageStreaming,
  isProcessActive,
  normalizedContentParts,
  onLinkClick,
  openReasoningPartIds,
  openToolCallPartIds,
  parts,
  plan,
  setReasoningPartOpen,
  setToolCallPartOpen,
  variant,
}: MessageRenderPlanContentProps) {
  const renderMarkdownValue = (value: string) => (
    <MarkdownRenderer
      fontSize={fontSize}
      onLinkClick={onLinkClick}
      streaming={isMessageStreaming}
      value={value}
      variant={variant}
    />
  )

  const activeToolCallPartId = getActiveToolCallPartId(parts, isProcessActive)

  const renderMarkdownPart = (part: AgentChatMessageContentPart) => (
    <div className="chat-markdown-message-content__part" key={part.id}>
      {renderMarkdownValue(part.content)}
    </div>
  )

  const renderReasoningPart = (part: AgentChatMessageContentPart, index: number) => {
    const isPartStreaming = activeReasoningPartId === part.id
    const partTitle = normalizeReasoningValue(
      resolveAgentReasoningPartTitle(part.title, isPartStreaming),
    )
    const isPartOpen = Boolean(openReasoningPartIds[part.id])
    return (
      <CollapsibleContent
        bodyClassName="chat-markdown-message-content__reasoning-body"
        className={[
          'chat-markdown-message-content__reasoning',
          index > 0 && 'chat-markdown-message-content__reasoning--interleaved',
        ].filter(Boolean).join(' ')}
        content={part.content}
        enableEnterAnimation
        fontSize={12}
        key={part.id}
        onClose={() => { setReasoningPartOpen(part.id, false) }}
        onOpen={() => { setReasoningPartOpen(part.id, true) }}
        open={isPartOpen}
        scrollable
        streaming={isPartStreaming}
        title={getReasoningPanelTitle(partTitle)}
        titleStreaming={isPartStreaming && isStreamingTitle(partTitle)}
        variant="chat"
      />
    )
  }

  const renderToolCallPart = (part: AgentChatMessageContentPart, index: number) => {
    if (subagentMetadata(part)) return <SubagentTaskPart key={part.id} part={part}
      open={Boolean(openToolCallPartIds[part.id])} setOpen={(open) => setToolCallPartOpen(part.id, open)} />
    if (Object.hasOwn(SUBAGENT_CONTROL_KEYS, String(part.metadata?.tool_name))) {
      return <SubagentControlPart key={part.id} part={part}
        open={Boolean(openToolCallPartIds[part.id])} setOpen={(open) => setToolCallPartOpen(part.id, open)} />
    }
    const isPartOpen = Boolean(openToolCallPartIds[part.id])
    const approvalDisplay = getToolApprovalDisplay(part.metadata)
    const companyLookupDisplay = getCompanyEntityLookupDisplay(part)
    const isPartActive = activeToolCallPartId === part.id
    const displayTitle = companyLookupDisplay?.title ?? resolveToolCallDisplayTitle(part, isPartActive)
    const baseContent = approvalDisplay?.content ?? part.content
    const displayContent = companyLookupDisplay?.content
      ? `${companyLookupDisplay.content}\n\n${baseContent}`
      : baseContent
    const isFailedToolCall = isFailedToolCallPart(part, displayTitle)
    return (
      <CollapsibleContent
        bodyClassName="chat-markdown-message-content__tool-body"
        className={[
          'chat-markdown-message-content__tool',
          index > 0 && 'chat-markdown-message-content__tool--interleaved',
          isFailedToolCall && 'chat-markdown-message-content__tool--failed',
        ].filter(Boolean).join(' ')}
        content={displayContent}
        enableEnterAnimation
        fontSize={12}
        key={part.id}
        onClose={() => { setToolCallPartOpen(part.id, false) }}
        onOpen={() => { setToolCallPartOpen(part.id, true) }}
        open={Boolean(approvalDisplay) || isPartOpen}
        scrollable
        title={displayTitle}
        titleTransition
        titleClassName={isFailedToolCall ? 'chat-markdown-message-content__tool-title--failed' : ''}
        titleStreaming={!isFailedToolCall && isPartActive && isStreamingTitle(displayTitle)}
        titleIcon={getCollapsibleTitleIcon(displayTitle)}
        variant="chat"
      />
    )
  }

  const getContentPartTitleIcon = (part: AgentChatMessageContentPart): LucideIcon | null => {
    if (part.kind === 'reasoning') {
      const partTitle = normalizeReasoningValue(
        resolveAgentReasoningPartTitle(part.title, activeReasoningPartId === part.id),
      )
      return getCollapsibleTitleIcon(getReasoningPanelTitle(partTitle))
    }
    if (part.kind === 'tool_call') {
      if (part.metadata?.subagent === true) return Component
      if (part.metadata?.tool_name === 'wait_subagents') return RotateCwSquare
      if (Object.hasOwn(SUBAGENT_CONTROL_KEYS, String(part.metadata?.tool_name))) return Component
      return getCollapsibleTitleIcon(
        resolveToolCallDisplayTitle(part, activeToolCallPartId === part.id),
      )
    }
    return null
  }

  const getGroupTitleIcon = (
    item: MessageRenderGroupItem,
    nextParts: AgentChatMessageContentPart[],
  ): LucideIcon | null => {
    const iconCounts = new Map<LucideIcon, number>()
    const iconOrder: LucideIcon[] = []
    item.indexes.forEach((partIndex) => {
      const part = nextParts[partIndex]
      const Icon = part ? getContentPartTitleIcon(part) : null
      if (!Icon) return
      if (!iconCounts.has(Icon)) iconOrder.push(Icon)
      iconCounts.set(Icon, (iconCounts.get(Icon) ?? 0) + 1)
    })
    return iconOrder.reduce<LucideIcon | null>((bestIcon, Icon) => {
      if (!bestIcon) return Icon
      return (iconCounts.get(Icon) ?? 0) > (iconCounts.get(bestIcon) ?? 0) ? Icon : bestIcon
    }, null)
  }

  const renderContentPart = (
    part: AgentChatMessageContentPart,
    displayIndex: number,
  ) => {
    if (part.kind === 'reasoning') return renderReasoningPart(part, displayIndex)
    if (part.kind === 'tool_call') return renderToolCallPart(part, displayIndex)
    if (part.kind === 'user_question') {
      return <UserQuestionPart display="message" key={part.id} part={part} />
    }
    return renderMarkdownPart(part)
  }

  return (
    <>
      {plan.map((item) => {
        if (item.kind === 'part') {
          const part = parts[item.index]
          return part ? renderContentPart(part, item.index) : null
        }

        const hasFollowingContent = hasFollowingContentAfterGroup(
          item,
          parts,
          normalizedContentParts,
        )
        const streamingGroupTitle = isProcessActive && !hasFollowingContent
          ? getStreamingGroupTitleInGroup(item, parts, true)
          : null
        const groupTitle = resolveCollapsibleGroupTitle(item, parts, {
          hasFollowingContent,
          isProcessActive,
        })
        const groupTitleIcon = streamingGroupTitle
          ? getCollapsibleTitleIcon(streamingGroupTitle)
          : getGroupTitleIcon(item, parts)
        return (
          <ToolRunGroup
            className="chat-markdown-message-content__collapsible-group"
            key={item.id}
            presentation={item.presentation}
            title={groupTitle}
            titleStreaming={Boolean(streamingGroupTitle)}
            titleIcon={groupTitleIcon}
          >
            {item.indexes.map((partIndex, displayIndex) => {
              const part = parts[partIndex]
              return part
                ? renderContentPart(part, displayIndex)
                : null
            })}
          </ToolRunGroup>
        )
      })}
    </>
  )
}
