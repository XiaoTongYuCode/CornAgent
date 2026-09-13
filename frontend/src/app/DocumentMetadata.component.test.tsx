import { act, render } from '@testing-library/react'
import { DocumentMetadata } from './DocumentMetadata'
import { navigate } from './navigation'
import { I18nProvider } from '../i18n'

it('removes public canonical and structured data on private navigation and restores them on home', () => {
  const previousHead = document.head.innerHTML
  document.head.innerHTML = '<meta name="robots"><meta name="description"><meta property="og:title">'
  const view = render(<I18nProvider><DocumentMetadata /></I18nProvider>)
  try {
    expect(document.querySelector('link[rel="canonical"]')).toHaveAttribute('href', 'https://cornagent.xiaotongyu.com/')
    for (const route of ['/chat/session-id', '/profile', '/usage', '/rendering', '/sidebar']) {
      act(() => navigate(route))
      expect(document.querySelector('meta[name="robots"]')).toHaveAttribute('content', 'noindex, follow')
      expect(document.querySelector('link[rel="canonical"]')).toBeNull()
      expect(document.querySelector('#project-structured-data')).toBeNull()
      expect(document.title).not.toContain('session-id')
    }
    act(() => navigate('/chat'))
    expect(document.querySelector('meta[name="robots"]')).toHaveAttribute('content', 'index, follow, max-image-preview:large')
    expect(document.querySelectorAll('link[rel="canonical"]')).toHaveLength(1)
    expect(JSON.parse(document.querySelector('#project-structured-data')!.textContent!)).toMatchObject({ '@context': 'https://schema.org' })
  } finally {
    view.unmount()
    document.head.innerHTML = previousHead
  }
})
