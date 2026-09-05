import { useEffect, useLayoutEffect, useRef, useState, type KeyboardEvent, type PointerEvent as ReactPointerEvent } from 'react'
import {
  SIDEBAR_KEYBOARD_STEP,
  SIDEBAR_MAX_WIDTH,
  SIDEBAR_MIN_WIDTH,
  clampSidebarWidth,
  readSidebarWidth,
  storeSidebarWidth,
} from './sidebarSizing'

interface SidebarResizeHandleProps {
  label: string
}

export function SidebarResizeHandle({ label }: SidebarResizeHandleProps) {
  const handleRef = useRef<HTMLDivElement>(null)
  const resizeShellRef = useRef<HTMLElement | null>(null)
  const dragRef = useRef<{ pointerId: number; startX: number; startWidth: number } | null>(null)
  const pointerListenersCleanupRef = useRef<(() => void) | null>(null)
  const [width, setWidth] = useState(readSidebarWidth)
  const widthRef = useRef(width)

  function applyWidth(nextWidth: number) {
    const clampedWidth = clampSidebarWidth(nextWidth)
    widthRef.current = clampedWidth
    setWidth(clampedWidth)
    handleRef.current?.closest<HTMLElement>('.app-shell')?.style.setProperty('--sidebar-width', `${clampedWidth}px`)
  }

  function finishResize(pointerId?: number) {
    const drag = dragRef.current
    if (!drag || (pointerId !== undefined && drag.pointerId !== pointerId)) return
    const handle = handleRef.current
    try {
      if (handle?.hasPointerCapture?.(drag.pointerId)) handle.releasePointerCapture(drag.pointerId)
    } catch {
      // Window listeners keep dragging reliable when pointer capture is unavailable.
    }
    pointerListenersCleanupRef.current?.()
    pointerListenersCleanupRef.current = null
    resizeShellRef.current?.classList.remove('sidebar-resizing')
    resizeShellRef.current = null
    dragRef.current = null
    storeSidebarWidth(widthRef.current)
  }

  useLayoutEffect(() => {
    const shell = handleRef.current?.closest<HTMLElement>('.app-shell')
    shell?.style.setProperty('--sidebar-width', `${widthRef.current}px`)
    return () => {
      shell?.style.removeProperty('--sidebar-width')
    }
  }, [])

  useEffect(() => () => {
    pointerListenersCleanupRef.current?.()
    resizeShellRef.current?.classList.remove('sidebar-resizing')
  }, [])

  function handlePointerDown(event: ReactPointerEvent<HTMLDivElement>) {
    if (event.button !== 0) return
    event.preventDefault()
    dragRef.current = { pointerId: event.pointerId, startX: event.clientX, startWidth: widthRef.current }
    resizeShellRef.current = event.currentTarget.closest<HTMLElement>('.app-shell')
    resizeShellRef.current?.classList.add('sidebar-resizing')
    const handlePointerMove = (moveEvent: PointerEvent) => {
      const drag = dragRef.current
      if (!drag || drag.pointerId !== moveEvent.pointerId) return
      applyWidth(drag.startWidth + moveEvent.clientX - drag.startX)
    }
    const handlePointerEnd = (endEvent: PointerEvent) => finishResize(endEvent.pointerId)
    window.addEventListener('pointermove', handlePointerMove)
    window.addEventListener('pointerup', handlePointerEnd)
    window.addEventListener('pointercancel', handlePointerEnd)
    pointerListenersCleanupRef.current = () => {
      window.removeEventListener('pointermove', handlePointerMove)
      window.removeEventListener('pointerup', handlePointerEnd)
      window.removeEventListener('pointercancel', handlePointerEnd)
    }
    try {
      event.currentTarget.setPointerCapture?.(event.pointerId)
    } catch {
      // The window listeners above cover browsers that reject pointer capture.
    }
  }

  function handleKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    let nextWidth: number | null = null
    if (event.key === 'ArrowLeft') nextWidth = widthRef.current - SIDEBAR_KEYBOARD_STEP
    if (event.key === 'ArrowRight') nextWidth = widthRef.current + SIDEBAR_KEYBOARD_STEP
    if (event.key === 'Home') nextWidth = SIDEBAR_MIN_WIDTH
    if (event.key === 'End') nextWidth = SIDEBAR_MAX_WIDTH
    if (nextWidth === null) return
    event.preventDefault()
    applyWidth(nextWidth)
    storeSidebarWidth(widthRef.current)
  }

  return (
    <div
      ref={handleRef}
      className="sidebar-resize-handle"
      role="separator"
      tabIndex={0}
      aria-label={label}
      aria-orientation="vertical"
      aria-valuemin={SIDEBAR_MIN_WIDTH}
      aria-valuemax={SIDEBAR_MAX_WIDTH}
      aria-valuenow={width}
      aria-valuetext={`${width}px`}
      title={label}
      onKeyDown={handleKeyDown}
      onPointerDown={handlePointerDown}
    />
  )
}
