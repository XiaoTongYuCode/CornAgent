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
    vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockReturnValue(new DOMRect(0, 60, 393, 700))
    const view = render(
      <div className={className}>
        <PromptPanel className="agent-conversation-prompt" onStartResearch={() => {}} />
      </div>,
    )
    const host = view.container.querySelector<HTMLElement>(`.${className}`)!
    const height = () => host.style.getPropertyValue('--agent-viewport-height')
    expect(height()).toBe('640px')

    viewport.height = 340
    viewport.dispatchEvent(new Event('resize'))
    expect(height()).toBe('280px')
    viewport.offsetTop = 24
    viewport.dispatchEvent(new Event('scroll'))
    expect(height()).toBe('304px')

    viewport.scale = 1.5
    viewport.dispatchEvent(new Event('resize'))
    expect(height()).toBe('')
    viewport.scale = 1
    mobile.matches = false
    mobile.dispatchEvent(new Event('change'))
    expect(height()).toBe('')

    mobile.matches = true
    viewport.height = 700
    viewport.offsetTop = 0
    viewport.dispatchEvent(new Event('resize'))
    expect(height()).toBe('640px')
    view.unmount()
    expect(height()).toBe('')
    viewport.dispatchEvent(new Event('resize'))
    expect(height()).toBe('')
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
