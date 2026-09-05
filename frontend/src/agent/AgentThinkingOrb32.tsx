import { MODE_DRAWS, type ModeKey } from 'thinking-orbs/engine'
import { useContext, useEffect, useRef, useState, type CanvasHTMLAttributes } from 'react'
import { AppThemeContext } from '../app/AppThemeContext'

const ORB_SIZE = 32
type AgentThinkingOrbState = 'breathing' | 'composing'

const PRESETS: Record<AgentThinkingOrbState, { mode: ModeKey; speed: number; opts: Record<string, number> }> = {
  composing: {
    mode: 'ribbon',
    speed: 2.7776,
    opts: {
      lanes: 2,
      segs: 27,
      ghostN: 15,
      rBase: 1.07426,
      rDepth: 1.66022,
      rSizeMul: 0.9766,
      rsPow: 0.6,
      rMin: 0.3,
      spin: 0,
      bandMul: 4.49,
      wobMul: 1,
    },
  },
  breathing: {
    mode: 'ring',
    speed: 3.5517,
    opts: {
      lanes: 2,
      segs: 23,
      ghostN: 0,
      faceOn: 1,
      rBase: 1.441,
      rDepth: 2.227,
      rSizeMul: 1.31,
      rsPow: 0.6,
      rMin: 0.3,
      spin: 0,
      bandMul: 3.8265,
      wobMul: 0.4751,
    },
  },
}

type AgentThinkingOrb32Props = Omit<CanvasHTMLAttributes<HTMLCanvasElement>, 'height' | 'width'> & {
  paused?: boolean
  speed?: number
  state: AgentThinkingOrbState
}

export function AgentThinkingOrb32({
  paused = false,
  speed = 1,
  state,
  style,
  'aria-label': ariaLabel,
  ...canvasProps
}: AgentThinkingOrb32Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const appTheme = useContext(AppThemeContext)
  const reducedMotion = usePrefersReducedMotion()
  const dark = appTheme?.theme === 'dark' || (!appTheme && document.documentElement.dataset.theme === 'dark')
  const preset = PRESETS[state]

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const dpr = Math.min(2, window.devicePixelRatio || 1)
    canvas.width = Math.round(ORB_SIZE * dpr)
    canvas.height = Math.round(ORB_SIZE * dpr)
    const context = canvas.getContext('2d')
    if (!context) return

    const drawFrame = (timeSeconds: number) => {
      context.setTransform(dpr, 0, 0, dpr, 0, 0)
      context.clearRect(0, 0, ORB_SIZE, ORB_SIZE)
      MODE_DRAWS[preset.mode](context, ORB_SIZE, timeSeconds, dark, preset.opts)
    }

    if (reducedMotion) {
      drawFrame(0.6)
      return
    }

    let animationFrame = 0
    let running = false
    const drawAnimatedFrame = () => {
      drawFrame(performance.now() / 1000 * preset.speed * speed)
      if (running) animationFrame = window.requestAnimationFrame(drawAnimatedFrame)
    }
    const start = () => {
      if (running || paused) return
      running = true
      animationFrame = window.requestAnimationFrame(drawAnimatedFrame)
    }
    const stop = () => {
      running = false
      window.cancelAnimationFrame(animationFrame)
    }

    drawAnimatedFrame()
    let visible = true
    const observer = typeof IntersectionObserver === 'undefined'
      ? null
      : new IntersectionObserver(([entry]) => {
        visible = entry.isIntersecting
        if (visible && document.visibilityState !== 'hidden') start()
        else stop()
      })
    observer?.observe(canvas)

    const handleVisibilityChange = () => {
      if (document.visibilityState === 'hidden') stop()
      else if (visible) start()
    }
    document.addEventListener('visibilitychange', handleVisibilityChange)
    if (!observer) start()

    return () => {
      stop()
      observer?.disconnect()
      document.removeEventListener('visibilitychange', handleVisibilityChange)
    }
  }, [dark, paused, preset, reducedMotion, speed])

  return <canvas
    ref={canvasRef}
    role="img"
    aria-label={ariaLabel ?? (state === 'composing' ? 'Composing…' : 'Thinking…')}
    style={{ width: ORB_SIZE, height: ORB_SIZE, display: 'block', ...style }}
    {...canvasProps}
  />
}

function usePrefersReducedMotion() {
  const [reducedMotion, setReducedMotion] = useState(() => window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false)

  useEffect(() => {
    const mediaQuery = window.matchMedia?.('(prefers-reduced-motion: reduce)')
    if (!mediaQuery) return
    const update = () => setReducedMotion(mediaQuery.matches)
    update()
    mediaQuery.addEventListener('change', update)
    return () => mediaQuery.removeEventListener('change', update)
  }, [])

  return reducedMotion
}
