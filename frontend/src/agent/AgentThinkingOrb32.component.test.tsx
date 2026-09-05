import { render } from '@testing-library/react'

import { AgentThinkingOrb32 } from './AgentThinkingOrb32'

it.each([
  ['composing', 258, 'Composing…'],
  ['breathing', 184, 'Thinking…'],
] as const)('renders the tuned 32px %s preset as a static high-DPI frame for reduced motion', (state, arcCount, accessibleName) => {
  const context = {
    arc: vi.fn(),
    beginPath: vi.fn(),
    clearRect: vi.fn(),
    fill: vi.fn(),
    fillStyle: '',
    setTransform: vi.fn(),
  } as unknown as CanvasRenderingContext2D
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(context)
  vi.stubGlobal('devicePixelRatio', 2)
  vi.stubGlobal('matchMedia', () => ({
    matches: true,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  }))
  const requestAnimationFrame = vi.spyOn(window, 'requestAnimationFrame')

  const { container } = render(<AgentThinkingOrb32 state={state} />)

  const canvas = container.querySelector('canvas')
  expect(canvas).toHaveStyle({ width: '32px', height: '32px' })
  expect(canvas).toHaveAttribute('width', '64')
  expect(canvas).toHaveAttribute('height', '64')
  expect(canvas).toHaveAccessibleName(accessibleName)
  expect(context.setTransform).toHaveBeenCalledWith(2, 0, 0, 2, 0, 0)
  expect(context.clearRect).toHaveBeenCalledWith(0, 0, 32, 32)
  expect(context.arc).toHaveBeenCalledTimes(arcCount)
  expect(requestAnimationFrame).not.toHaveBeenCalled()
})
