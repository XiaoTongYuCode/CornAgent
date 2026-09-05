import { act, fireEvent, render, screen } from '@testing-library/react'
import { useConversationScroll } from './useConversationScroll'

let viewportHeight: number
let contentHeight: number
let resize: () => void

function Harness({ sessionId = 'session', turnId = 'turn-1', loadOlder = async () => undefined }: {
  sessionId?: string
  turnId?: string
  loadOlder?: () => Promise<void>
}) {
  const { viewportRef, contentRef, onScroll, atBottom, followLatest, loadOlderWithAnchor } = useConversationScroll({ sessionId, turnId, loadOlder })
  return <>
    <div data-testid="viewport" ref={viewportRef} onScroll={onScroll}>
      <div data-testid="content" ref={contentRef} />
    </div>
    {!atBottom && <button onClick={followLatest}>Latest</button>}
    <button onClick={() => void loadOlderWithAnchor()}>Older</button>
  </>
}

beforeEach(() => {
  vi.useFakeTimers()
  viewportHeight = 600
  contentHeight = 1000
  vi.spyOn(HTMLElement.prototype, 'clientHeight', 'get').mockImplementation(() => viewportHeight)
  vi.spyOn(HTMLElement.prototype, 'scrollHeight', 'get').mockImplementation(() => contentHeight)
  Object.defineProperty(HTMLElement.prototype, 'scrollTo', {
    configurable: true,
    value(this: HTMLElement, { top }: ScrollToOptions) {
      this.scrollTop = Math.max(0, Math.min(top ?? 0, contentHeight - viewportHeight))
    },
  })
  vi.stubGlobal('ResizeObserver', class {
    constructor(callback: () => void) { resize = callback }
    observe() {}
    disconnect() {}
  })
})

afterEach(() => { delete (HTMLElement.prototype as Partial<HTMLElement>).scrollTo })

it('follows growing answers until the reader scrolls up, then resumes on request', () => {
  render(<Harness />)
  const viewport = screen.getByTestId('viewport')
  expect(viewport.scrollTop).toBe(400)
  contentHeight = 1200
  act(() => resize())
  expect(viewport.scrollTop).toBe(600)

  fireEvent.scroll(viewport, { target: { scrollTop: 200 } })
  contentHeight = 1400
  act(() => resize())
  expect(viewport.scrollTop).toBe(200)
  fireEvent.click(screen.getByRole('button', { name: 'Latest' }))
  act(() => vi.advanceTimersByTime(400))
  expect(viewport.scrollTop).toBe(800)
})

it('starts a new turn in view even when reading history and responds to viewport resize', () => {
  const { rerender } = render(<Harness />)
  const viewport = screen.getByTestId('viewport')
  fireEvent.scroll(viewport, { target: { scrollTop: 100 } })
  contentHeight = 1800
  rerender(<Harness turnId="turn-2" />)
  act(() => vi.advanceTimersByTime(400))
  expect(viewport.scrollTop).toBe(1200)
  viewportHeight = 450
  act(() => resize())
  expect(screen.getByTestId('content').style.getPropertyValue('--conversation-viewport-height')).toBe('450px')
  expect(viewport.scrollTop).toBe(1350)
})

it('animates a new turn without streaming resizes snapping to the end or disabling follow', () => {
  const { rerender } = render(<Harness />)
  const viewport = screen.getByTestId('viewport')
  contentHeight = 1800
  rerender(<Harness turnId="turn-2" />)
  expect(viewport.scrollTop).toBe(400)
  act(() => vi.advanceTimersByTime(80))
  const intermediateTop = viewport.scrollTop
  expect(intermediateTop).toBeGreaterThan(400)
  expect(intermediateTop).toBeLessThan(1200)
  fireEvent.scroll(viewport)
  contentHeight = 2000
  act(() => resize())
  expect(viewport.scrollTop).toBe(intermediateTop)
  act(() => vi.advanceTimersByTime(400))
  expect(viewport.scrollTop).toBe(1400)
  contentHeight = 2200
  act(() => resize())
  expect(viewport.scrollTop).toBe(1600)
})

it('lets the reader interrupt a transition without later frames pulling them back', () => {
  const { rerender } = render(<Harness />)
  const viewport = screen.getByTestId('viewport')
  contentHeight = 1800
  rerender(<Harness turnId="turn-2" />)
  act(() => vi.advanceTimersByTime(80))
  const readingTop = viewport.scrollTop - 100
  fireEvent.wheel(viewport, { deltaY: -100 })
  expect(screen.getByRole('button', { name: 'Latest' })).toBeInTheDocument()
  fireEvent.scroll(viewport, { target: { scrollTop: readingTop } })
  act(() => vi.advanceTimersByTime(400))
  contentHeight = 2000
  act(() => resize())
  expect(viewport.scrollTop).toBe(readingTop)
  expect(screen.getByRole('button', { name: 'Latest' })).toBeInTheDocument()
})

it('respects reduced motion for new turns', () => {
  const media = window.matchMedia('(prefers-reduced-motion: reduce)')
  vi.spyOn(window, 'matchMedia').mockReturnValue({ ...media, matches: true })
  const { rerender } = render(<Harness />)
  contentHeight = 1800
  rerender(<Harness turnId="turn-2" />)
  expect(screen.getByTestId('viewport').scrollTop).toBe(1200)
})

it('preserves the reading position when history is prepended', async () => {
  const loadOlder = async () => { contentHeight += 350 }
  render(<Harness loadOlder={loadOlder} />)
  const viewport = screen.getByTestId('viewport')
  fireEvent.scroll(viewport, { target: { scrollTop: 100 } })
  await act(async () => {
    fireEvent.click(screen.getByRole('button', { name: 'Older' }))
    await vi.runAllTimersAsync()
  })
  expect(viewport.scrollTop).toBe(450)
})

it('does not restore a stale history position after changing turns or sessions', async () => {
  let finish!: () => void
  const loadOlder = () => new Promise<void>((resolve) => { finish = resolve })
  const { rerender } = render(<Harness loadOlder={loadOlder} />)
  const viewport = screen.getByTestId('viewport')
  fireEvent.scroll(viewport, { target: { scrollTop: 100 } })
  fireEvent.click(screen.getByRole('button', { name: 'Older' }))
  contentHeight = 1600
  rerender(<Harness sessionId="other-session" loadOlder={loadOlder} />)
  expect(viewport.scrollTop).toBe(1000)
  await act(async () => {
    finish()
    await vi.runAllTimersAsync()
  })
  expect(viewport.scrollTop).toBe(1000)
})
