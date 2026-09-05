import { useI18n } from '../i18n'
import { Plus, X } from '@phosphor-icons/react'
import { useCallback, useLayoutEffect, useRef, useState, type KeyboardEvent, type PointerEvent as ReactPointerEvent, type TransitionEvent as ReactTransitionEvent } from 'react'
import { AgentConversation } from './AgentConversation'
import { AgentHistoryPicker } from './AgentHistoryPicker'
import type { AgentWorkspace } from './useAgentWorkspace'

const MIN_AGENT_PANEL_WIDTH = 340
const MAX_AGENT_PANEL_WIDTH = 720
const AGENT_PANEL_WIDTH_STORAGE_KEY = 'cornagent:agent-panel-width'
const AGENT_PANEL_OPEN_DURATION_FALLBACK_MS = 400
const AGENT_PANEL_CLOSE_DURATION_FALLBACK_MS = 350

function cssDurationMs(value: string, fallback: number): number {
  const normalized = value.trim()
  const duration = Number.parseFloat(normalized)
  if (!Number.isFinite(duration)) return fallback
  return normalized.endsWith('ms') ? duration : duration * 1000
}

function clampPanelWidth(width: number): number {
  const viewportMaximum = typeof window === 'undefined'
    ? MAX_AGENT_PANEL_WIDTH
    : Math.max(MIN_AGENT_PANEL_WIDTH, Math.min(MAX_AGENT_PANEL_WIDTH, window.innerWidth - 480))
  return Math.min(viewportMaximum, Math.max(MIN_AGENT_PANEL_WIDTH, width))
}

function initialPanelWidth(): number {
  if (typeof window === 'undefined') return MIN_AGENT_PANEL_WIDTH
  try {
    const stored = Number(window.localStorage.getItem(AGENT_PANEL_WIDTH_STORAGE_KEY))
    return clampPanelWidth(Number.isFinite(stored) && stored > 0 ? stored : MIN_AGENT_PANEL_WIDTH)
  } catch {
    return MIN_AGENT_PANEL_WIDTH
  }
}

