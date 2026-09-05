import confetti from 'canvas-confetti'

// Mix launch speeds, spreads and sizes to avoid a uniform cone of particles.
// https://www.kirilv.com/canvas-confetti/#realistic
const realisticBursts: confetti.Options[] = [
  { particleCount: 50, spread: 26, startVelocity: 55 },
  { particleCount: 40, spread: 60 },
  { particleCount: 70, spread: 100, decay: 0.91, scalar: 0.8 },
  { particleCount: 20, spread: 120, startVelocity: 25, decay: 0.92, scalar: 1.2 },
  { particleCount: 20, spread: 120, startVelocity: 45 },
]

const defaults: confetti.Options = {
  colors: ['#26ccff', '#a25afd', '#ff5e7e', '#88ff5a', '#fcff42', '#ffa62d', '#ff36ff'],
  zIndex: 340,
  disableForReducedMotion: true,
}

const launchers: confetti.Options[] = [
  { angle: 60, origin: { x: 0, y: 0.7 } },
  { angle: 120, origin: { x: 1, y: 0.7 } },
]

export function celebrateAgentOutput(): void {
  if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return
  for (const launcher of launchers) {
    for (const burst of realisticBursts) void confetti({ ...defaults, ...launcher, ...burst })
  }
}
