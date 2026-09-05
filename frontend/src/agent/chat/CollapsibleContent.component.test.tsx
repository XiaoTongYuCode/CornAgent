import { render, screen, waitFor } from '@testing-library/react'
import { CollapsibleContent } from './CollapsibleContent'

const noop = () => undefined
const show = (open: boolean, label: string) => <CollapsibleContent
  title="过程" open={open} onOpen={noop} onClose={noop} scrollable={false}
><button>{label}</button></CollapsibleContent>

it('retains the previous body while closing and removes it from interaction immediately', async () => {
  const { rerender } = render(show(true, '旧过程'))
  const oldBody = screen.getByRole('button', { name: '旧过程' })
  rerender(show(false, '追加的新过程'))
  expect(screen.queryByText('追加的新过程')).not.toBeInTheDocument()
  const exiting = oldBody.closest('.chat-collapsible-content__body')
  expect(exiting).toHaveAttribute('aria-hidden', 'true')
  expect(exiting).toHaveAttribute('inert')
  await waitFor(() => expect(oldBody).not.toBeInTheDocument())
})

it('can reopen during exit without a stale unmount removing the updated content', async () => {
  const { rerender } = render(show(true, '旧过程'))
  rerender(show(false, '新过程'))
  rerender(show(true, '新过程'))
  const body = screen.getByRole('button', { name: '新过程' }).closest('.chat-collapsible-content__body')
  expect(body).not.toHaveAttribute('inert')
  await waitFor(() => expect(body).toHaveStyle({ height: 'auto', opacity: 1 }))
  expect(screen.queryByText('旧过程')).not.toBeInTheDocument()
})
