import { AgentLauncher } from '../agent/AgentLauncher'
import { ArticleSkeleton } from '../components/ArticleSkeleton'
import { useI18n } from '../i18n'
export function SidebarExamplePage() {
  const { t } = useI18n()
  return (
    <>
      <header className="topbar">
        <strong>{t('sidebarExample')}</strong>
        <span className="spacer" />
        <AgentLauncher />
      </header>
      <article className="cornagent-example">
        <h1>{t('exampleTitle')}</h1>
        <ArticleSkeleton />
      </article>
    </>
  )
}
