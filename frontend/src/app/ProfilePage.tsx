import type { ReactNode } from 'react'
import { useI18n } from '../i18n'
import './profile.css'

export function ProfilePage({ accountControls }: { accountControls?: ReactNode }) {
  const { t } = useI18n()
  return (
    <>
      <header className="topbar"><strong>{t('myProfile')}</strong></header>
      <section className="profile-page" aria-labelledby="profile-title">
        <h1 id="profile-title">{t('profileSecurity')}</h1>
        <p>{t(accountControls ? 'profileSecurityHint' : 'profileUnavailable')}</p>
        {accountControls}
      </section>
    </>
  )
}
