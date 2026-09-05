import { I18nProvider } from '../i18n'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { AgentSessionActionsMenu } from './AgentSessionActionsMenu'

describe('AgentSessionActionsMenu', () => {
  beforeEach(() => localStorage.setItem('cornagent.locale', 'en'))
  it('opens an accessible menu and deletes only after confirmation', async () => {
    const user = userEvent.setup()
    const onDelete = vi.fn(async () => undefined)
    render(
      <I18nProvider>
        <AgentSessionActionsMenu
          disabled={false}
          sessionTitle="Delete acceptance"
          onDelete={onDelete}
        />
      </I18nProvider>,
    )

    const trigger = screen.getByRole('button', { name: 'More actions' })
    await user.click(trigger)

    const menu = await screen.findByRole('menu', { name: 'Conversation actions' })
    const deleteItem = within(menu).getByRole('menuitem', { name: 'Delete conversation' })
    await waitFor(() => expect(deleteItem).toHaveFocus())
    await user.click(deleteItem)

    const dialog = await screen.findByRole('dialog', { name: 'Delete “Delete acceptance”?' })
    await waitFor(() => expect(within(dialog).getByText(/permanently deleted/)).toBeVisible())
    expect(onDelete).not.toHaveBeenCalled()
    await user.click(within(dialog).getByRole('button', { name: 'Delete conversation' }))

    await waitFor(() => expect(onDelete).toHaveBeenCalledTimes(1))
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
  })

  it('closes on Escape and restores trigger focus', async () => {
    const user = userEvent.setup()
    render(
      <I18nProvider>
        <AgentSessionActionsMenu
          disabled={false}
          sessionTitle="Keyboard acceptance"
          onDelete={vi.fn()}
        />
      </I18nProvider>,
    )

    const trigger = screen.getByRole('button', { name: 'More actions' })
    await user.click(trigger)
    await screen.findByRole('menu', { name: 'Conversation actions' })
    await user.keyboard('{Escape}')

    await waitFor(() =>
      expect(screen.queryByRole('menu', { name: 'Conversation actions' })).not.toBeInTheDocument(),
    )
    expect(trigger).toHaveFocus()
  })
})
