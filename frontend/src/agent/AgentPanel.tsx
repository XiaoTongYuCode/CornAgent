import { useI18n } from '../i18n'
import { useCallback, useLayoutEffect, useRef, useState, type CSSProperties, type TransitionEvent as ReactTransitionEvent } from 'react'
import clsx from 'clsx'
import { AgentConversation } from './AgentConversation'
import { AgentPanelHeader } from './AgentPanelHeader'
import type { AgentWorkspace } from './useAgentWorkspace'
import type { AgentSidebarProps } from './AgentSidebar.types'
import { useAgentPanelWidth } from './useAgentPanelWidth'

const AGENT_PANEL_CLOSE_DURATION_FALLBACK_MS = 350

function cssDurationMs(value: string, fallback: number): number {
  const normalized = value.trim()
  const duration = Number.parseFloat(normalized)
  if (!Number.isFinite(duration)) return fallback
  return normalized.endsWith('ms') ? duration : duration * 1000
}

export function AgentPanel({
  workspace, userName, layout = 'docked', title = 'CornAgent', icon, ariaLabel,
  renderHeader, renderActions, footer, emptyStateFooter, className, style, classNames, styles,
  resizable = true, ...widthOptions
}: AgentSidebarProps & { workspace: AgentWorkspace }) {
  const { t } = useI18n()
  const { panelWidth, effectiveMinimum, effectiveMaximum, cancelResize, startResize, resizeWithKeyboard } = useAgentPanelWidth({ ...widthOptions, resizable })
  const [panelOpen, setPanelOpen] = useState(false)
  const panelRef = useRef<HTMLElement>(null)
  const motionFrameRef = useRef<number | null>(null)
  const closeTimerRef = useRef<number | null>(null)
  const closePendingRef = useRef(false)

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
    cancelResize()
    if (motionFrameRef.current !== null) {
      window.cancelAnimationFrame(motionFrameRef.current)
      motionFrameRef.current = null
    }
    if (window.matchMedia?.('(prefers-reduced-motion: reduce)').matches) {
      setPanelOpen(false)
      finishClose()
      return
    }
    setPanelOpen(false)
    const closeDuration = cssDurationMs(
      panelRef.current ? window.getComputedStyle(panelRef.current).getPropertyValue('--panel-close-dur') : '',
      AGENT_PANEL_CLOSE_DURATION_FALLBACK_MS,
    )
    closeTimerRef.current = window.setTimeout(finishClose, closeDuration + 100)
  }, [finishClose, cancelResize])

  useLayoutEffect(() => {
    // Establish the closed layout before transitioning the panel into the row.
    panelRef.current?.getBoundingClientRect()
    motionFrameRef.current = window.requestAnimationFrame(() => {
      motionFrameRef.current = null
      setPanelOpen(true)
    })
    return () => {
      if (motionFrameRef.current !== null) window.cancelAnimationFrame(motionFrameRef.current)
      if (closeTimerRef.current !== null) window.clearTimeout(closeTimerRef.current)
    }
  }, [])

  return <aside
    aria-label={ariaLabel ?? (typeof title === 'string' ? title : 'CornAgent')}
    className={clsx('agent-panel', 'agent-drawer', `agent-drawer--${layout}`, className)}
    data-open={panelOpen}
    inert={!panelOpen}
    onTransitionEnd={(event: ReactTransitionEvent<HTMLElement>) => {
      if (event.target !== event.currentTarget || !['margin-right', 'transform'].includes(event.propertyName)) return
      if (!panelOpen) finishClose()
    }}
    ref={panelRef}
    style={{ ...style, width: panelWidth, '--agent-panel-width': `${panelWidth}px` } as CSSProperties}
  >
    {resizable && <div
      aria-label={t('resizeAgent')}
      aria-orientation="vertical"
      aria-valuemax={effectiveMaximum}
      aria-valuemin={effectiveMinimum}
      aria-valuenow={panelWidth}
      className="agent-panel-resize-handle"
      onKeyDown={resizeWithKeyboard}
      onPointerDown={startResize}
      role="separator"
      tabIndex={0}
    />}
    <AgentPanelHeader
      workspace={workspace}
      close={requestClose}
      title={title}
      icon={icon}
      renderHeader={renderHeader}
      renderActions={renderActions}
      className={classNames?.header}
      style={styles?.header}
    />
    <div className={clsx('agent-panel-body', classNames?.body)} style={styles?.body}>
      <AgentConversation emptyStateFooter={emptyStateFooter} focusPrompt={panelOpen} userName={userName} workspace={workspace} />
    </div>
    {footer != null && footer !== false && <footer className={clsx('agent-panel-footer', classNames?.footer)} style={styles?.footer}>{footer}</footer>}
  </aside>
}
