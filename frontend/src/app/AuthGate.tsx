import type { startAuthentication, startRegistration } from '@simplewebauthn/browser'
import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react'
import { I18nProvider, useI18n } from '../i18n'
import { navigate } from './navigation'
import './auth.css'

type Session = { enabled: boolean; mode: 'invisible' | 'account' | null; user_id: string | null }
type CreationOptions = Parameters<typeof startRegistration>[0]['optionsJSON']
type RequestOptions = Parameters<typeof startAuthentication>[0]['optionsJSON']
async function request<T>(path: string, body: unknown = {}): Promise<T> {
  const response = await fetch(`/api/v1/auth/${path}`, {
    method: 'POST',
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json', 'X-CornAgent-Request': '1' },
    body: JSON.stringify(body),
  })
  if (!response.ok) throw new Error('authentication_failed')
  return response.json() as Promise<T>
}
// Deduplicate StrictMode bootstrap so initial device cookies cannot race.
let pending: Promise<Session> | null = null
function getSession() {
  pending ??= request<Session>('session').finally(() => {
    pending = null
  })
  return pending
}
export function AuthGate({
  children,
}: {
  children: (principal: string, controls: ReactNode) => ReactNode
}) {
  const [session, setSession] = useState<Session | null>(null)
  const [failed, setFailed] = useState(false)
  const revision = useRef(0)
  const refresh = useCallback(async () => {
    const current = ++revision.current
    try {
      if (pending) await pending
      const next = await getSession()
      if (current !== revision.current) return
      setSession(next)
      setFailed(false)
    } catch {
      if (current === revision.current) setFailed(true)
    }
  }, [])
  useEffect(() => {
    let active = true
    const current = revision.current
    void getSession()
      .then((value) => {
        if (active && current === revision.current) setSession(value)
      })
      .catch(() => {
        if (active && current === revision.current) setFailed(true)
      })
    const check = () => {
      void refresh()
    }
    window.addEventListener('focus', check)
    window.addEventListener('cornagent-auth-expired', check)
    const timer = window.setInterval(check, 30000)
    return () => {
      active = false
      window.clearInterval(timer)
      window.removeEventListener('focus', check)
      window.removeEventListener('cornagent-auth-expired', check)
    }
  }, [refresh])
  if (!session || (session.enabled && !session.user_id))
    return (
      <I18nProvider>
        <LoginScreen ready={Boolean(session) && !failed} failed={failed} onLogin={refresh} />
      </I18nProvider>
    )
  return children(
    session.user_id ?? 'local',
    session.mode === 'account' ? (
      <AccountControls
        onLogout={async () => {
          await request('logout')
          ++revision.current
          setSession({ ...session, user_id: null })
          navigate('/chat')
          await refresh()
        }}
      />
    ) : null,
  )
}
function LoginScreen({
  ready,
  failed,
  onLogin,
}: {
  ready: boolean
  failed: boolean
  onLogin: () => Promise<void>
}) {
  const { t, toggleLocale } = useI18n()
  const [method, setMethod] = useState<'code' | 'password'>('code')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [code, setCode] = useState('')
  const [challenge, setChallenge] = useState('')
  const [newPassword, setNewPassword] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(false)
  async function perform(operation: () => Promise<unknown>) {
    setBusy(true)
    setError(false)
    try {
      await operation()
    } catch {
      setError(true)
    } finally {
      setBusy(false)
    }
  }
  return (
    <main className="auth-page">
      <section className="auth-card" aria-labelledby="auth-title">
        <h1 id="auth-title">CornAgent</h1>
        <button onClick={toggleLocale}>{t('authLanguage')}</button>
        {!ready ? (
          <>
            <p role="status">{t(failed ? 'authFailed' : 'authLoading')}</p>
            {failed && (
              <button
                onClick={() => {
                  void onLogin()
                }}
              >
                {t('authRetry')}
              </button>
            )}
          </>
        ) : (
          <>
            <h2>{t('authSignIn')}</h2>
            <div className="auth-tabs">
              {(['code', 'password'] as const).map((value) => (
                <button
                  key={value}
                  type="button"
                  aria-pressed={method === value}
                  disabled={busy}
                  onClick={() => {
                    setMethod(value)
                    setPassword('')
                    setError(false)
                  }}
                >
                  {t(value === 'code' ? 'authEmailCode' : 'authPassword')}
                </button>
              ))}
            </div>
            <form
              onSubmit={(event) => {
                event.preventDefault()
                void perform(async () => {
                  if (method === 'password') await request('password/login', { email, password })
                  else if (!challenge) {
                    const result = await request<{ challenge_id: string }>('email/code', { email })
                    setChallenge(result.challenge_id)
                    return
                  } else
                    await request('email/verify', {
                      challenge_id: challenge,
                      code,
                      ...(newPassword ? { password } : {}),
                    })
                  setPassword('')
                  navigate('/chat')
                  await onLogin()
                })
              }}
            >
              <label>
                {t('authEmail')}
                <input
                  required
                  type="email"
                  autoComplete="username"
                  maxLength={254}
                  value={email}
                  disabled={busy}
                  onChange={(event) => {
                    setEmail(event.target.value)
                    setChallenge('')
                    setCode('')
                  }}
                />
              </label>
              {method === 'code' && challenge && (
                <>
                  <p role="status">{t('authCodeSent')}</p>
                  <label>
                    {t('authEmailCode')}
                    <input
                      required
                      inputMode="numeric"
                      autoComplete="one-time-code"
                      pattern="[0-9]{6}"
                      maxLength={6}
                      value={code}
                      onChange={(event) => setCode(event.target.value)}
                    />
                  </label>
                  <label className="auth-checkbox">
                    <input
                      type="checkbox"
                      checked={newPassword}
                      onChange={(event) => setNewPassword(event.target.checked)}
                    />
                    {t('authSetPassword')}
                  </label>
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => {
                      setChallenge('')
                      setCode('')
                    }}
                  >
                    {t('authResend')}
                  </button>
                </>
              )}
              {(method === 'password' || (challenge && newPassword)) && (
                <label>
                  {t('authPassword')}
                  <input
                    required
                    type="password"
                    autoComplete={method === 'password' ? 'current-password' : 'new-password'}
                    minLength={method === 'password' ? 1 : 15}
                    maxLength={128}
                    value={password}
                    onChange={(event) => setPassword(event.target.value)}
                  />
                  {method === 'code' && <small>{t('authPasswordHint')}</small>}
                </label>
              )}
              <button className="auth-primary" disabled={busy}>
                {t(method === 'code' && !challenge ? 'authSendCode' : 'authSignIn')}
              </button>
            </form>
            <button
              disabled={busy}
              onClick={() => {
                void perform(async () => {
                  const result = await request<{ challenge_id: string; options: RequestOptions }>(
                    'passkeys/login/options',
                  )
                  const { startAuthentication } = await import('@simplewebauthn/browser')
                  const credential = await startAuthentication({ optionsJSON: result.options })
                  await request('passkeys/login/verify', {
                    challenge_id: result.challenge_id,
                    credential,
                  })
                  navigate('/chat')
                  await onLogin()
                })
              }}
            >
              {t('authPasskey')}
            </button>
            <p className="auth-help">{t('authSignupHint')}</p>
            {error && <p role="alert">{t('authFailed')}</p>}
          </>
        )}
      </section>
    </main>
  )
}
function AccountControls({ onLogout }: { onLogout: () => Promise<void> }) {
  const { t } = useI18n()
  const [busy, setBusy] = useState(false)
  const [status, setStatus] = useState<'success' | 'error' | null>(null)
  const perform = async (operation: () => Promise<unknown>) => {
    setBusy(true)
    setStatus(null)
    try {
      await operation()
      setStatus('success')
    } catch {
      setStatus('error')
    } finally {
      setBusy(false)
    }
  }
  return (
    <div className="auth-account">
      <button
        disabled={busy}
        onClick={() => {
          void perform(async () => {
            const result = await request<{ challenge_id: string; options: CreationOptions }>(
              'passkeys/register/options',
            )
            const { startRegistration } = await import('@simplewebauthn/browser')
            const credential = await startRegistration({ optionsJSON: result.options })
            await request('passkeys/register/verify', {
              challenge_id: result.challenge_id,
              credential,
            })
          })
        }}
      >
        {t('authAddPasskey')}
      </button>
      <button
        disabled={busy}
        onClick={() => {
          void perform(onLogout)
        }}
      >
        {t('authLogout')}
      </button>
      {status && (
        <span role="status">{t(status === 'success' ? 'authPasskeyAdded' : 'authFailed')}</span>
      )}
    </div>
  )
}
