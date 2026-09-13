import { useEffect, useState, useSyncExternalStore } from 'react'
import { readThemePreference, subscribeSystemTheme, systemTheme, type ThemeMode } from '../workspacePreferences'

export function useThemePreference() {
  const [preference, setPreference] = useState<ThemeMode | null>(readThemePreference)
  const osTheme = useSyncExternalStore(subscribeSystemTheme, systemTheme, () => 'light' as const)
  const theme = preference ?? osTheme
  useEffect(() => {
    document.documentElement.dataset.theme = theme
    document.documentElement.style.colorScheme = theme
    document.querySelector('meta[name="theme-color"]')?.setAttribute('content', theme === 'dark' ? '#101112' : '#ffffff')
  }, [theme])
  useEffect(() => {
    if (preference === null) return
    try {
      window.localStorage.setItem('cornagent-theme', preference)
    } catch {
      // Theme persistence is optional in restricted browser contexts.
    }
  }, [preference])
  return { theme, setPreference }
}
