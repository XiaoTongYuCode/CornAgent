import { createContext, useContext, useEffect, useMemo, useState, useSyncExternalStore, type ReactNode } from 'react'
import dayjs from 'dayjs'
import 'dayjs/locale/zh-cn'
import { translate, type Locale, type Translator } from './i18n/catalog'
export type { Locale } from './i18n/catalog'

interface I18nValue {
  locale: Locale
  t: Translator
  text: (zh: string, en: string) => string
  toggleLocale: () => void
}

const I18nContext = createContext<I18nValue | null>(null)
const syncDayjsLocale = (locale: Locale) => dayjs.locale(locale === 'zh-CN' ? 'zh-cn' : 'en')
const fallbackI18n: I18nValue = {
  locale: 'zh-CN',
  t: (key, params) => translate('zh-CN', key, params),
  text: (zh) => zh,
  toggleLocale: () => undefined,
}

function readLocalePreference(): Locale | null {
  try {
    const saved = localStorage.getItem('cornagent.locale')
    return saved === 'en' || saved === 'zh-CN' ? saved : null
  } catch {
    return null
  }
}

function systemLocale(): Locale {
  if (typeof navigator === 'undefined') return 'en'
  for (const language of navigator.languages?.length ? navigator.languages : [navigator.language]) {
    const base = language?.toLowerCase().split(/[-_]/)[0]
    if (base === 'zh') return 'zh-CN'
    if (base === 'en') return 'en'
  }
  return 'en'
}

function subscribeSystemLocale(onChange: () => void) {
  window.addEventListener('languagechange', onChange)
  return () => window.removeEventListener('languagechange', onChange)
}

export function I18nProvider({ children }: { children: ReactNode }) {
  const [preference, setPreference] = useState<Locale | null>(readLocalePreference)
  const osLocale = useSyncExternalStore(subscribeSystemLocale, systemLocale, () => 'en' as const)
  const locale = preference ?? osLocale
  useEffect(() => {
    syncDayjsLocale(locale)
    document.documentElement.lang = locale
  }, [locale])
  useEffect(() => {
    if (preference === null) return
    try {
      localStorage.setItem('cornagent.locale', preference)
    } catch {
      // Language switching still works when browser storage is unavailable.
    }
  }, [preference])
  const value = useMemo<I18nValue>(
    () => ({
      locale,
      t: (key, params) => translate(locale, key, params),
      text: (zh, en) => (locale === 'zh-CN' ? zh : en),
      toggleLocale: () => setPreference(locale === 'zh-CN' ? 'en' : 'zh-CN'),
    }),
    [locale],
  )
  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>
}

// This hook intentionally shares the provider module so the locale contract stays in one place.
// eslint-disable-next-line react-refresh/only-export-components
export function useI18n(): I18nValue {
  return useContext(I18nContext) ?? fallbackI18n
}
