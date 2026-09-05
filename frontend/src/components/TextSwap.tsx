import { AnimatePresence, motion, useReducedMotion } from 'motion/react'
import { memo, useMemo } from 'react'
import { ShimmerText } from './ShimmerText'
import '../styles/components/text-swap.css'

interface TextSwapProps {
  text: string
  shimmer?: boolean
  className?: string
  durationMs?: number
}

const enter = { y: 4, filter: 'blur(2px)', opacity: 0 }
const visible = { y: 0, filter: 'blur(0px)', opacity: 1 }
const exit = { y: -4, filter: 'blur(2px)', opacity: 0 }

/** Sequential text swap; the accessible label always reflects the latest state. */
export const TextSwap = memo(function TextSwap({ text, shimmer = false, className = '', durationMs = 150 }: TextSwapProps) {
  const reducedMotion = useReducedMotion()
  const transition = useMemo(() => ({ duration: durationMs / 1000, ease: 'easeInOut' as const }), [durationMs])
  if (reducedMotion) return <ShimmerText active={shimmer} className={className}>{text}</ShimmerText>

  return (
    <span className={`text-swap ${className}`}>
      <span className="sr-only">{text}</span>
      <span aria-hidden="true" className="text-swap__visual">
        <span className="text-swap__measure" data-text={text} />
        <AnimatePresence initial={false} mode="wait">
          <motion.span
            key={text}
            className="text-swap__frame"
            initial={enter}
            animate={visible}
            exit={exit}
            transition={transition}
          >
            <ShimmerText active={shimmer}>{text}</ShimmerText>
          </motion.span>
        </AnimatePresence>
      </span>
    </span>
  )
})
