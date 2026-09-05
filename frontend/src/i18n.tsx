import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
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

function initialLocale(): Locale {
  try {
    return localStorage.getItem('cornagent.locale') === 'en' ? 'en' : 'zh-CN'
  } catch {
    return 'zh-CN'
  }
}

export function I18nProvider({ children }: { children: ReactNode }) {
  const [locale, setLocale] = useState<Locale>(() => {
    return initialLocale()
  })
  useEffect(() => {
    syncDayjsLocale(locale)
    try {
      localStorage.setItem('cornagent.locale', locale)
    } catch {
      // Language switching still works when browser storage is unavailable.
    }
    document.documentElement.lang = locale
  }, [locale])
  const value = useMemo<I18nValue>(
    () => ({
      locale,
      t: (key, params) => translate(locale, key, params),
      text: (zh, en) => (locale === 'zh-CN' ? zh : en),
      toggleLocale: () => setLocale((current) => (current === 'zh-CN' ? 'en' : 'zh-CN')),
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
