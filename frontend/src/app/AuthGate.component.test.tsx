import { render, screen, waitFor, act, fireEvent } from '@testing-library/react'
import { AuthGate } from './AuthGate'

const response = (body: unknown) => new Response(JSON.stringify(body), { status: 200 })
afterEach(() => {
  vi.unstubAllGlobals()
})
it('does not mount a workspace until the server establishes an identity', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn().mockResolvedValue(response({ enabled: true, mode: 'account', user_id: null })),
  )
  render(<AuthGate>{(id) => <p>workspace:{id}</p>}</AuthGate>)
  expect(screen.queryByText(/workspace:/)).not.toBeInTheDocument()
  await screen.findByRole('heading', { name: '登录' })
  expect(screen.getByLabelText('邮箱')).toHaveAttribute('type', 'email')
  expect(screen.queryByText(/workspace:/)).not.toBeInTheDocument()
})
it('preserves the default shared workspace without account controls', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn().mockResolvedValue(response({ enabled: false, mode: null, user_id: 'local' })),
  )
  render(
    <AuthGate>
      {(id, controls) => (
        <>
          <p>workspace:{id}</p>
          {controls}
        </>
      )}
    </AuthGate>,
  )
  await screen.findByText('workspace:local')
  expect(screen.queryByRole('button', { name: '退出登录' })).not.toBeInTheDocument()
})
it('unmounts private content when authentication expires', async () => {
  const fetch = vi
    .fn()
    .mockImplementation(() =>
      Promise.resolve(response({ enabled: true, mode: 'account', user_id: 'alice' })),
    )
  vi.stubGlobal('fetch', fetch)
  render(<AuthGate>{(id) => <p>workspace:{id}</p>}</AuthGate>)
  await screen.findByText('workspace:alice')
  fetch.mockImplementation(() =>
    Promise.resolve(response({ enabled: true, mode: 'account', user_id: null })),
  )
  act(() => {
    window.dispatchEvent(new Event('cornagent-auth-expired'))
  })
  await waitFor(() => expect(screen.queryByText('workspace:alice')).not.toBeInTheDocument())
})


it('clears private content after logout even if the session refresh fails', async () => {
  const fetch = vi.fn().mockImplementation((url: string) => {
    if (url.endsWith('/logout')) return Promise.resolve(response({ ok: true }))
    return Promise.resolve(response({ enabled: true, mode: 'account', user_id: 'alice' }))
  })
  vi.stubGlobal('fetch', fetch)
  render(<AuthGate>{(id, controls) => <><p>workspace:{id}</p>{controls}</>}</AuthGate>)
  await screen.findByText('workspace:alice')
  fetch.mockImplementation((url: string) => url.endsWith('/logout')
    ? Promise.resolve(response({ ok: true })) : Promise.reject(new TypeError('offline')))
  fireEvent.click(screen.getByRole('button', { name: '退出登录' }))
  await waitFor(() => expect(screen.queryByText('workspace:alice')).not.toBeInTheDocument())
  await screen.findByRole('button', { name: '重试' })
})
