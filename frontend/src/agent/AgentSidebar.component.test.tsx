import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import type { CornAgentApiTransport } from '../api/transport'
import { AgentLauncher, AgentSidebar, CornAgentProvider, type AgentSidebarProps } from './index'

function transport() {
  return {
    kind: 'cornagent-http',
    get: vi.fn(async (path: string) => path === '/agent/status'
      ? { available: true, file_input: { enabled: false, accepts: [], max_count: 0, max_total_bytes: 0 } }
      : { data: [], next_cursor: null }),
    mutate: vi.fn(),
    openEventStream: vi.fn(),
  } as unknown as CornAgentApiTransport
}

function host(api: CornAgentApiTransport, props: AgentSidebarProps = {}) {
  return <CornAgentProvider transport={api} sessionId={null}>
    <AgentLauncher />
    <AgentSidebar {...props} />
  </CornAgentProvider>
}

async function openPanel(name = 'CornAgent') {
  await userEvent.setup().click(screen.getByRole('button', { name: '询问AI' }))
  const panel = await screen.findByRole('complementary', { name })
  await waitFor(() => expect(panel).toHaveAttribute('data-open', 'true'))
  return panel
}

beforeEach(() => {
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(null)
})

it('customizes branding and semantic slots through the public entry without losing the draft', async () => {
  const api = transport()
  const props: AgentSidebarProps = {
    title: '业务助手',
    icon: <span data-testid="brand-icon">◆</span>,
    className: 'host-sidebar',
    style: { backgroundColor: 'red' },
    classNames: { header: 'host-header', body: 'host-body', footer: 'host-footer' },
    styles: { header: { height: 64 }, body: { padding: 8 }, footer: { padding: 12 } },
    footer: <span>宿主页脚</span>,
    emptyStateFooter: <span>宿主欢迎内容</span>,
  }
  const view = render(host(api, props))
  const panel = await openPanel('业务助手')
  expect(panel).toHaveClass('host-sidebar', 'agent-drawer--overlay')
  expect(panel).toHaveStyle({ backgroundColor: 'rgb(255, 0, 0)' })
  expect(screen.getByText('业务助手')).toBeVisible()
  expect(screen.getByTestId('brand-icon')).toBeVisible()
  expect(panel.querySelector('.host-header')).toHaveStyle({ height: '64px' })
  expect(panel.querySelector('.host-body')).toHaveStyle({ padding: '8px' })
  expect(panel.querySelector('.host-footer')).toHaveStyle({ padding: '12px' })
  expect(screen.getByText('宿主欢迎内容')).toBeVisible()
  const prompt = await screen.findByRole('textbox', { name: 'Agent 问题输入框' })
  fireEvent.change(prompt, { target: { value: '保留当前草稿' } })
  const initialRequests = vi.mocked(api.get).mock.calls.length

  view.rerender(host(api, { ...props, title: <em>新的标题</em>, ariaLabel: '新的助手' }))
  expect(screen.getByRole('complementary', { name: '新的助手' })).toBe(panel)
  expect(screen.getByText('新的标题')).toBeVisible()
  expect(prompt).toHaveValue('保留当前草稿')
  expect(api.get).toHaveBeenCalledTimes(initialRequests)
  expect(api.openEventStream).not.toHaveBeenCalled()
})

it('lets a host select built-in actions while preserving animated close', async () => {
  const api = transport()
  render(host(api, {
    renderActions: ({ actions }) => <>{actions.newChat}{actions.close}</>,
  }))
  const panel = await openPanel()
  expect(screen.getByRole('button', { name: '新对话' })).toBeVisible()
  expect(panel.querySelector('.agent-history-trigger')).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: '关闭 Agent' }))
  expect(panel).toHaveAttribute('data-open', 'false')
  expect(panel).toHaveAttribute('inert')
  await waitFor(() => expect(panel).not.toBeInTheDocument())
})

it('replaces or hides the header without replacing the conversation', async () => {
  const api = transport()
  const view = render(host(api, {
    renderHeader: ({ close, busy }) => <button disabled={busy} onClick={close}>收起业务助手</button>,
    resizable: false,
  }))
  const panel = await openPanel()
  const prompt = await screen.findByRole('textbox', { name: 'Agent 问题输入框' })
  expect(screen.queryByRole('separator')).toBeNull()
  expect(screen.queryByText('CornAgent')).toBeNull()
  expect(screen.getByRole('button', { name: '收起业务助手' })).toBeEnabled()
  view.rerender(host(api, { renderHeader: () => null, resizable: false }))
  expect(panel.querySelector('header')).toBeNull()
  expect(screen.getByRole('textbox', { name: 'Agent 问题输入框' })).toBe(prompt)
  view.rerender(host(api, { renderHeader: ({ close }) => <button onClick={close}>收起业务助手</button> }))
  fireEvent.click(screen.getByRole('button', { name: '收起业务助手' }))
  await waitFor(() => expect(panel).not.toBeInTheDocument())
})

