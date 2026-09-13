import { useEffect } from 'react'
import { useI18n } from '../i18n'
import { usePathname } from './navigation'
import { DEFAULT_SITE_URL, pageMetadata } from './seo'

export function DocumentMetadata() {
  const path = usePathname()
  const { locale } = useI18n()
  useEffect(() => {
    const metadata = pageMetadata(path, locale, import.meta.env.VITE_PUBLIC_SITE_URL || DEFAULT_SITE_URL)
    document.title = metadata.title
    const setMeta = (selector: string, content: string) => {
      document.head.querySelector<HTMLMetaElement>(selector)?.setAttribute('content', content)
    }
    setMeta('meta[name="description"]', metadata.description)
    setMeta('meta[name="robots"]', metadata.robots)
    setMeta('meta[property="og:title"]', metadata.title)
    setMeta('meta[property="og:description"]', metadata.description)
    setMeta('meta[property="og:locale"]', locale === 'en' ? 'en_US' : 'zh_CN')
    setMeta('meta[name="twitter:title"]', metadata.title)
    setMeta('meta[name="twitter:description"]', metadata.description)
    document.head.querySelectorAll('link[rel="canonical"], meta[property="og:url"], #project-structured-data').forEach((node) => node.remove())
    if (metadata.canonical) {
      const canonical = document.createElement('link')
      canonical.rel = 'canonical'
      canonical.href = metadata.canonical
      const ogUrl = document.createElement('meta')
      ogUrl.setAttribute('property', 'og:url')
      ogUrl.content = metadata.canonical
      const structuredData = document.createElement('script')
      structuredData.id = 'project-structured-data'
      structuredData.type = 'application/ld+json'
      structuredData.textContent = JSON.stringify(metadata.structuredData)
      document.head.append(canonical, ogUrl, structuredData)
    }
  }, [path, locale])
  return null
}
