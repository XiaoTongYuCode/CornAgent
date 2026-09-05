import '@testing-library/jest-dom/vitest'
import { TransformStream } from 'node:stream/web'
import { cleanup } from '@testing-library/react'

Object.defineProperty(globalThis, 'TransformStream', {
  configurable: true,
  writable: true,
  value: TransformStream,
})

const originalConsoleError = console.error
let consoleErrorSpy: ReturnType<typeof vi.spyOn>
let testLocalStorage: Storage

function createMemoryStorage(): Storage {
  const values = new Map<string, string>()
  return {
    get length() { return values.size },
    clear: () => values.clear(),
    getItem: (key) => values.get(key) ?? null,
    key: (index) => [...values.keys()][index] ?? null,
    removeItem: (key) => { values.delete(key) },
    setItem: (key, value) => { values.set(key, String(value)) },
  }
}

beforeEach(() => {
  testLocalStorage = createMemoryStorage()
  vi.stubGlobal('localStorage', testLocalStorage)
  Object.defineProperty(window, 'localStorage', { configurable: true, value: testLocalStorage })
  consoleErrorSpy = vi.spyOn(console, 'error').mockImplementation((...args: unknown[]) => {
    originalConsoleError(...args)
  })
})


afterEach(() => {
  cleanup()
  const actWarnings = consoleErrorSpy.mock.calls
    .map((args) => args.map(String).join(' '))
    .filter((message) => /not wrapped in act|wrap-tests-with-act/.test(message))
  vi.useRealTimers()
  testLocalStorage.clear()
  sessionStorage.clear()
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
  window.history.replaceState({}, '', '/')
  if (actWarnings.length) throw new Error(`React act warning:\n${actWarnings.join('\n')}`)
})

class TestResizeObserver implements ResizeObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
}

Object.defineProperty(globalThis, 'ResizeObserver', {
  configurable: true,
  writable: true,
  value: TestResizeObserver,
})

class TestIntersectionObserver implements IntersectionObserver {
  readonly root = null
  readonly rootMargin = '0px'
  readonly thresholds = [0]
  private readonly callback: IntersectionObserverCallback

  constructor(callback: IntersectionObserverCallback) {
    this.callback = callback
  }

  disconnect() {}
  observe(target: Element) {
    this.callback([{ isIntersecting: true, target } as IntersectionObserverEntry], this)
  }
  takeRecords(): IntersectionObserverEntry[] { return [] }
  unobserve() {}
}

Object.defineProperty(globalThis, 'IntersectionObserver', {
  configurable: true,
  writable: true,
  value: TestIntersectionObserver,
})

Object.defineProperty(globalThis, 'matchMedia', {
  configurable: true,
  writable: true,
  value: (query: string): MediaQueryList => ({
    matches: false,
    media: query,
    onchange: null,
    addEventListener() {},
    removeEventListener() {},
    addListener() {},
    removeListener() {},
    dispatchEvent: () => false,
  }),
})
