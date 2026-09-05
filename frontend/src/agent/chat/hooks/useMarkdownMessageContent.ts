import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import { projectAgentMessageSections } from '../projectAgentMessageSections'
import type { AgentChatMessageContentPart } from '../types'

interface ProcessSessionRenderModelArgs {
  content: string
  contentParts?: AgentChatMessageContentPart[]
  display: 'markdown' | 'title'
  enableProcessSession: boolean
  hasReasoningContent: boolean
  hasProcessTiming: boolean
  isProcessActive: boolean
  showLoadingWhenEmpty: boolean
  shouldShowReasoningPanel: boolean
}

export interface ProcessSessionRenderModel {
  collapseBoundaryId: string | null
  hasInterleavedParts: boolean
  isWaitingForFirstToken: boolean
  hasVisibleContent: boolean
  hasVisibleInterleavedParts: boolean
  normalizedContentParts: AgentChatMessageContentPart[]
  processHasBody: boolean
  processParts: AgentChatMessageContentPart[]
  shouldRenderProcessSession: boolean
  shouldRenderStandaloneLoading: boolean
  shouldRenderStandaloneReasoningInProcess: boolean
  shouldRenderStandaloneReasoningOutside: boolean
  visibleContent: string
  visibleContentParts: AgentChatMessageContentPart[]
}

function toValidTimestamp(value: string | null | undefined): number | null {
  if (!value) {
    return null
  }
  const timestamp = Date.parse(value)
  return Number.isNaN(timestamp) ? null : timestamp
}

function formatElapsedDuration(elapsedMs: number): string {
  const totalSeconds = Math.max(0, Math.floor(elapsedMs / 1000))
  if (totalSeconds === 0) {
    return ''
  }

  if (totalSeconds < 60) {
    return `${totalSeconds} s`
  }

  const minutes = Math.floor(totalSeconds / 60)
  const seconds = totalSeconds % 60
  return `${minutes}m ${seconds}s`
}

interface ProcessSessionBlockStateArgs {
  collapseBoundaryId: string | null
  endedAt?: string | null
  isStreaming: boolean
  startedAt?: string | null
}

export function useProcessSessionBlockState({
  collapseBoundaryId,
  endedAt,
  isStreaming,
  startedAt,
}: ProcessSessionBlockStateArgs) {
  const startedAtMs = toValidTimestamp(startedAt)
  const endedAtMs = toValidTimestamp(endedAt)
  const [expandedBoundaryId, setExpandedBoundaryId] = useState<string | null>(null)
  const isCollapsible = collapseBoundaryId !== null
  const isOpen = !isCollapsible || expandedBoundaryId === collapseBoundaryId
  const setIsOpen = (open: boolean) => setExpandedBoundaryId(open ? collapseBoundaryId : null)
  const [elapsedMs, setElapsedMs] = useState(() => {
    if (!startedAtMs) {
      return 0
    }
    return (endedAtMs ?? Date.now()) - startedAtMs
  })

  useEffect(() => {
    if (!startedAtMs) {
      return
    }

    const resolveElapsedMs = () => (endedAtMs ?? Date.now()) - startedAtMs
    const frameId = window.requestAnimationFrame(() => {
      setElapsedMs(resolveElapsedMs())
    })

    if (endedAtMs !== null || !isStreaming) {
      return () => {
        window.cancelAnimationFrame(frameId)
      }
    }

    const intervalId = window.setInterval(() => {
      setElapsedMs(resolveElapsedMs())
    }, 1000)

    return () => {
      window.cancelAnimationFrame(frameId)
      window.clearInterval(intervalId)
    }
  }, [endedAtMs, isStreaming, startedAtMs])

  const elapsedDuration = formatElapsedDuration(elapsedMs)

  return {
    isCollapsible,
    openState: isOpen,
    setIsOpen,
    elapsedDuration,
  }
}

