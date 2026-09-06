import { act, fireEvent, render, screen, within } from '@testing-library/react'
import type { ComponentProps } from 'react'
import { AppProviders } from '../app/AppProviders'
import { I18nProvider } from '../i18n'
import type { MarkdownMessageContent } from '../agent/chat/MarkdownMessageContent'
import { ProcessTransitionPreview } from './ProcessTransitionPreview'

// Observe playback data separately from the renderer's own animation timers.
vi.mock('../agent/chat/MarkdownMessageContent', () => ({
  MarkdownMessageContent: (props: ComponentProps<typeof MarkdownMessageContent>) => <output
    data-testid="frame" data-active={props.isProcessActive} data-streaming={props.isMessageStreaming}
  >{JSON.stringify(props.contentParts)}</output>,
}))

const advance = (ms: number) => act(() => vi.advanceTimersByTime(ms))
const show = () => render(<I18nProvider><AppProviders><ProcessTransitionPreview /></AppProviders></I18nProvider>)

it('pauses and resumes the same timeline and button across theme and language changes', () => {
  vi.useFakeTimers()
  show()
  const button = screen.getByRole('button', { name: '播放完整流程' })
  fireEvent.click(button)
  advance(2000)
  expect(screen.getByRole('button', { name: '暂停播放' })).toBe(button)
  expect(button.querySelector('.lucide-pause')).not.toBeNull()
  fireEvent.click(button)
  const frozen = screen.getByTestId('frame').textContent
  expect(frozen).toContain('reasoning')
  advance(20000)
  expect(screen.getByTestId('frame')).toHaveTextContent(frozen!)
  expect(screen.getByTestId('frame')).toHaveAttribute('data-active', 'true')

  const settings = within(screen.getByRole('group', { name: '视图设置' }))
  fireEvent.click(settings.getByRole('button', { name: '切换主题' }))
  fireEvent.click(settings.getByRole('button', { name: '切换语言' }))
  expect(screen.getByRole('button', { name: 'Resume playback' })).toBe(button)
  const english = screen.getByTestId('frame').textContent!
  expect(english).not.toMatch(/[\u4e00-\u9fff]/)
  expect(JSON.parse(english).map((part: { id: string }) => part.id)).toEqual(JSON.parse(frozen!).map((part: { id: string }) => part.id))
  advance(10000)
  expect(screen.getByTestId('frame').textContent).toBe(english)
  fireEvent.click(button)
  advance(700)
  expect(screen.getByTestId('frame').textContent).not.toBe(english)
  // Resumes within reasoning, without jumping ahead by the time spent paused.
  expect(screen.getByTestId('frame').textContent).not.toContain('tool_call')
  advance(20000)
  expect(screen.getByRole('button', { name: 'Play full sequence' })).toBe(button)
  expect(button.querySelector('.lucide-play')).not.toBeNull()
  expect(screen.getByTestId('frame')).toHaveAttribute('data-streaming', 'false')
})

it('freezes running tools without completing them and reset discards the paused run', () => {
  vi.useFakeTimers()
  show()
  const initial = screen.getByTestId('frame').textContent
  fireEvent.click(screen.getByRole('button', { name: '工具流式演示' }))
  advance(1200)
  fireEvent.click(screen.getByRole('button', { name: '暂停播放' }))
  const frozen = screen.getByTestId('frame').textContent
  expect(frozen).toContain('正在读取示例资料')
  expect(frozen).toContain('"status":"running"')
  advance(10000)
  expect(screen.getByTestId('frame').textContent).toBe(frozen)
  fireEvent.click(screen.getByRole('button', { name: '重置演示' }))
  advance(10000)
  expect(screen.getByTestId('frame').textContent).toBe(initial)
  expect(screen.queryByRole('button', { name: '继续播放' })).not.toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: '首 token 演示' }))
  advance(500)
  fireEvent.click(screen.getByRole('button', { name: '暂停播放' }))
  advance(10000)
  expect(screen.getByTestId('frame')).toHaveTextContent('[]')
  fireEvent.click(screen.getByRole('button', { name: '继续播放' }))
  advance(1200)
  expect(screen.getByTestId('frame').textContent).toContain('reasoning')
  advance(4000)
  expect(screen.getByRole('button', { name: '播放完整流程' })).toBeEnabled()
})
