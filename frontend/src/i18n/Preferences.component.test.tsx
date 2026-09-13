import { act, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useEffect, useState } from 'react'
import { I18nProvider, useI18n } from '../i18n'

function Probe({ onMount }: { onMount: () => void }) {
  const { locale, toggleLocale } = useI18n()
  const [draft, setDraft] = useState('')
  useEffect(onMount, [onMount])
  return <><output>{locale}</output><input aria-label="draft" value={draft} onChange={(event) => setDraft(event.target.value)} /><button onClick={toggleLocale}>Language</button></>
}

it.each([
  [['en-US'], 'en'], [['zh-TW'], 'zh-CN'], [['fr-FR', 'zh-CN'], 'zh-CN'], [['ja-JP'], 'en'],
])('uses system languages %j without persisting an automatic choice', (languages, locale) => {
  vi.spyOn(navigator, 'languages', 'get').mockReturnValue(languages as string[])
  render(<I18nProvider><Probe onMount={vi.fn()} /></I18nProvider>)
  expect(screen.getByRole('status')).toHaveTextContent(locale as string)
  expect(document.documentElement.lang).toBe(locale)
  expect(localStorage.getItem('cornagent.locale')).toBeNull()
})

it('follows system changes until manually overridden, preserving mounted state and saved preferences', async () => {
  const languages = vi.spyOn(navigator, 'languages', 'get').mockReturnValue(['en-US'])
  const mount = vi.fn()
  const user = userEvent.setup()
  const view = render(<I18nProvider><Probe onMount={mount} /></I18nProvider>)
  await user.type(screen.getByLabelText('draft'), 'My draft')
  languages.mockReturnValue(['zh-CN'])
  act(() => window.dispatchEvent(new Event('languagechange')))
  expect(screen.getByRole('status')).toHaveTextContent('zh-CN')
  await user.click(screen.getByRole('button', { name: 'Language' }))
  expect(localStorage.getItem('cornagent.locale')).toBe('en')
  languages.mockReturnValue(['en-US'])
  act(() => window.dispatchEvent(new Event('languagechange')))
  languages.mockReturnValue(['zh-CN'])
  act(() => window.dispatchEvent(new Event('languagechange')))
  expect(screen.getByRole('status')).toHaveTextContent('en')
  expect(screen.getByLabelText('draft')).toHaveValue('My draft')
  expect(mount).toHaveBeenCalledTimes(1)
  view.unmount()
  render(<I18nProvider><Probe onMount={vi.fn()} /></I18nProvider>)
  expect(screen.getByRole('status')).toHaveTextContent('en')
})

it('falls back to the system when storage is blocked and still allows manual switching', async () => {
  vi.spyOn(navigator, 'languages', 'get').mockReturnValue(['en-US'])
  vi.spyOn(localStorage, 'getItem').mockImplementation(() => { throw new Error('blocked') })
  vi.spyOn(localStorage, 'setItem').mockImplementation(() => { throw new Error('blocked') })
  render(<I18nProvider><Probe onMount={vi.fn()} /></I18nProvider>)
  expect(screen.getByRole('status')).toHaveTextContent('en')
  await userEvent.click(screen.getByRole('button', { name: 'Language' }))
  expect(screen.getByRole('status')).toHaveTextContent('zh-CN')
})
