import { render, screen, waitFor } from '@testing-library/react'
import { TextSwap } from './TextSwap'

const preference = vi.hoisted(() => ({ reduced: false }))
vi.mock('motion/react', async (importOriginal) => ({
  ...await importOriginal<typeof import('motion/react')>(),
  useReducedMotion: () => preference.reduced,
}))
beforeEach(() => { preference.reduced = false })

const show = (text: string, shimmer = false) => <button><TextSwap text={text} shimmer={shimmer} /></button>

it('keeps the outgoing visual while exposing only the latest accessible title', async () => {
  const view = render(show('正在读取', true))
  expect(screen.getByRole('button', { name: '正在读取' })).toBeVisible()
  view.rerender(show('已读取'))
  expect(screen.getByRole('button', { name: '已读取' })).toBeVisible()
  expect(view.container.querySelector('.text-swap__frame')).toHaveTextContent('正在读取')
  await waitFor(() => expect(view.container.querySelector('.text-swap__frame')).toHaveTextContent('已读取'))
  await waitFor(() => expect(view.container.querySelector('.text-swap__frame')).toHaveStyle({ opacity: 1, filter: 'blur(0px)' }))
  expect(view.container.querySelectorAll('.text-swap__frame')).toHaveLength(1)
  expect(view.container.querySelector('.shimmer-text__highlight')).toBeNull()
})

it('coalesces rapid title changes without restoring an intermediate title', async () => {
  const view = render(show('正在读取', true))
  view.rerender(show('正在核验', true))
  view.rerender(show('正在汇总', true))
  view.rerender(show('已完成'))
  await waitFor(() => expect(view.container.querySelector('.text-swap__frame')).toHaveTextContent('已完成'))
  await waitFor(() => expect(view.container.querySelector('.text-swap__frame')).toHaveStyle({ opacity: 1 }))
  expect(screen.getByRole('button')).toHaveAccessibleName('已完成')
  expect(view.container.querySelectorAll('.text-swap__frame')).toHaveLength(1)
})

it('updates immediately without transitional frames when reduced motion is requested', () => {
  preference.reduced = true
  const view = render(show('正在读取', true))
  view.rerender(show('已读取'))
  expect(screen.getByRole('button')).toHaveAccessibleName('已读取')
  expect(screen.queryByText('正在读取')).not.toBeInTheDocument()
  expect(view.container.querySelector('.text-swap__frame')).toBeNull()
})
