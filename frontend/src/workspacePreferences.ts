export type ThemeMode = 'light' | 'dark'

export function readThemePreference(): ThemeMode | null {
  try {
    const saved = window.localStorage?.getItem('cornagent-theme')
    return saved === 'dark' || saved === 'light' ? saved : null
  } catch {
    return null
  }
}

export function systemTheme(): ThemeMode {
  return typeof window !== 'undefined' && window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

export function subscribeSystemTheme(onChange: () => void) {
  const media = window.matchMedia('(prefers-color-scheme: dark)')
  media.addEventListener('change', onChange)
  return () => media.removeEventListener('change', onChange)
}
