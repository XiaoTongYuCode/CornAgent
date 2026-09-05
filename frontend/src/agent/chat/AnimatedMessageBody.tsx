import { motion, useIsPresent, useReducedMotion } from 'motion/react'
import type { ReactNode } from 'react'

type MessageBodyMotion = 'accordion' | 'boundary'

const boundaryDuration = 0.44
const boundaryEase = [0.33, 0, 0.2, 1] as const
const accordionDuration = 0.25
const smoothOutEase = [0.22, 1, 0.36, 1] as const
const fullClip = 'polygon(0% 0%, 100% 0%, 100% 100%, 0% 100%)'
const staticContentVariants = {
  enter: { y: 0, clipPath: fullClip },
  visible: { y: 0, clipPath: fullClip },
  exit: { y: 0, clipPath: fullClip },
}
const boundaryContentVariants = {
  ...staticContentVariants,
  exit: {
    y: -18,
    clipPath: [fullClip,
      'polygon(0% 0%, 100% 0%, 100% 100%, 0% 0%)',
      'polygon(0% 0%, 100% 0%, 100% 34%, 0% 0%)',
      'polygon(0% 0%, 100% 0%, 100% 0%, 0% 0%)'],
  },
}

/** Keep animated content in flow; reserve the directional fold for answer boundaries. */
export function AnimatedMessageBody({ children, className, motionPreset = 'boundary' }: {
  children: ReactNode
  className?: string
  motionPreset?: MessageBodyMotion
}) {
  const present = useIsPresent()
  const reducedMotion = useReducedMotion()
  const isBoundary = motionPreset === 'boundary'
  const duration = isBoundary ? boundaryDuration : accordionDuration
  const ease = isBoundary ? boundaryEase : smoothOutEase
  return <motion.div
    aria-hidden={present ? undefined : true}
    inert={!present}
    className={className}
    initial={reducedMotion ? false : 'enter'}
    animate="visible"
    exit="exit"
    variants={{
      enter: { height: 0, opacity: 0 },
      visible: { height: 'auto', opacity: 1 },
      exit: { height: 0, opacity: 0 },
    }}
    transition={reducedMotion ? { duration: 0 } : {
      height: { duration, ease },
      opacity: isBoundary
        ? { duration: present ? 0.22 : duration, ease: 'easeIn' }
        : { duration, ease },
    }}
    style={{ overflow: 'hidden', pointerEvents: present ? undefined : 'none' }}
  >
    <motion.div
      variants={reducedMotion || !isBoundary ? staticContentVariants : boundaryContentVariants}
      transition={reducedMotion ? { duration: 0 } : {
        duration, ease,
        ...(isBoundary
          ? { clipPath: { duration, times: [0, 0.35, 0.72, 1], ease: 'easeInOut' as const } }
          : {}),
      }}
    >{children}</motion.div>
  </motion.div>
}
