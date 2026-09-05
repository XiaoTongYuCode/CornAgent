import type { ComponentProps } from 'react'
import '../styles/components/shimmer-text.css'

interface ShimmerTextProps extends ComponentProps<'span'> {
  active?: boolean
}

/** Keeps readable text underneath a decorative, screen-reader-hidden sweep. */
export function ShimmerText({ active = true, children, className = '', ...props }: ShimmerTextProps) {
  const text = typeof children === 'string' || typeof children === 'number' ? String(children) : null
  const shimmering = active && text !== null
  return (
    <span {...props} className={`shimmer-text${shimmering ? ' shimmer-text--active' : ''} ${className}`}>
      {children}
      {shimmering && <span aria-hidden="true" className="shimmer-text__highlight" data-text={text} />}
    </span>
  )
}
