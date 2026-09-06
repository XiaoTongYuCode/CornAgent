import { useEffect } from 'react'
import { useI18n } from '../i18n'
import { CollapsedSidebarPreview } from './CollapsedSidebarPreview'
import { SidebarResizeHandle } from './SidebarResizeHandle'
import { SidebarCredit } from './sidebar/SidebarCredit'
import { SidebarHeader } from './sidebar/SidebarHeader'
import { SidebarNavigation, type SidebarNavigationProps } from './sidebar/SidebarNavigation'

interface Props extends SidebarNavigationProps {
  collapsed: boolean
  mobile: boolean
  mobileOpen: boolean
  onCollapse(): void
  onExpand(): void
  onCloseMobile(): void
}
export function Sidebar({
  collapsed,
  mobile,
  mobileOpen,
  onCollapse,
  onExpand,
  onCloseMobile,
  ...navigation
}: Props) {
  const { t } = useI18n()
  useEffect(() => {
    if (!mobile || !mobileOpen) return
    const sidebar = document.getElementById('primary-sidebar')
    const frame = requestAnimationFrame(() =>
      sidebar?.querySelector<HTMLButtonElement>('button')?.focus(),
    )
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault()
        onCloseMobile()
        return
      }
      if (event.key !== 'Tab') return
      const buttons = Array.from(
        sidebar?.querySelectorAll<HTMLElement>('button:not(:disabled), [tabindex="0"]') ?? [],
      ).filter((node) => node.getClientRects().length > 0)
      const first = buttons[0]
      const last = buttons[buttons.length - 1]
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault()
        last?.focus()
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault()
        first?.focus()
      }
    }
    sidebar?.addEventListener('keydown', handleKeyDown)
    return () => {
      cancelAnimationFrame(frame)
      sidebar?.removeEventListener('keydown', handleKeyDown)
    }
  }, [mobile, mobileOpen, onCloseMobile])
  return (
    <CollapsedSidebarPreview collapsed={collapsed} label={t('expandSidebar')} onExpand={onExpand}>
      {({ open, pinOpen, sidebarRef, sidebarInteractionProps }) => (
        <aside
          ref={sidebarRef}
          id="primary-sidebar"
          className="sidebar t-panel-slide"
          data-open={mobile ? mobileOpen : !collapsed || open}
          data-preview={open || undefined}
          aria-label={t('navigation')}
          aria-hidden={(mobile ? !mobileOpen : collapsed && !open) || undefined}
          inert={(mobile ? !mobileOpen : collapsed && !open) || undefined}
          {...sidebarInteractionProps}
        >
          <SidebarResizeHandle label={t('resizeSidebar')} />
          <SidebarHeader
            preview={open}
            onCollapse={onCollapse}
            onExpand={pinOpen}
            onCloseMobile={onCloseMobile}
          />
          <SidebarNavigation {...navigation} />
          <SidebarCredit />
        </aside>
      )}
    </CollapsedSidebarPreview>
  )
}