export function AgentPanel({ workspace, userName, layout = 'docked' }: { workspace: AgentWorkspace; userName?: string; layout?: 'overlay' | 'docked' }) {
  const { t } = useI18n()
  const [panelWidth, setPanelWidth] = useState(initialPanelWidth)
  const [panelOpen, setPanelOpen] = useState(false)
  const [layoutOpen, setLayoutOpen] = useState(false)
  const panelRef = useRef<HTMLElement>(null)
  const dragCleanupRef = useRef<(() => void) | null>(null)
  const motionFrameRef = useRef<number | null>(null)
  const openTimerRef = useRef<number | null>(null)
  const closeTimerRef = useRef<number | null>(null)
  const openSettledRef = useRef(false)
  const closePendingRef = useRef(false)
  const currentRun = workspace.snapshot?.run ?? workspace.session?.activeRun
  const active = Boolean(currentRun && !['completed', 'failed', 'cancelled'].includes(currentRun.status))

  const settleOpen = useCallback(() => {
    if (closePendingRef.current || openSettledRef.current) return
    openSettledRef.current = true
    if (openTimerRef.current !== null) {
      window.clearTimeout(openTimerRef.current)
      openTimerRef.current = null
    }
    setLayoutOpen(true)
  }, [])

  const finishClose = useCallback(() => {
    if (!closePendingRef.current) return
    closePendingRef.current = false
    if (closeTimerRef.current !== null) {
      window.clearTimeout(closeTimerRef.current)
      closeTimerRef.current = null
    }
    workspace.setOpen(false)
  }, [workspace])

  const requestClose = useCallback(() => {
    if (closePendingRef.current) return
    closePendingRef.current = true
    dragCleanupRef.current?.()
    setLayoutOpen(false)
    if (motionFrameRef.current !== null) {
      window.cancelAnimationFrame(motionFrameRef.current)
      motionFrameRef.current = null
    }
    if (openTimerRef.current !== null) {
      window.clearTimeout(openTimerRef.current)
      openTimerRef.current = null
    }
    if (window.matchMedia?.('(prefers-reduced-motion: reduce)').matches) {
      setPanelOpen(false)
      finishClose()
      return
    }
    motionFrameRef.current = window.requestAnimationFrame(() => {
      motionFrameRef.current = null
      setPanelOpen(false)
      const closeDuration = cssDurationMs(
        panelRef.current ? window.getComputedStyle(panelRef.current).getPropertyValue('--panel-close-dur') : '',
        AGENT_PANEL_CLOSE_DURATION_FALLBACK_MS,
      )
      closeTimerRef.current = window.setTimeout(finishClose, closeDuration + 100)
    })
  }, [finishClose])

  useLayoutEffect(() => {
    const reduceMotion = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
    motionFrameRef.current = window.requestAnimationFrame(() => {
      motionFrameRef.current = null
      setPanelOpen(true)
      if (reduceMotion) settleOpen()
    })
    if (!reduceMotion) {
      const openDuration = cssDurationMs(
        panelRef.current ? window.getComputedStyle(panelRef.current).getPropertyValue('--panel-open-dur') : '',
        AGENT_PANEL_OPEN_DURATION_FALLBACK_MS,
      )
      openTimerRef.current = window.setTimeout(settleOpen, openDuration + 100)
    }
    return () => {
      dragCleanupRef.current?.()
      if (motionFrameRef.current !== null) window.cancelAnimationFrame(motionFrameRef.current)
      if (openTimerRef.current !== null) window.clearTimeout(openTimerRef.current)
      if (closeTimerRef.current !== null) window.clearTimeout(closeTimerRef.current)
    }
  }, [settleOpen])

  const commitPanelWidth = (width: number) => {
    const nextWidth = clampPanelWidth(width)
    setPanelWidth(nextWidth)
    try {
      window.localStorage.setItem(AGENT_PANEL_WIDTH_STORAGE_KEY, String(nextWidth))
    } catch {
      // Resizing still works when storage is unavailable.
    }
  }

  const startResize = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (window.matchMedia('(max-width: 864px)').matches) return
    event.preventDefault()
    dragCleanupRef.current?.()
    const startX = event.clientX
    const startWidth = panelWidth
    document.documentElement.classList.add('agent-panel-resizing')

    const handleMove = (moveEvent: PointerEvent) => {
      setPanelWidth(clampPanelWidth(startWidth + startX - moveEvent.clientX))
    }
    const cleanup = () => {
      window.removeEventListener('pointermove', handleMove)
      window.removeEventListener('pointerup', handleUp)
      window.removeEventListener('pointercancel', handleUp)
      document.documentElement.classList.remove('agent-panel-resizing')
      dragCleanupRef.current = null
    }
    const handleUp = () => {
      setPanelWidth((current) => {
        try {
          window.localStorage.setItem(AGENT_PANEL_WIDTH_STORAGE_KEY, String(current))
        } catch {
          // Keep the current width for this session.
        }
        return current
      })
      cleanup()
    }

    window.addEventListener('pointermove', handleMove)
    window.addEventListener('pointerup', handleUp)
    window.addEventListener('pointercancel', handleUp)
    dragCleanupRef.current = cleanup
  }

  const resizeWithKeyboard = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return
    event.preventDefault()
    commitPanelWidth(panelWidth + (event.key === 'ArrowLeft' ? 16 : -16))
  }

  return <aside
    aria-label="CornAgent"
    className={`agent-panel agent-drawer t-panel-slide${layout === 'overlay' ? ' agent-drawer--overlay' : ''}`}
    data-layout-open={layoutOpen}
    data-open={panelOpen}
    onTransitionEnd={(event: ReactTransitionEvent<HTMLElement>) => {
      if (event.target !== event.currentTarget || event.propertyName !== 'transform') return
      if (panelOpen) settleOpen()
      else finishClose()
    }}
    ref={panelRef}
    style={{ width: panelWidth }}
  >
    <div
      aria-label={t('resizeAgent')}
      aria-orientation="vertical"
      aria-valuemax={MAX_AGENT_PANEL_WIDTH}
      aria-valuemin={MIN_AGENT_PANEL_WIDTH}
      aria-valuenow={panelWidth}
      className="agent-panel-resize-handle"
      onKeyDown={resizeWithKeyboard}
      onPointerDown={startResize}
      role="separator"
      tabIndex={0}
    />
    <header className="agent-panel-header">
      <div className="agent-panel-identity">
        <strong>CornAgent</strong>
      </div>
      <span className="spacer" />
      <button type="button" className="agent-icon-button" aria-label={t('newChat')} disabled={active || workspace.busy} onClick={() => void workspace.newSession()}><Plus size={16} /></button>
      <AgentHistoryPicker
        currentSessionId={workspace.session?.id ?? null}
        disabled={active || workspace.busy}
        loadingMore={workspace.loadingMoreSessions}
        nextCursor={workspace.sessionsNextCursor}
        sessions={workspace.sessions}
        loadMore={workspace.loadMoreSessions}
        search={workspace.searchSessions}
        onSessionChange={(sessionId) => { void workspace.selectSession(sessionId) }}
      />
      <button type="button" className="agent-icon-button" aria-label={t('closeAgent')} onClick={requestClose}><X size={16} /></button>
    </header>
    <AgentConversation focusPrompt userName={userName} workspace={workspace} />
  </aside>
}
