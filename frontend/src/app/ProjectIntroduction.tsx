import React from 'react'
import { translate, type Locale } from '../i18n/catalog'
import { REPOSITORY_URL } from './seo'

// Shared by the build-time HTML and the live UI; no API or workspace is needed.
export function ProjectIntroduction({ locale }: { locale: Locale }) {
  return (
    <section className="project-introduction" aria-label="CornAgent">
      <h2>{translate(locale, 'projectTitle')}</h2>
      <p>{translate(locale, 'projectDescription')}</p>
      <nav aria-label={translate(locale, 'projectLinks')}>
        <a href={REPOSITORY_URL} target="_blank" rel="noopener noreferrer">GitHub</a>
        <a href={`${REPOSITORY_URL}#quick-start`} target="_blank" rel="noopener noreferrer">{translate(locale, 'projectQuickStart')}</a>
        <a href={`${REPOSITORY_URL}/blob/main/docs/frontend-integration.md`} target="_blank" rel="noopener noreferrer">{translate(locale, 'projectIntegration')}</a>
      </nav>
    </section>
  )
}
