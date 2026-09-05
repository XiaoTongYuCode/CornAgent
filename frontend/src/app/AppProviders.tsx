import * as LobeConfigProviderModule from '@lobehub/ui/es/ConfigProvider/index'
import LobeThemeProvider from '@lobehub/ui/es/ThemeProvider/index'
import { App as AntdApp, ConfigProvider as AntdConfigProvider, theme as antdTheme, type ThemeConfig } from 'antd'
import enUS from 'antd/locale/en_US'
import zhCN from 'antd/locale/zh_CN'
import { motion } from 'motion/react'
import { useEffect, useMemo, useState, useSyncExternalStore, type ReactNode } from 'react'
import { useI18n } from '../i18n'
import { readThemePreference, subscribeSystemTheme, systemTheme, type ThemeMode } from '../workspacePreferences'
import { AppThemeContext, type AppThemeContextValue } from './AppThemeContext'

const LobeConfigProvider = (
  LobeConfigProviderModule as typeof LobeConfigProviderModule & {
    default: typeof LobeConfigProviderModule.ConfigProvider
  }
).default

export function AppProviders({ children }: { children: ReactNode }) {
  const { locale } = useI18n()
  const [preference, setPreference] = useState<ThemeMode | null>(readThemePreference)
  const osTheme = useSyncExternalStore(subscribeSystemTheme, systemTheme, () => 'light' as const)
  const theme = preference ?? osTheme

  useEffect(() => {
    document.documentElement.dataset.theme = theme
    document.documentElement.style.colorScheme = theme
  }, [theme])

  useEffect(() => {
    if (preference === null) return
    try {
      if (typeof window.localStorage?.setItem === 'function') window.localStorage.setItem('cornagent-theme', preference)
    } catch {
      // Theme persistence is optional in restricted browser contexts.
    }
  }, [preference])

  const themeConfig = useMemo<ThemeConfig>(() => ({
    algorithm: [
      theme === 'dark' ? antdTheme.darkAlgorithm : antdTheme.defaultAlgorithm,
      antdTheme.compactAlgorithm,
      // Keep primary controls monochrome after Ant Design derives its dark palette.
      (seed, map) => ({
        ...(map ?? antdTheme.defaultAlgorithm(seed)),
        colorPrimary: theme === 'dark' ? '#fafafa' : '#171717',
        colorPrimaryHover: theme === 'dark' ? '#dedede' : '#333333',
        colorPrimaryActive: theme === 'dark' ? '#c8c8c8' : '#000000',
      }),
    ],
    token: {
      colorPrimary: theme === 'dark' ? '#fafafa' : '#171717',
      colorPrimaryHover: theme === 'dark' ? '#dedede' : '#333333',
      colorPrimaryActive: theme === 'dark' ? '#c8c8c8' : '#000000',
      colorTextLightSolid: theme === 'dark' ? '#101112' : '#ffffff',
      colorBgContainer: theme === 'dark' ? '#151618' : '#ffffff',
      colorBgElevated: theme === 'dark' ? '#1a1b1e' : '#ffffff',
      colorText: theme === 'dark' ? '#e6e7e9' : '#202124',
      colorTextSecondary: theme === 'dark' ? '#a4a8ae' : '#73777f',
      colorBorder: theme === 'dark' ? '#303236' : '#dedfe2',
      colorBorderSecondary: theme === 'dark' ? '#292b2f' : '#e9eaec',
      controlHeight: 28,
      controlHeightLG: 32,
      borderRadius: 7,
      fontFamily: 'Inter, ui-sans-serif, system-ui, sans-serif',
      fontSize: 14,
      fontWeightStrong: 500,
      boxShadowSecondary: theme === 'dark'
        ? '0 16px 42px rgba(0, 0, 0, 0.5)'
        : '0 16px 42px rgba(17, 24, 39, 0.16)',
    },
    components: {
      Checkbox: { controlInteractiveSize: 16 },
      Rate: {
        starColor: theme === 'dark' ? '#fafafa' : '#171717',
        starBg: theme === 'dark' ? '#303236' : '#dedfe2',
      },
      Select: {
        optionSelectedBg: theme === 'dark' ? '#303236' : '#eeeeee',
        optionActiveBg: theme === 'dark' ? '#202226' : '#f3f4f6',
      },
      DatePicker: { activeBorderColor: theme === 'dark' ? '#fafafa' : '#171717', hoverBorderColor: theme === 'dark' ? '#dedede' : '#333333' },
      Switch: { trackHeight: 18, trackMinWidth: 32, handleSize: 14, trackPadding: 2 },
    },
  }), [theme])

  const context = useMemo<AppThemeContextValue>(() => ({
    theme,
    toggleTheme: () => setPreference(theme === 'light' ? 'dark' : 'light'),
  }), [theme])

  return (
    <AppThemeContext.Provider value={context}>
      <AntdConfigProvider locale={locale === 'zh-CN' ? zhCN : enUS} theme={themeConfig}>
        <LobeConfigProvider locale={locale} motion={motion}>
          <LobeThemeProvider
            appearance={theme}
            enableCustomFonts={false}
            style={{ height: '100%', minHeight: 0, width: '100%' }}
            theme={themeConfig}
          >
            <AntdApp component={false}>
              {children}
            </AntdApp>
          </LobeThemeProvider>
        </LobeConfigProvider>
      </AntdConfigProvider>
    </AppThemeContext.Provider>
  )
}
