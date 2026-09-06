import { PanelLeftClose, PanelLeftOpen } from 'lucide-react'

interface NavigationMenuIconProps {
  variant: 'collapse' | 'expand'
}

export function NavigationMenuIcon({ variant }: NavigationMenuIconProps) {
  const Icon = variant === 'collapse' ? PanelLeftClose : PanelLeftOpen
  return <Icon className="navigation-menu-icon" size={16} strokeWidth={1.75} aria-hidden="true" />
}
