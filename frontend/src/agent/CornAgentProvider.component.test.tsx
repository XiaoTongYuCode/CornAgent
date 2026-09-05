import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { CornAgentApiTransport } from '../api/transport'
import { useAppTheme } from '../app/AppThemeContext'
import { useI18n } from '../i18n'
import { AgentLauncher } from './AgentLauncher'
import { AgentSidebar } from './AgentSidebar'
import { CornAgentProvider } from './CornAgentProvider'

function Preferences() {
  const { toggleLocale } = useI18n()
  const { toggleTheme } = useAppTheme()
  return (
    <>
      <button onClick={toggleLocale}>语言</button>
      <button onClick={toggleTheme}>主题</button>
    </>
  )
}

it('shares a workspace between the launcher and overlay without reloading it on preference changes', async () => {
  const user = userEvent.setup()
  const get = vi.fn(async (path: string) =>
    path === '/agent/status'
      ? { available: false, file_input: { enabled: false, accepts: [], max_count: 0, max_total_bytes: 0 } }
      : { data: [], next_cursor: null },
  )
  const transport = {
    kind: 'cornagent-http',
    get,
    mutate: vi.fn(),
    openEventStream: vi.fn(),
  } as unknown as CornAgentApiTransport
  render(
    <CornAgentProvider transport={transport} sessionId={null}>
      <Preferences />
      <AgentLauncher />
      <AgentSidebar />
    </CornAgentProvider>,
  )
  await user.click(screen.getByRole('button', { name: '询问AI' }))
  expect(await screen.findByRole('heading', { name: 'Agent 暂不可用' })).toBeVisible()
  expect(document.querySelector('.agent-drawer--overlay')).toBeInTheDocument()
  const initialRequests = get.mock.calls.length
  await user.click(screen.getByRole('button', { name: '语言' }))
  await user.click(screen.getByRole('button', { name: '主题' }))
  expect(screen.getByRole('heading', { name: 'Agent unavailable' })).toBeVisible()
  expect(get).toHaveBeenCalledTimes(initialRequests)
  expect(transport.openEventStream).not.toHaveBeenCalled()
  await user.click(screen.getByRole('button', { name: 'Close agent' }))
  await waitFor(() => expect(document.querySelector('.agent-drawer')).toBeNull())
})
