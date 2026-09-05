import { Languages, SunMoon, X } from 'lucide-react'
import { useI18n } from '../../i18n'
import { useAppTheme } from '../../app/AppThemeContext'
import { NavigationMenuIcon } from './NavigationMenuIcon'
import cornAgentIcon from '../../../../assets/brand/cornagent.svg'

interface Props {
  preview: boolean
  onCollapse(): void
  onExpand(): void
  onCloseMobile(): void
}
export function SidebarHeader({ preview, onCollapse, onExpand, onCloseMobile }: Props) {
  const { locale, t, toggleLocale } = useI18n()
  const { theme, toggleTheme } = useAppTheme()
  const themeLabel = t(theme === 'light' ? 'darkTheme' : 'lightTheme')
  const languageLabel = locale === 'zh-CN' ? 'Switch to English' : '切换至中文'
  const collapseLabel = t(preview ? 'pinSidebar' : 'collapseSidebar')
  return (
    <div className="sidebar-header" data-preview={preview || undefined}>
      <span className="sidebar-brand">
        <span className="sidebar-brand-icon" aria-hidden="true" style={{ maskImage: `url("${cornAgentIcon}")` }} />
        <strong className="sidebar-title">CornAgent</strong>
      </span>
      <div className="sidebar-header-actions">
        <button
          className="sidebar-header-icon-button sidebar-theme-toggle"
          type="button"
          data-theme={theme}
          aria-label={themeLabel}
          title={themeLabel}
          aria-pressed={theme === 'dark'}
          onClick={toggleTheme}
        >
          <SunMoon size={16} strokeWidth={1.75} aria-hidden="true" />
        </button>
        <button
          className="sidebar-header-icon-button sidebar-language-toggle"
          type="button"
          data-locale={locale}
          aria-label={languageLabel}
          title={languageLabel}
          onClick={toggleLocale}
        >
          <Languages size={16} strokeWidth={1.75} aria-hidden="true" />
        </button>
        <button
          className="desktop-sidebar-collapse sidebar-header-icon-button"
          type="button"
          aria-label={collapseLabel}
          title={collapseLabel}
          onClick={preview ? onExpand : onCollapse}
        >
          <NavigationMenuIcon variant={preview ? 'expand' : 'collapse'} />
        </button>
        <button
          className="mobile-sidebar-close sidebar-header-icon-button"
          type="button"
          aria-label={t('closeNavigation')}
          onClick={onCloseMobile}
        >
          <X size={18} aria-hidden="true" />
        </button>
      </div>
    </div>
  )
}
