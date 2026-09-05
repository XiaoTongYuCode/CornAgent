import { act, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Button, theme as antdTheme } from 'antd'
import { AppProviders } from './AppProviders'
import { useAppTheme } from './AppThemeContext'

function ThemeProbe() {
  const { theme, toggleTheme } = useAppTheme()
  const { token } = antdTheme.useToken()
  return <>
    <output data-testid="theme">{theme}:{token.colorPrimary}:{token.colorTextLightSolid}</output>
    <Button type="primary" onClick={toggleTheme}>切换主题</Button>
  </>
}

it('follows the system until manually selected and applies monochrome Ant Design tokens', async () => {
  let dark = false
  const listeners = new Set<() => void>()
  vi.stubGlobal('matchMedia', (query: string) => ({
    matches: query.includes('prefers-color-scheme') && dark, media: query,
    addEventListener: (_type: string, listener: () => void) => { if (query.includes('prefers-color-scheme')) listeners.add(listener) },
    removeEventListener: (_type: string, listener: () => void) => listeners.delete(listener),
    addListener() {}, removeListener() {},
  }))
  const user = userEvent.setup()
  render(<AppProviders><ThemeProbe /></AppProviders>)
  expect(screen.getByTestId('theme')).toHaveTextContent('light:#171717:#ffffff')
  expect(localStorage.getItem('cornagent-theme')).toBeNull()
  act(() => { dark = true; listeners.forEach((listener) => listener()) })
  expect(screen.getByTestId('theme')).toHaveTextContent('dark:#fafafa:#101112')
  await user.click(screen.getByRole('button', { name: '切换主题' }))
  expect(localStorage.getItem('cornagent-theme')).toBe('light')
  act(() => { dark = false; listeners.forEach((listener) => listener()) })
  act(() => { dark = true; listeners.forEach((listener) => listener()) })
  expect(screen.getByTestId('theme')).toHaveTextContent('light:#171717:#ffffff')
})
