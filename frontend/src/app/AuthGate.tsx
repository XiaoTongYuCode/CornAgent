import type { startAuthentication, startRegistration } from '@simplewebauthn/browser'
import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react'
import { KeyRound, Mail, LockKeyhole } from 'lucide-react'
import cornAgentIcon from '../../../assets/brand/cornagent.svg'
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
  if (!response.ok) {
    const body = await response.json().catch(() => null)
    throw new Error(body?.error?.code ?? 'authentication_failed')
  }
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
  const verifying = method === 'code' && Boolean(challenge)
  function resetChallenge() {
    setChallenge('')
    setCode('')
    setPassword('')
    setNewPassword(false)
    setError(false)
  }
  return (
    <main className="auth-page">
      <a className="auth-brand" href="/chat" aria-label="CornAgent">
        <img src={cornAgentIcon} alt="" />
        <span>CornAgent</span>
      </a>
      <div className="auth-main">
        <section className="auth-card" aria-labelledby="auth-title" aria-busy={busy}>
          <h1 id="auth-title">{t(verifying ? 'authCheckEmail' : 'authSignIn')}</h1>
          {!ready ? (
            <>
              <p className="auth-description" role="status">{t(failed ? 'authFailed' : 'authLoading')}</p>
              {failed && <button className="auth-primary" onClick={() => { void onLogin() }}>{t('authRetry')}</button>}
            </>
          ) : (
            <>
              {!verifying && (
                <>
                  <button
                    className="auth-passkey"
                    type="button"
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
                    <KeyRound size={16} aria-hidden="true" />
                    {t('authPasskey')}
                  </button>
                  <div className="auth-divider" />
                </>
              )}
              <form
                onSubmit={(event) => {
                  event.preventDefault()
                  if (busy) return
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
                {verifying ? (
                  <>
                    <div className="auth-description" role="status">
                      <p>{t('authCodeSent')}</p>
                      <div className="auth-email-summary">{email}</div>
                    </div>
                    <label className="auth-field">
                      <span className="sr-only">{t('authEmailCode')}</span>
                      <span className="auth-input">
                        <Mail size={16} aria-hidden="true" />
                        <input
                          key="verification-code"
                          autoFocus
                          required
                          inputMode="numeric"
                          autoComplete="one-time-code"
                          placeholder={t('authCodePlaceholder')}
                          pattern="[0-9]{6}"
                          maxLength={6}
                          value={code}
                          disabled={busy}
                          onChange={(event) => setCode(event.target.value)}
                        />
                      </span>
                    </label>
                  </>
                ) : (
                  <label className="auth-field">
                    <span className="sr-only">{t('authEmail')}</span>
                    <span className="auth-input">
                      <Mail size={16} aria-hidden="true" />
                      <input
                        key="email"
                        autoFocus
                        required
                        type="email"
                        autoComplete="username"
                        placeholder={t('authEmailPlaceholder')}
                        maxLength={254}
                        value={email}
                        disabled={busy}
                        onChange={(event) => {
                          setEmail(event.target.value)
                          resetChallenge()
                        }}
                      />
                    </span>
                  </label>
                )}
                {(method === 'password' || (verifying && newPassword)) && (
                  <label className="auth-field">
                    <span className="sr-only">{t('authPassword')}</span>
                    <span className="auth-input">
                      <LockKeyhole size={16} aria-hidden="true" />
                      <input
                        required
                        type="password"
                        placeholder={t('authPassword')}
                        autoComplete={method === 'password' ? 'current-password' : 'new-password'}
                        minLength={method === 'password' ? 1 : 8}
                        maxLength={128}
                        value={password}
                        disabled={busy}
                        onChange={(event) => setPassword(event.target.value)}
                      />
                    </span>
                    {method === 'code' && <small>{t('authPasswordHint')}</small>}
                  </label>
                )}
                <button className="auth-primary" disabled={busy} type="submit">
                  {t(busy ? 'authWorking' : 'authContinue')}
                </button>
                {verifying && (
                  <>
                    <label className="auth-checkbox">
                      <input type="checkbox" checked={newPassword} disabled={busy}
                        onChange={(event) => setNewPassword(event.target.checked)} />
                      {t('authSetPassword')}
                    </label>
                    <div className="auth-secondary-actions">
                      <button className="auth-text-button" type="button" disabled={busy} onClick={resetChallenge}>
                        {t('authChangeEmail')}
                      </button>
                      <button className="auth-text-button" type="button" disabled={busy}
                        onClick={() => {
                          void perform(async () => {
                            const result = await request<{ challenge_id: string }>('email/code', { email })
                            setChallenge(result.challenge_id)
                            setCode('')
                          })
                        }}>
                        {t('authResend')}
                      </button>
                    </div>
                  </>
                )}
              </form>
              {!verifying && (
                <button className="auth-text-button auth-method-switch" type="button" disabled={busy}
                  onClick={() => {
                    setMethod(method === 'code' ? 'password' : 'code')
                    resetChallenge()
                  }}>
                  {t(method === 'code' ? 'authUsePassword' : 'authUseCode')}
                </button>
              )}
              {error && <p role="alert">{t('authFailed')}</p>}
            </>
          )}
        </section>
      </div>
      <footer className="auth-footer">
        <p>{t('authSignupHint')}</p>
        <nav aria-label={t('authFooter')}>
          <span>© {new Date().getFullYear()} CornAgent</span>
          <a href="https://github.com/XiaoTongYuCode/CornAgent" target="_blank" rel="noreferrer">GitHub</a>
          <button type="button" onClick={toggleLocale}>{t('authLanguage')}</button>
        </nav>
      </footer>
    </main>
  )
}

function AccountControls({ onLogout }: { onLogout: () => Promise<void> }) {
  const { t } = useI18n()
  const [busy, setBusy] = useState(false)
  const [status, setStatus] = useState<'authPasskeyAdded' | 'authFailed' | 'authReauthenticate' | 'authPasskeyUnsupported' | 'authPasskeyOrigin' | 'authPasskeyCancelled' | null>(null)
  const perform = async (operation: () => Promise<unknown>) => {
    setBusy(true)
    setStatus(null)
    try {
      await operation()
      setStatus('authPasskeyAdded')
    } catch (error) {
      const message = error instanceof Error ? error.message : ''
      const name = error instanceof Error ? error.name : ''
      setStatus(message === 'reauthentication_required' ? 'authReauthenticate'
        : message === 'passkey_origin' || name === 'SecurityError' ? 'authPasskeyOrigin'
        : message === 'passkey_unsupported' ? 'authPasskeyUnsupported'
        : name === 'NotAllowedError' || name === 'AbortError' ? 'authPasskeyCancelled'
        : 'authFailed')
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
            if (/^\d+\.\d+\.\d+\.\d+$/.test(window.location.hostname) || window.location.hostname.includes(':')) {
              throw new Error('passkey_origin')
            }
            if (!window.isSecureContext || !window.PublicKeyCredential) throw new Error('passkey_unsupported')
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
        <span role="status">{t(status)}</span>
      )}
    </div>
  )
}
