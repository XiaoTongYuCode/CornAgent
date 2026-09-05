import { useCallback, useEffect, useLayoutEffect, useRef, useState, type UIEvent } from 'react'

const BOTTOM_THRESHOLD = 48
const TURN_SCROLL_DURATION = 360

function isAtBottom(viewport: HTMLElement) {
  return viewport.scrollHeight - viewport.scrollTop - viewport.clientHeight <= BOTTOM_THRESHOLD
}

/** Keep a new turn in view without pulling readers away from older messages. */
export function useConversationScroll({ sessionId, turnId, loadOlder }: {
  sessionId: string
  turnId: string
  loadOlder(): Promise<void>
}) {
  const viewKey = `${sessionId}:${turnId}`
  const viewportRef = useRef<HTMLDivElement>(null)
  const contentRef = useRef<HTMLDivElement>(null)
  const followingRef = useRef(true)
  const viewKeyRef = useRef(viewKey)
  const sessionIdRef = useRef(sessionId)
  const animationFrameRef = useRef<number | null>(null)
  const [atBottom, setAtBottom] = useState(true)

  const stopAnimation = useCallback(() => {
    if (animationFrameRef.current !== null) window.cancelAnimationFrame(animationFrameRef.current)
    animationFrameRef.current = null
  }, [])

  const scrollToBottom = useCallback((behavior: 'instant' | 'smooth' = 'instant') => {
    stopAnimation()
    const viewport = viewportRef.current
    if (!viewport) return
    if (behavior === 'instant' || window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      viewport.scrollTo({ top: viewport.scrollHeight, behavior: 'instant' })
      return
    }
    const startTop = viewport.scrollTop
    let startedAt: number | null = null
    const animate = (now: number) => {
      startedAt ??= now
      const progress = Math.min(1, (now - startedAt) / TURN_SCROLL_DURATION)
      const eased = 1 - (1 - progress) ** 3
      const target = Math.max(0, viewport.scrollHeight - viewport.clientHeight)
      viewport.scrollTo({ top: startTop + (target - startTop) * eased, behavior: 'instant' })
      if (progress < 1) animationFrameRef.current = window.requestAnimationFrame(animate)
      else {
        animationFrameRef.current = null
        setAtBottom(isAtBottom(viewport))
      }
    }
    animationFrameRef.current = window.requestAnimationFrame(animate)
  }, [stopAnimation])

  const measureViewport = useCallback(() => {
    const viewport = viewportRef.current
    const content = contentRef.current
    if (!viewport || !content) return
    const height = `${viewport.clientHeight}px`
    if (content.style.getPropertyValue('--conversation-viewport-height') !== height) {
      content.style.setProperty('--conversation-viewport-height', height)
    }
  }, [])

  // The latest turn fills the viewport before scrolling, so short answers stay at its top.
  useLayoutEffect(() => {
    const animateTurn = sessionIdRef.current === sessionId && viewKeyRef.current !== viewKey
    viewKeyRef.current = viewKey
    sessionIdRef.current = sessionId
    followingRef.current = true
    measureViewport()
    scrollToBottom(animateTurn ? 'smooth' : 'instant')
  }, [measureViewport, scrollToBottom, sessionId, viewKey])

  useEffect(() => {
    const viewport = viewportRef.current
    const content = contentRef.current
    if (!viewport || !content) return
    const resize = () => {
      measureViewport()
      // Streaming and layout observers must not interrupt the turn transition.
      if (followingRef.current && animationFrameRef.current === null) scrollToBottom()
      setAtBottom(animationFrameRef.current !== null || isAtBottom(viewport))
    }
    const interrupt = () => {
      stopAnimation()
      followingRef.current = false
      setAtBottom(isAtBottom(viewport))
    }
    const onKeyDown = (event: KeyboardEvent) => {
      if (['ArrowUp', 'ArrowDown', 'PageUp', 'PageDown', 'Home', 'End', ' '].includes(event.key)) interrupt()
    }
    const observer = new ResizeObserver(resize)
    observer.observe(viewport)
    observer.observe(content)
    viewport.addEventListener('wheel', interrupt, { passive: true })
    viewport.addEventListener('touchstart', interrupt, { passive: true })
    viewport.addEventListener('pointerdown', interrupt, { passive: true })
    viewport.addEventListener('keydown', onKeyDown)
    return () => {
      observer.disconnect()
      stopAnimation()
      viewport.removeEventListener('wheel', interrupt)
      viewport.removeEventListener('touchstart', interrupt)
      viewport.removeEventListener('pointerdown', interrupt)
      viewport.removeEventListener('keydown', onKeyDown)
    }
  }, [measureViewport, scrollToBottom, stopAnimation])

  const onScroll = useCallback((event: UIEvent<HTMLDivElement>) => {
    if (animationFrameRef.current !== null) return
    const bottom = isAtBottom(event.currentTarget)
    followingRef.current = bottom
    setAtBottom(bottom)
  }, [])

  const loadOlderWithAnchor = useCallback(async () => {
    const viewport = viewportRef.current
    if (!viewport) return
    const expectedView = viewKeyRef.current
    const previousHeight = viewport.scrollHeight
    const previousTop = viewport.scrollTop
    stopAnimation()
    followingRef.current = false
    await loadOlder()
    window.requestAnimationFrame(() => {
      if (!viewport.isConnected || viewKeyRef.current !== expectedView) return
      viewport.scrollTop = previousTop + viewport.scrollHeight - previousHeight
      setAtBottom(isAtBottom(viewport))
    })
  }, [loadOlder, stopAnimation])

  const followLatest = useCallback(() => {
    followingRef.current = true
    scrollToBottom('smooth')
  }, [scrollToBottom])

  return { viewportRef, contentRef, atBottom, onScroll, loadOlderWithAnchor, followLatest }
}
