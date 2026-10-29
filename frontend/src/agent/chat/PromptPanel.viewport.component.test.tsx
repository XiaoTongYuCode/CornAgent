import { fireEvent, render, screen } from '@testing-library/react'
import { PromptPanel } from './PromptPanel'

const iphoneSafari = 'Mozilla/5.0 (iPhone; CPU iPhone OS 26_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/26.5 Mobile/15E148 Safari/604.1'

describe.each(['agent-chat-page', 'agent-drawer'])('%s Safari keyboard animation', (className) => {
  it.each([
    ['iPhone', iphoneSafari, 'iPhone', 5],
    ['iPad', iphoneSafari.replaceAll('iPhone', 'iPad'), 'iPad', 5],
    ['iPad desktop mode', 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/26.5 Safari/605.1.15', 'MacIntel', 5],
  ] as const)('compensates root scrolling before the next frame on %s', (_, userAgent, platform, maxTouchPoints) => {
    vi.stubGlobal('navigator', { userAgent, platform, maxTouchPoints, languages: ['zh-CN'] })
    const viewport = Object.assign(new EventTarget(), { height: 714, offsetTop: 0, scale: 1 })
    const mobile = Object.assign(new EventTarget(), { matches: true })
    vi.stubGlobal('visualViewport', viewport)
    vi.spyOn(window, 'matchMedia').mockReturnValue(mobile as unknown as MediaQueryList)
    const scrollY = vi.spyOn(window, 'scrollY', 'get').mockReturnValue(0)
    const innerHeight = vi.spyOn(window, 'innerHeight', 'get').mockReturnValue(714)
    const onSubmit = vi.fn()
    const view = render(<div className={className}>
      <PromptPanel className="agent-conversation-prompt" onStartResearch={onSubmit} />
    </div>)
    const host = view.container.querySelector<HTMLElement>(`.${className}`)!
    const input = screen.getByRole<HTMLTextAreaElement>('textbox', { name: 'Agent 问题输入框' })
    const height = () => host.style.getPropertyValue('--agent-viewport-height')
    const top = () => host.style.getPropertyValue('--agent-viewport-top')
    fireEvent.change(input, { target: { value: '保留中文草稿和选区' } })
    input.focus()
    input.setSelectionRange(2, 6)

    // Replay Safari's delayed offsetTop: the document has already moved, but
    // visualViewport will not report its new offset until the animation ends.
    viewport.height = 377
    viewport.dispatchEvent(new Event('resize'))
    scrollY.mockReturnValue(337)
    window.dispatchEvent(new Event('scroll'))
    expect(top()).toBe('337px') // Synchronous: no rAF or React commit to await.
    expect(height()).toBe('377px')
    viewport.offsetTop = 337
    viewport.dispatchEvent(new Event('scroll'))
    expect(top()).toBe('337px')

    // Layout viewport animation must not change the height source mid-flight.
    for (const animatedHeight of [650, 604, 500, 377]) {
      innerHeight.mockReturnValue(animatedHeight)
      window.dispatchEvent(new Event('resize'))
      expect(height()).toBe('377px')
    }
    fireEvent.compositionStart(input)
    fireEvent.keyDown(input, { key: 'Enter', isComposing: true })
    expect(onSubmit).not.toHaveBeenCalled()
    fireEvent.compositionEnd(input)

    // Dismissal has the reverse race: scrollY is reset while offsetTop is stale.
    scrollY.mockReturnValue(0)
    window.dispatchEvent(new Event('scroll'))
    expect(top()).toBe('0px')
    viewport.height = 714
    viewport.dispatchEvent(new Event('resize'))
    expect(height()).toBe('714px')
    expect(top()).toBe('0px')
    viewport.offsetTop = 0
    viewport.dispatchEvent(new Event('scroll'))

    expect(screen.getByRole('textbox', { name: 'Agent 问题输入框' })).toBe(input)
    expect(input).toHaveFocus()
    expect(input).toHaveValue('保留中文草稿和选区')
    expect([input.selectionStart, input.selectionEnd]).toEqual([2, 6])

    // A second focus and rotation still use the current visual viewport.
    input.blur()
    input.focus({ preventScroll: true })
    viewport.height = 180
    scrollY.mockReturnValue(120)
    window.dispatchEvent(new Event('resize'))
    expect(height()).toBe('180px')
    expect(top()).toBe('120px')
    viewport.scale = 1.5
    viewport.dispatchEvent(new Event('resize'))
    expect(height()).toBe('')
    expect(top()).toBe('')
    viewport.scale = 1
    viewport.dispatchEvent(new Event('resize'))
    expect(top()).toBe('120px')
    view.unmount()
    viewport.dispatchEvent(new Event('resize'))
    viewport.dispatchEvent(new Event('scroll'))
    window.dispatchEvent(new Event('scroll'))
    expect(height()).toBe('')
    expect(top()).toBe('')
  })
})

describe.each([
  ['iOS Chrome', iphoneSafari.replace('Version/26.5', 'CriOS/140.0.0.0')],
  ['Android Chrome', 'Mozilla/5.0 (Linux; Android 15) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Mobile Safari/537.36'],
  ['desktop Safari', 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/26.5 Safari/605.1.15'],
])('%s visual viewport', (_, userAgent) => {
  it.each(['agent-chat-page', 'agent-drawer'])(
    'keeps the mobile composer inside the visual viewport in %s',
    (className) => {
      vi.stubGlobal('navigator', { userAgent, platform: 'MacIntel', maxTouchPoints: 0, languages: ['zh-CN'] })
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

      // Other browsers retain visual viewport coordinates even if the root scrolls.
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
})

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
