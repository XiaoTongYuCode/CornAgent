import { createContext, useContext } from 'react'
import type { ThemeMode } from '../workspacePreferences'

export interface AppThemeContextValue {
  theme: ThemeMode
  toggleTheme(): void
}

export const AppThemeContext = createContext<AppThemeContextValue | null>(null)

export function useAppTheme() {
  const context = useContext(AppThemeContext)
  if (!context) throw new Error('useAppTheme must be used inside AppProviders.')
  return context
}
