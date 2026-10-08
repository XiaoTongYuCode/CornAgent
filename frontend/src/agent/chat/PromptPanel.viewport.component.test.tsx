import { fireEvent, render, screen } from '@testing-library/react'
import { PromptPanel } from './PromptPanel'

it.each(['agent-chat-page', 'agent-drawer'])(
  'keeps the mobile composer inside the visual viewport in %s',
  (className) => {
    const viewport = Object.assign(new EventTarget(), {
      height: 700,
      offsetTop: 0,
      scale: 1,
    })
    const mobile = Object.assign(new EventTarget(), { matches: true })
    vi.stubGlobal('visualViewport', viewport)
    vi.spyOn(window, 'matchMedia').mockReturnValue(mobile as unknown as MediaQueryList)
    const view = render(
      <div className={className}>
        <PromptPanel className="agent-conversation-prompt" onStartResearch={() => {}} />
      </div>,
    )
    const host = view.container.querySelector<HTMLElement>(`.${className}`)!
    const height = () => host.style.getPropertyValue('--agent-viewport-height')
    const top = () => host.style.getPropertyValue('--agent-viewport-top')
    expect(height()).toBe('700px')
    expect(top()).toBe('0px')

    // iOS 聚焦会平移文档，失焦后仍可能保留该滚动位置。
    vi.spyOn(host, 'getBoundingClientRect').mockReturnValue(new DOMRect(0, -320, 393, 700))
    vi.spyOn(window, 'scrollY', 'get').mockReturnValue(320)

    viewport.height = 340
    viewport.dispatchEvent(new Event('resize'))
    expect(height()).toBe('340px')
    viewport.offsetTop = 24
    viewport.dispatchEvent(new Event('scroll'))
    expect(height()).toBe('340px')
    expect(top()).toBe('24px')

    viewport.height = 360
    window.dispatchEvent(new Event('resize'))
    expect(height()).toBe('360px')
    viewport.offsetTop = 0
    window.dispatchEvent(new Event('scroll'))
    expect(top()).toBe('0px')

    viewport.scale = 1.5
    viewport.dispatchEvent(new Event('resize'))
    expect(height()).toBe('')
    expect(top()).toBe('')
    viewport.scale = 1
    mobile.matches = false
    mobile.dispatchEvent(new Event('change'))
    expect(height()).toBe('')
    expect(top()).toBe('')

    mobile.matches = true
    viewport.height = 700
    viewport.offsetTop = 0
    viewport.dispatchEvent(new Event('resize'))
    expect(height()).toBe('700px')
    expect(top()).toBe('0px')
    view.unmount()
    expect(height()).toBe('')
    expect(top()).toBe('')
    viewport.dispatchEvent(new Event('resize'))
    window.dispatchEvent(new Event('resize'))
    window.dispatchEvent(new Event('scroll'))
    expect(height()).toBe('')
    expect(top()).toBe('')
  },
)

it('reflows the draft height when the viewport changes without editing text', () => {
  render(<PromptPanel className="agent-conversation-prompt" value="保留草稿" onStartResearch={() => {}} />)
  const input = screen.getByRole('textbox', { name: 'Agent 问题输入框' })
  Object.defineProperty(input, 'scrollHeight', { configurable: true, value: 240 })
  fireEvent(window, new Event('resize'))
  expect(input.style.height).toBe('160px')

  Object.defineProperty(input, 'scrollHeight', { value: 44 })
  fireEvent(window, new Event('resize'))
  expect(input.style.height).toBe('44px')
  expect(input).toHaveValue('保留草稿')
})
