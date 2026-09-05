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

const unitSessionStorage = createMemoryStorage()
const cookies = new Map<string, string>()
const cookieDocument = {}

Object.defineProperty(cookieDocument, 'cookie', {
  configurable: true,
  get: () => [...cookies].map(([key, value]) => `${key}=${value}`).join('; '),
  set: (raw: string) => {
    const [pair] = raw.split(';')
    const separator = pair.indexOf('=')
    const key = pair.slice(0, separator).trim()
    const value = pair.slice(separator + 1).trim()
    if (/max-age=0/i.test(raw)) cookies.delete(key)
    else cookies.set(key, value)
  },
})

Object.defineProperty(globalThis, 'sessionStorage', { configurable: true, value: unitSessionStorage })
Object.defineProperty(globalThis, 'document', { configurable: true, value: cookieDocument })

beforeEach(() => {
  unitSessionStorage.clear()
  cookies.clear()
})