export function useProcessSessionRenderModel({
  content,
  contentParts,
  display,
  enableProcessSession,
  hasReasoningContent,
  hasProcessTiming,
  isProcessActive,
  showLoadingWhenEmpty,
  shouldShowReasoningPanel,
}: ProcessSessionRenderModelArgs): ProcessSessionRenderModel {
  const sections = useMemo(
    () => projectAgentMessageSections(contentParts ?? []),
    [contentParts],
  )
  const normalizedContentParts = sections.normalizedParts
  const hasInterleavedParts = normalizedContentParts.length > 0
  const hasInterleavedReasoningParts = normalizedContentParts.some(
    (part) => part.kind === 'reasoning',
  )
  const shouldRenderProcessSession =
    display === 'markdown' &&
    enableProcessSession &&
    (isProcessActive || showLoadingWhenEmpty || hasProcessTiming ||
      hasReasoningContent || sections.processParts.length > 0)
  const isWaitingForFirstToken = shouldRenderProcessSession &&
    (isProcessActive || showLoadingWhenEmpty) &&
    !hasInterleavedParts && !content.trim() && !hasReasoningContent
  const processParts = shouldRenderProcessSession ? sections.processParts : []
  const visibleContent = hasInterleavedParts ? '' : content
  const visibleContentParts = hasInterleavedParts
    ? shouldRenderProcessSession
      ? sections.visibleParts
      : normalizedContentParts
    : []
  const hasVisibleContent = visibleContent.trim().length > 0
  const hasVisibleInterleavedParts = visibleContentParts.length > 0
  const shouldRenderStandaloneReasoningInProcess =
    shouldRenderProcessSession && !hasInterleavedReasoningParts && shouldShowReasoningPanel
  const shouldRenderStandaloneReasoningOutside =
    shouldShowReasoningPanel &&
    !hasInterleavedReasoningParts &&
    !shouldRenderStandaloneReasoningInProcess
  const processHasBody =
    processParts.length > 0 ||
    shouldRenderStandaloneReasoningInProcess
  const shouldRenderStandaloneLoading =
    !shouldRenderProcessSession &&
    !hasVisibleInterleavedParts &&
    !hasVisibleContent &&
    showLoadingWhenEmpty

  return {
    collapseBoundaryId: shouldRenderProcessSession && processHasBody
      ? sections.visibleBoundaryId ?? (hasVisibleContent ? 'standalone-content' : null)
      : null,
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
  }
}

interface StandaloneReasoningExpansionArgs {
  hasContent: boolean
  hasInterleavedParts: boolean
  hasReasoningContent: boolean
  suppressReasoningAutoExpand: boolean
}

export function useStandaloneReasoningExpansion({
  hasContent,
  hasInterleavedParts,
  hasReasoningContent,
  suppressReasoningAutoExpand,
}: StandaloneReasoningExpansionArgs) {
  const hasAutoCollapsedReasoningRef = useRef(false)
  const [isReasoningExpanded, setIsReasoningExpanded] = useState(false)

  useEffect(() => {
    let frameId: number | null = null

    if (!hasReasoningContent) {
      hasAutoCollapsedReasoningRef.current = false
      frameId = window.requestAnimationFrame(() => {
        setIsReasoningExpanded(false)
      })
    } else if (!hasContent && !suppressReasoningAutoExpand) {
      hasAutoCollapsedReasoningRef.current = false
      frameId = window.requestAnimationFrame(() => {
        setIsReasoningExpanded(true)
      })
    } else if (!hasAutoCollapsedReasoningRef.current) {
      hasAutoCollapsedReasoningRef.current = true
      frameId = window.requestAnimationFrame(() => {
        setIsReasoningExpanded(false)
      })
    }

    return () => {
      if (frameId !== null) {
        window.cancelAnimationFrame(frameId)
      }
    }
  }, [hasContent, hasInterleavedParts, hasReasoningContent, suppressReasoningAutoExpand])

  return {
    isReasoningExpanded,
    setIsReasoningExpanded,
  }
}

interface InterleavedReasoningExpansionArgs {
  hasInterleavedParts: boolean
  isProcessActive: boolean
  normalizedContentParts: AgentChatMessageContentPart[]
  suppressReasoningAutoExpand: boolean
}

