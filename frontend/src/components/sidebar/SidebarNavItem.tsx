import type { ComponentProps, ReactNode } from 'react'

interface Props extends ComponentProps<'button'> {
  icon: ReactNode
  active?: boolean
}

export function SidebarNavItem({
  icon,
  active = false,
  children,
  className = '',
  ...props
}: Props) {
  return (
    <button
      type="button"
      aria-current={active ? 'page' : undefined}
      {...props}
      className={`nav-item${active ? ' active' : ''}${className ? ` ${className}` : ''}`}
    >
      {icon}
      <span className="nav-chat-title">{children}</span>
    </button>
  )
}
