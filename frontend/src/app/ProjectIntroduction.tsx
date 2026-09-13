import React from 'react'
import { translate, type Locale } from '../i18n/catalog'
import { REPOSITORY_URL } from './seo'
import { ProjectContactLinks } from './ProjectContactLinks'

// Shared by the build-time HTML and the live UI; no API or workspace is needed.
export function ProjectIntroduction({ locale, showLinks = true, compact = false }: { locale: Locale; showLinks?: boolean; compact?: boolean }) {
  return (
    <section className={`project-introduction${compact ? ' project-introduction--compact' : ''}`} aria-label="CornAgent">
      {!compact && <h2>{translate(locale, 'projectTitle')}</h2>}
      <p>{translate(locale, compact ? 'projectShortDescription' : 'projectDescription')}</p>
      {showLinks && <nav aria-label={translate(locale, 'projectLinks')}>
        {compact ? <ProjectContactLinks /> : <a href={REPOSITORY_URL} target="_blank" rel="noopener noreferrer">GitHub</a>}
        <a href={`${REPOSITORY_URL}#quick-start`} target="_blank" rel="noopener noreferrer">{translate(locale, 'projectQuickStart')}</a>
        <a href={`${REPOSITORY_URL}/blob/main/docs/frontend-integration.md`} target="_blank" rel="noopener noreferrer">{translate(locale, 'projectIntegration')}</a>
      </nav>}
    </section>
  )
}