export function useInterleavedReasoningExpansion({
  hasInterleavedParts,
  isProcessActive,
  normalizedContentParts,
  suppressReasoningAutoExpand,
}: InterleavedReasoningExpansionArgs) {
  const touchedReasoningPartIdsRef = useRef<Set<string>>(new Set())
  const [openReasoningPartIds, setOpenReasoningPartIds] = useState<Record<string, boolean>>({})

  useEffect(() => {
    let frameId: number | null = null

    if (!hasInterleavedParts) {
      touchedReasoningPartIdsRef.current.clear()
      frameId = window.requestAnimationFrame(() => {
        setOpenReasoningPartIds({})
      })

      return () => {
        if (frameId !== null) {
          window.cancelAnimationFrame(frameId)
        }
      }
    }

    const reasoningPartIds = new Set(
      normalizedContentParts
        .filter((part) => part.kind === 'reasoning')
        .map((part) => part.id),
    )
    const lastPart = normalizedContentParts[normalizedContentParts.length - 1]
    frameId = window.requestAnimationFrame(() => {
      setOpenReasoningPartIds((current) => {
        const next: Record<string, boolean> = {}
        normalizedContentParts.forEach((part) => {
          if (part.kind !== 'reasoning') {
            return
          }
          const wasTouched = touchedReasoningPartIdsRef.current.has(part.id)
          next[part.id] = wasTouched
            ? current[part.id] ?? false
            : !suppressReasoningAutoExpand && isProcessActive && lastPart?.id === part.id
        })
        return next
      })
    })

    touchedReasoningPartIdsRef.current.forEach((partId) => {
      if (!reasoningPartIds.has(partId)) {
        touchedReasoningPartIdsRef.current.delete(partId)
      }
    })

    return () => {
      if (frameId !== null) {
        window.cancelAnimationFrame(frameId)
      }
    }
  }, [hasInterleavedParts, isProcessActive, normalizedContentParts, suppressReasoningAutoExpand])

  const setReasoningPartOpen = useCallback((partId: string, open: boolean) => {
    touchedReasoningPartIdsRef.current.add(partId)
    setOpenReasoningPartIds((current) => ({
      ...current,
      [partId]: open,
    }))
  }, [])

  return {
    openReasoningPartIds,
    setReasoningPartOpen,
  }
}

interface ToolCallExpansionArgs {
  hasInterleavedParts: boolean
  normalizedContentParts: AgentChatMessageContentPart[]
}

export function useToolCallExpansion({
  hasInterleavedParts,
  normalizedContentParts,
}: ToolCallExpansionArgs) {
  const [openToolCallPartIds, setOpenToolCallPartIds] = useState<Record<string, boolean>>({})

  useEffect(() => {
    let frameId: number | null = null

    if (!hasInterleavedParts) {
      frameId = window.requestAnimationFrame(() => {
        setOpenToolCallPartIds({})
      })

      return () => {
        if (frameId !== null) {
          window.cancelAnimationFrame(frameId)
        }
      }
    }

    const toolCallPartIds = new Set(
      normalizedContentParts
        .filter((part) => part.kind === 'tool_call')
        .map((part) => part.id),
    )
    frameId = window.requestAnimationFrame(() => {
      setOpenToolCallPartIds((current) => {
        const next: Record<string, boolean> = {}
        toolCallPartIds.forEach((partId) => {
          next[partId] = current[partId] ?? false
        })
        return next
      })
    })

    return () => {
      if (frameId !== null) {
        window.cancelAnimationFrame(frameId)
      }
    }
  }, [hasInterleavedParts, normalizedContentParts])

  const setToolCallPartOpen = useCallback((partId: string, open: boolean) => {
    setOpenToolCallPartIds((current) => ({
      ...current,
      [partId]: open,
    }))
  }, [])

  return {
    openToolCallPartIds,
    setToolCallPartOpen,
  }
}
