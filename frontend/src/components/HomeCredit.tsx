import confetti from 'canvas-confetti'
import type { MouseEvent } from 'react'
import { useI18n } from '../i18n'

function celebrate(event: MouseEvent<HTMLButtonElement>) {
  if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return
  const rect = event.currentTarget.getBoundingClientRect()
  const origin = {
    x: (rect.left + rect.width / 2) / window.innerWidth,
    y: (rect.top + rect.height / 2) / window.innerHeight,
  }
  const options: confetti.Options = {
    origin,
    colors: ['#E8B647', '#FF769D', '#9B88ED', '#62B9F3', '#87CBA0'],
    gravity: 0.9,
    ticks: 180,
    zIndex: 600,
    disableForReducedMotion: true,
  }
  void confetti({ ...options, particleCount: 85, spread: 85, startVelocity: 38 })
  void confetti({ ...options, particleCount: 45, spread: 130, startVelocity: 25, decay: 0.92, scalar: 0.8 })
}

export function HomeCredit() {
  const { t } = useI18n()
  return (
    <footer className="home-credit">
      <button type="button" className="home-credit-button" title={t('creatorCelebration')} onClick={celebrate}>
        {t('creatorCredit')}
      </button>
    </footer>
  )
}