it('supports configurable width limits and an isolated persistence key', async () => {
  const user = userEvent.setup()
  const onWidthChange = vi.fn()
  render(host(transport(), { defaultWidth: 360, minWidth: 300, maxWidth: 600, widthStorageKey: 'host:panel-width', onWidthChange }))
  const panel = await openPanel()
  expect(panel).toHaveStyle({ width: '360px' })
  const separator = screen.getByRole('separator')
  expect(separator).toHaveAttribute('aria-valuemin', '300')
  expect(separator).toHaveAttribute('aria-valuemax', '600')
  await waitFor(() => expect(screen.getByRole('textbox', { name: 'Agent 问题输入框' })).toHaveFocus())
  await user.click(separator)
  expect(separator).toHaveFocus()
  await user.keyboard('{ArrowLeft}')
  expect(panel).toHaveStyle({ width: '376px' })
  expect(onWidthChange).toHaveBeenLastCalledWith(376)
  expect(localStorage.getItem('host:panel-width')).toBe('376')
  expect(localStorage.getItem('cornagent:agent-panel-width')).toBeNull()
  await user.keyboard('{End}{ArrowLeft}')
  expect(panel).toHaveStyle({ width: '600px' })
  await user.keyboard('{Home}{ArrowRight}')
  expect(panel).toHaveStyle({ width: '300px' })
  await user.click(screen.getByRole('button', { name: '关闭 Agent' }))
  await waitFor(() => expect(panel).not.toBeInTheDocument())
  expect(await openPanel()).toHaveStyle({ width: '300px' })
})

it('keeps width controlled by the host and never reads or writes its saved preference', async () => {
  localStorage.setItem('cornagent:agent-panel-width', '700')
  const onWidthChange = vi.fn()
  const api = transport()
  const view = render(host(api, { width: 440, onWidthChange }))
  const panel = await openPanel()
  expect(panel).toHaveStyle({ width: '440px' })
  fireEvent.keyDown(screen.getByRole('separator'), { key: 'ArrowLeft' })
  expect(onWidthChange).toHaveBeenLastCalledWith(456)
  expect(panel).toHaveStyle({ width: '440px' })
  view.rerender(host(api, { width: 456, onWidthChange }))
  expect(panel).toHaveStyle({ width: '456px' })
  expect(localStorage.getItem('cornagent:agent-panel-width')).toBe('700')
})

it('updates a controlled width with the standard state setter', async () => {
  const api = transport()
  function Host() {
    const [width, setWidth] = useState(420)
    return host(api, { width, onWidthChange: setWidth })
  }
  render(<Host />)
  const panel = await openPanel()
  fireEvent.keyDown(screen.getByRole('separator'), { key: 'ArrowLeft' })
  expect(panel).toHaveStyle({ width: '436px' })
  expect(panel.style.getPropertyValue('--agent-panel-width')).toBe('436px')
})

it('can disable persistence and clamps to the viewport without discarding the desired width', async () => {
  localStorage.setItem('cornagent:agent-panel-width', '700')
  const api = transport()
  const view = render(host(api, { defaultWidth: 460, widthStorageKey: null }))
  const panel = await openPanel()
  expect(panel).toHaveStyle({ width: '460px' })
  fireEvent.keyDown(screen.getByRole('separator'), { key: 'ArrowLeft' })
  expect(localStorage.getItem('cornagent:agent-panel-width')).toBe('700')
  const originalWidth = window.innerWidth
  vi.stubGlobal('innerWidth', 350)
  fireEvent(window, new Event('resize'))
  expect(panel).toHaveStyle({ width: '350px' })
  vi.stubGlobal('innerWidth', originalWidth)
  fireEvent(window, new Event('resize'))
  expect(panel).toHaveStyle({ width: '476px' })
  view.rerender(host(api, { width: Number.NaN, minWidth: -1, maxWidth: -1, defaultWidth: Number.NaN }))
  expect(panel).toHaveStyle({ width: '400px' })
})

it('persists pointer resizing and cleans up an interrupted drag', async () => {
  const api = transport()
  const onWidthChange = vi.fn()
  const view = render(host(api, { onWidthChange }))
  const panel = await openPanel()
  fireEvent.pointerDown(screen.getByRole('separator'), { clientX: 700 })
  fireEvent.pointerMove(window, { clientX: 650 })
  expect(panel).toHaveStyle({ width: '450px' })
  expect(onWidthChange).toHaveBeenLastCalledWith(450)
  fireEvent.pointerUp(window)
  expect(localStorage.getItem('cornagent:agent-panel-width')).toBe('450')
  expect(document.documentElement).not.toHaveClass('agent-panel-resizing')

  fireEvent.pointerDown(screen.getByRole('separator'), { clientX: 650 })
  expect(document.documentElement).toHaveClass('agent-panel-resizing')
  view.rerender(host(api, { resizable: false, onWidthChange }))
  expect(document.documentElement).not.toHaveClass('agent-panel-resizing')
  fireEvent.pointerMove(window, { clientX: 600 })
  expect(panel).toHaveStyle({ width: '450px' })
})
