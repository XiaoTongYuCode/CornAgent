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

it('continues through email verification and resends without losing the email', async () => {
  let authenticated = false
  let challenge = 0
  const fetch = vi.fn().mockImplementation((url: string, init?: RequestInit) => {
    if (url.endsWith('/email/code')) return Promise.resolve(response({ challenge_id: `challenge-${++challenge}` }))
    if (url.endsWith('/email/verify')) {
      expect(JSON.parse(String(init?.body))).toEqual({ challenge_id: 'challenge-2', code: '123456' })
      authenticated = true
      return Promise.resolve(response({ ok: true }))
    }
    return Promise.resolve(response({ enabled: true, mode: 'account', user_id: authenticated ? 'alice' : null }))
  })
  vi.stubGlobal('fetch', fetch)
  render(<AuthGate>{(id) => <p>workspace:{id}</p>}</AuthGate>)
  fireEvent.change(await screen.findByLabelText('邮箱'), { target: { value: 'alice@example.com' } })
  fireEvent.click(screen.getByRole('button', { name: '继续' }))
  await screen.findByRole('heading', { name: '查看你的邮箱' })
  expect(screen.getByText('alice@example.com')).toBeInTheDocument()
  expect(screen.getByLabelText('邮箱验证码')).toHaveFocus()
  fireEvent.click(screen.getByRole('checkbox', { name: '设置或重置密码' }))
  expect(screen.getByLabelText(/密码.*使用/)).toHaveAttribute('minlength', '8')
  fireEvent.click(screen.getByRole('checkbox', { name: '设置或重置密码' }))
  fireEvent.click(screen.getByRole('button', { name: '重新获取验证码' }))
  await waitFor(() => expect(challenge).toBe(2))
  await waitFor(() => expect(screen.getByRole('button', { name: '继续' })).toBeEnabled())
  fireEvent.change(screen.getByLabelText('邮箱验证码'), { target: { value: '123456' } })
  fireEvent.click(screen.getByRole('button', { name: '继续' }))
  await screen.findByText('workspace:alice')
})

it('keeps email on method changes and allows correcting it after requesting a code', async () => {
  vi.stubGlobal('fetch', vi.fn().mockImplementation((url: string) => Promise.resolve(response(
    url.endsWith('/email/code') ? { challenge_id: 'challenge' } : { enabled: true, mode: 'account', user_id: null },
  ))))
  render(<AuthGate>{(id) => <p>workspace:{id}</p>}</AuthGate>)
  fireEvent.change(await screen.findByLabelText('邮箱'), { target: { value: 'alice@example.com' } })
  fireEvent.click(screen.getByRole('button', { name: '使用密码登录' }))
  expect(screen.getByLabelText('邮箱')).toHaveValue('alice@example.com')
  fireEvent.change(screen.getByLabelText('密码'), { target: { value: 'private-password' } })
  fireEvent.click(screen.getByRole('button', { name: '使用邮箱验证码登录' }))
  expect(screen.queryByLabelText('密码')).not.toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: '继续' }))
  await screen.findByRole('heading', { name: '查看你的邮箱' })
  fireEvent.click(screen.getByRole('button', { name: '更换邮箱' }))
  expect(screen.getByLabelText('邮箱')).toHaveValue('alice@example.com')
  expect(screen.getByLabelText('邮箱')).toHaveFocus()
  expect(screen.queryByLabelText('邮箱验证码')).not.toBeInTheDocument()
})

it('explains when adding a passkey requires a recent sign-in', async () => {
  vi.stubGlobal('isSecureContext', true)
  vi.stubGlobal('PublicKeyCredential', class {})
  vi.stubGlobal('fetch', vi.fn().mockImplementation((url: string) => Promise.resolve(
    url.endsWith('/passkeys/register/options')
      ? new Response(JSON.stringify({ error: { code: 'reauthentication_required' } }), { status: 401 })
      : response({ enabled: true, mode: 'account', user_id: 'alice' }),
  )))
  render(<AuthGate>{(_id, controls) => <>{controls}</>}</AuthGate>)
  fireEvent.click(await screen.findByRole('button', { name: '添加 Passkey' }))
  await screen.findByText('请退出并重新登录，再添加 Passkey（需要在登录后 10 分钟内操作）。')
})
