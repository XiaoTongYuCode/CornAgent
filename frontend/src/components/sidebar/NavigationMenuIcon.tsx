import collapseIconMarkup from '../../assets/svg/menu.svg?raw'
import expandIconMarkup from '../../assets/svg/menu-right.svg?raw'

interface NavigationMenuIconProps {
  variant: 'collapse' | 'expand'
}

export function NavigationMenuIcon({ variant }: NavigationMenuIconProps) {
  const iconMarkup = variant === 'collapse' ? collapseIconMarkup : expandIconMarkup

  return (
    <span
      className={`navigation-menu-icon navigation-menu-icon-${variant}`}
      aria-hidden="true"
      dangerouslySetInnerHTML={{ __html: iconMarkup }}
    />
  )
}
