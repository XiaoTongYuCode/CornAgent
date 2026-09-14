import { useCallback, useEffect, useRef, useState, type KeyboardEvent, type PointerEvent as ReactPointerEvent } from 'react'
import type { AgentSidebarProps } from './AgentSidebar.types'

function positiveWidth(value: number | undefined, fallback: number) {
  return value !== undefined && Number.isFinite(value) && value > 0 ? value : fallback
}

export function useAgentPanelWidth({
  width,
  defaultWidth = 400,
  minWidth = 400,
  maxWidth = 720,
  resizable = true,
  onWidthChange,
  widthStorageKey = 'cornagent:agent-panel-width',
}: AgentSidebarProps) {
  const minimum = positiveWidth(minWidth, 400)
  const maximum = Math.max(minimum, positiveWidth(maxWidth, 720))
  const [viewportWidth, setViewportWidth] = useState(() => typeof window === 'undefined' ? maximum : window.innerWidth)
  const effectiveMinimum = Math.min(minimum, viewportWidth)
  const effectiveMaximum = Math.min(maximum, viewportWidth)
  const clamp = (value: number) => Math.min(effectiveMaximum, Math.max(effectiveMinimum, positiveWidth(value, positiveWidth(defaultWidth, 400))))
  const [uncontrolledWidth, setUncontrolledWidth] = useState(() => {
    if (width === undefined && widthStorageKey && typeof window !== 'undefined') {
      try {
        return positiveWidth(Number(window.localStorage.getItem(widthStorageKey)), positiveWidth(defaultWidth, 400))
      } catch { /* Storage is optional. */ }
    }
    return positiveWidth(defaultWidth, 400)
  })
  const panelWidth = clamp(width ?? uncontrolledWidth)
  const dragCleanupRef = useRef<(() => void) | null>(null)
  const cancelResize = useCallback(() => dragCleanupRef.current?.(), [])

  useEffect(() => {
    const resize = () => setViewportWidth(window.innerWidth)
    window.addEventListener('resize', resize)
    return () => window.removeEventListener('resize', resize)
  }, [])

  useEffect(() => cancelResize, [cancelResize, resizable, minimum, maximum, viewportWidth, widthStorageKey])

  const persistWidth = (value: number) => {
    if (width !== undefined || !widthStorageKey) return
    try {
      window.localStorage.setItem(widthStorageKey, String(value))
    } catch { /* Resizing still works when storage is unavailable. */ }
  }
  const changeWidth = (value: number) => {
    const next = clamp(value)
    if (width === undefined) setUncontrolledWidth(next)
    onWidthChange?.(next)
    return next
  }
  const startResize = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (!resizable || window.matchMedia('(max-width: 864px)').matches) return
    event.preventDefault()
    event.currentTarget.focus({ preventScroll: true })
    dragCleanupRef.current?.()
    const startX = event.clientX
    const startWidth = panelWidth
    let lastWidth = panelWidth
    document.documentElement.classList.add('agent-panel-resizing')
    const move = (moveEvent: PointerEvent) => {
      lastWidth = changeWidth(startWidth + startX - moveEvent.clientX)
    }
    const cleanup = () => {
      window.removeEventListener('pointermove', move)
      window.removeEventListener('pointerup', finish)
      window.removeEventListener('pointercancel', finish)
      document.documentElement.classList.remove('agent-panel-resizing')
      dragCleanupRef.current = null
    }
    const finish = () => {
      persistWidth(lastWidth)
      cleanup()
    }
    window.addEventListener('pointermove', move)
    window.addEventListener('pointerup', finish)
    window.addEventListener('pointercancel', finish)
    dragCleanupRef.current = cleanup
  }
  const resizeWithKeyboard = (event: KeyboardEvent<HTMLDivElement>) => {
    if (!resizable || !['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return
    event.preventDefault()
    const next = event.key === 'Home' ? effectiveMinimum : event.key === 'End' ? effectiveMaximum
      : panelWidth + (event.key === 'ArrowLeft' ? 16 : -16)
    persistWidth(changeWidth(next))
  }

  return { panelWidth, effectiveMinimum, effectiveMaximum, cancelResize, startResize, resizeWithKeyboard }
}
