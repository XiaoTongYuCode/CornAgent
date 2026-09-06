import { fireEvent, render, screen } from '@testing-library/react'
import { MarkdownMessageContent } from '../agent/chat/MarkdownMessageContent'
import { projectDesktopContentParts } from '../agent/chat/projectDesktopContentParts'
import { I18nProvider } from '../i18n'
import { messagePreviewCopy } from './messagePreviewCopy'
import { createPreviewScript, initialPreviewParts } from './messagePreviewScript'

it.each(['zh-CN', 'en'] as const)('automatically folds the fourth demo tool and preserves expansion in %s', (locale) => {
  localStorage.setItem('cornagent.locale', locale)
  const title = (count: number) => messagePreviewCopy[locale].groupDone.replace('{count}', String(count))
  const steps = createPreviewScript('tool-group', 'group-demo', initialPreviewParts)
  const show = (count: number) => {
    const frame = steps.find((step) => step.parts[locale].filter((part) => part.kind === 'tool_call').length === count
      && step.parts[locale].at(-1)?.metadata?.status === 'completed')!
    return <I18nProvider><MarkdownMessageContent content="" contentParts={projectDesktopContentParts(frame.parts[locale])} enableProcessSession /></I18nProvider>
  }
  const { container, rerender } = render(show(3))
  const group = container.querySelector('.chat-tool-run-group')!
  expect(group).toHaveClass('chat-tool-run-group--flat')
  expect(screen.getByRole('button', { name: title(3) })).toBeInTheDocument()

  rerender(show(4))
  expect(container.querySelector('.chat-tool-run-group')).toBe(group)
  expect(group).toHaveClass('chat-tool-run-group--grouped')
  const toggle = group.querySelector('.chat-tool-run-group__toggle')!
  expect(toggle).toHaveAttribute('aria-expanded', 'false')
  expect(group.querySelector('.chat-tool-run-group__body')).toHaveAttribute('inert')
  expect(screen.queryByRole('button', { name: title(3) })).not.toBeInTheDocument()

  fireEvent.click(toggle)
  expect(toggle).toHaveAttribute('aria-expanded', 'true')
  rerender(show(5))
  expect(container.querySelector('.chat-tool-run-group')).toBe(group)
  expect(toggle).toHaveAttribute('aria-expanded', 'true')
  expect(screen.getByRole('button', { name: title(5) })).toBeInTheDocument()
  if (locale === 'en') expect(container.textContent).not.toMatch(/[\u4e00-\u9fff]/)
})

it('keeps English running titles shimmering, including after they collapse into a group', () => {
  localStorage.setItem('cornagent.locale', 'en')
  const steps = createPreviewScript('tool-group', 'english', initialPreviewParts)
  const show = (count: number) => {
    const frame = steps.find((step) => step.parts.en.length === count + 1 && step.parts.en.at(-1)?.metadata?.status === 'running')!
    return <I18nProvider><MarkdownMessageContent content="" contentParts={projectDesktopContentParts(frame.parts.en)} enableProcessSession isMessageStreaming isProcessActive /></I18nProvider>
  }
  const { container, rerender } = render(show(1))
  expect(screen.getByRole('button', { name: 'Running example tool 1' }).querySelector('.shimmer-text--active')).not.toBeNull()
  rerender(show(4))
  expect(container.querySelector('.chat-tool-run-group__toggle')).toHaveTextContent('Running example tool 4')
  expect(container.querySelector('.chat-tool-run-group__toggle .shimmer-text--active')).not.toBeNull()
})
