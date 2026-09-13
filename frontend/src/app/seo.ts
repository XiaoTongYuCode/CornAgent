import { translate, type Locale, type MessageKey } from '../i18n/catalog'

export const DEFAULT_SITE_URL = 'https://cornagent.xiaotongyu.com'
export const REPOSITORY_URL = 'https://github.com/XiaoTongYuCode/CornAgent'
export const publicHome = (path: string) => path === '/' || path === '/chat'

export function pageMetadata(path: string, locale: Locale, siteUrl: string) {
  const home = publicHome(path)
  const pageKeys: Record<string, MessageKey> = {
    '/sidebar': 'sidebarExample', '/rendering': 'agentRendering', '/usage': 'usageTitle', '/profile': 'myProfile',
  }
  return {
    title: home ? translate(locale, 'projectTitle') : `${translate(locale, pageKeys[path] ?? 'conversation')} · CornAgent`,
    description: translate(locale, 'projectDescription'),
    robots: home ? 'index, follow, max-image-preview:large' : 'noindex, follow',
    canonical: home ? `${siteUrl}/` : null,
    structuredData: home ? {
      '@context': 'https://schema.org',
      '@graph': [
        { '@type': 'WebSite', '@id': `${siteUrl}/#website`, name: 'CornAgent', url: `${siteUrl}/`, inLanguage: ['en', 'zh-CN'] },
        {
          '@type': 'SoftwareSourceCode', '@id': `${siteUrl}/#source`, name: 'CornAgent',
          description: translate(locale, 'projectDescription'), url: `${siteUrl}/`,
          codeRepository: REPOSITORY_URL, license: `${REPOSITORY_URL}/blob/main/LICENSE`,
          programmingLanguage: ['TypeScript', 'Python'], runtimePlatform: ['React', 'FastAPI', 'PostgreSQL', 'Redis'],
        },
      ],
    } : null,
  }
}
