import { type CSSProperties, type ReactNode, type RefObject, useCallback, useLayoutEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'

export type FloatingMenuPlacement = 'bottom-start' | 'bottom-end' | 'top-start' | 'top-end'

interface FloatingMenuPortalProps {
  getAnchor: () => HTMLElement | null
  getBoundary?: () => HTMLElement | null
  getContainer?: () => Element | null
  children: ReactNode
  className: string
  matchAnchorWidth?: boolean
  placement?: FloatingMenuPlacement
  offset?: number
  id?: string
  role?: string
  ariaLabel?: string
  menuRef?: RefObject<HTMLDivElement | null>
}

const viewportPadding = 8

function resolvePosition(anchorRect: DOMRect, menuSize: Pick<DOMRect, 'height' | 'width'>, placement: FloatingMenuPlacement, offset: number, boundaryRect?: DOMRect) {
  const viewportWidth = document.documentElement.clientWidth || window.innerWidth
  const viewportHeight = window.innerHeight
  const alignEnd = placement.endsWith('end')
  const preferTop = placement.startsWith('top')
  const boundaryTop = Math.max(viewportPadding, boundaryRect?.top ?? viewportPadding)
  const boundaryBottom = Math.min(viewportHeight - viewportPadding, boundaryRect?.bottom ?? viewportHeight - viewportPadding)
  const roomAbove = anchorRect.top - boundaryTop
  const roomBelow = boundaryBottom - anchorRect.bottom
  const openAbove = preferTop ? roomAbove >= menuSize.height + offset || roomBelow < roomAbove : roomBelow < menuSize.height + offset && roomAbove > roomBelow
  const unclampedTop = openAbove ? anchorRect.top - menuSize.height - offset : anchorRect.bottom + offset
  const unclampedLeft = alignEnd ? anchorRect.right - menuSize.width : anchorRect.left
  const maxLeft = Math.max(viewportPadding, viewportWidth - menuSize.width - viewportPadding)
  const maxTop = Math.max(viewportPadding, viewportHeight - menuSize.height - viewportPadding)
  return {
    left: Math.round(Math.min(Math.max(unclampedLeft, viewportPadding), maxLeft)),
    top: Math.round(Math.min(Math.max(unclampedTop, viewportPadding), maxTop)),
  }
}

export function FloatingMenuPortal({ getAnchor, getBoundary, getContainer, children, className, matchAnchorWidth = false, placement = 'bottom-start', offset = 5, id, role = 'menu', ariaLabel, menuRef }: FloatingMenuPortalProps) {
  const localRef = useRef<HTMLDivElement | null>(null)
  const [position, setPosition] = useState<CSSProperties>({ visibility: 'hidden' })
  const assignRef = useCallback((node: HTMLDivElement | null) => {
    localRef.current = node
    if (menuRef) menuRef.current = node
  }, [menuRef])

  useLayoutEffect(() => {
    const menu = localRef.current
    if (!menu) return
    const menuElement = menu
    let anchorElement: HTMLElement | null = null
    let boundaryElement: HTMLElement | null = null
    let observer: ResizeObserver | null = null
    let retryFrame: number | null = null
    let listening = false
    function updatePosition() {
      if (!anchorElement) return
      const anchorRect = anchorElement.getBoundingClientRect()
      const menuRect = menuElement.getBoundingClientRect()
      const availableWidth = Math.max(0, (document.documentElement.clientWidth || window.innerWidth) - viewportPadding * 2)
      const menuWidth = matchAnchorWidth ? Math.min(anchorRect.width, availableWidth) : menuRect.width
      const next = resolvePosition(anchorRect, { height: menuRect.height, width: menuWidth }, placement, offset, boundaryElement?.getBoundingClientRect())
      setPosition({
        position: 'fixed',
        top: next.top,
        right: 'auto',
        bottom: 'auto',
        left: next.left,
        visibility: 'visible',
        width: matchAnchorWidth ? menuWidth : undefined,
      })
    }

    function connectToAnchor() {
      anchorElement = getAnchor()
      if (!anchorElement) return
      boundaryElement = getBoundary?.() ?? null
      updatePosition()
      window.addEventListener('resize', updatePosition)
      window.addEventListener('scroll', updatePosition, { capture: true, passive: true })
      listening = true
      observer = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(updatePosition)
      observer?.observe(anchorElement)
      observer?.observe(menuElement)
      if (boundaryElement) observer?.observe(boundaryElement)
    }

    connectToAnchor()
    if (!anchorElement) retryFrame = window.requestAnimationFrame(connectToAnchor)
    return () => {
      if (retryFrame !== null) window.cancelAnimationFrame(retryFrame)
      if (listening) {
        window.removeEventListener('resize', updatePosition)
        window.removeEventListener('scroll', updatePosition, true)
      }
      observer?.disconnect()
    }
  }, [getAnchor, getBoundary, matchAnchorWidth, offset, placement])

  if (typeof document === 'undefined') return null
  const container = getContainer?.() ?? document.body
  return createPortal(
    <div ref={assignRef} id={id} className={`floating-menu floating-menu-portal object-floating-menu ${className}`} role={role} aria-label={ariaLabel} style={position}>
      {children}
    </div>,
    container,
  )
}
