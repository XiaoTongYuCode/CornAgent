interface RgbColor {
  blue: number
  green: number
  red: number
}

const DEFAULT_PAPER_BACKGROUND = '#fff7e8'
const MIN_ICON_CONTRAST_RATIO = 4.5
const SUBAGENT_ICON_PALETTE = [
  { dark: '#1d4ed8', light: '#93c5fd' },
  { dark: '#6d28d9', light: '#c4b5fd' },
  { dark: '#a21caf', light: '#f0abfc' },
  { dark: '#0f766e', light: '#5eead4' },
  { dark: '#b91c1c', light: '#fca5a5' },
  { dark: '#9a3412', light: '#fdba74' },
  { dark: '#166534', light: '#86efac' },
  { dark: '#334155', light: '#cbd5e1' },
] as const

function stableHash(value: string): number {
  let hash = 2166136261
  for (let index = 0; index < value.length; index += 1) {
    hash ^= value.charCodeAt(index)
    hash = Math.imul(hash, 16777619)
  }
  return hash >>> 0
}

function parseCssColor(value: string): RgbColor | null {
  const normalized = value.trim().toLowerCase()
  const shortHex = /^#([0-9a-f]{3})$/u.exec(normalized)
  if (shortHex) {
    const [red, green, blue] = shortHex[1].split('').map((item) =>
      Number.parseInt(`${item}${item}`, 16),
    )
    return { red, green, blue }
  }

  const hex = /^#([0-9a-f]{6})$/u.exec(normalized)
  if (hex) {
    return {
      red: Number.parseInt(hex[1].slice(0, 2), 16),
      green: Number.parseInt(hex[1].slice(2, 4), 16),
      blue: Number.parseInt(hex[1].slice(4, 6), 16),
    }
  }

  const rgb = /^rgba?\(\s*(\d+(?:\.\d+)?)\s*[, ]\s*(\d+(?:\.\d+)?)\s*[, ]\s*(\d+(?:\.\d+)?)/u.exec(
    normalized,
  )
  if (!rgb) {
    return null
  }
  return {
    red: Math.min(255, Math.max(0, Number(rgb[1]))),
    green: Math.min(255, Math.max(0, Number(rgb[2]))),
    blue: Math.min(255, Math.max(0, Number(rgb[3]))),
  }
}

function relativeLuminance(color: RgbColor): number {
  const channel = (value: number) => {
    const normalized = value / 255
    return normalized <= 0.04045
      ? normalized / 12.92
      : ((normalized + 0.055) / 1.055) ** 2.4
  }
  return (
    0.2126 * channel(color.red) +
    0.7152 * channel(color.green) +
    0.0722 * channel(color.blue)
  )
}

export function getColorContrastRatio(foreground: string, background: string): number {
  const foregroundColor = parseCssColor(foreground)
  const backgroundColor = parseCssColor(background)
  if (!foregroundColor || !backgroundColor) {
    return 1
  }
  const light = Math.max(relativeLuminance(foregroundColor), relativeLuminance(backgroundColor))
  const dark = Math.min(relativeLuminance(foregroundColor), relativeLuminance(backgroundColor))
  return (light + 0.05) / (dark + 0.05)
}

function toHex(color: RgbColor): string {
  return `#${[color.red, color.green, color.blue]
    .map((value) => Math.round(value).toString(16).padStart(2, '0'))
    .join('')}`
}

export function getSubagentIconColor(seed: string, paperBackground: string): string | null {
  const normalizedSeed = seed.trim()
  if (!normalizedSeed) {
    return null
  }
  const background = parseCssColor(paperBackground) ?? parseCssColor(DEFAULT_PAPER_BACKGROUND)
  if (!background) {
    return null
  }

  const palette = SUBAGENT_ICON_PALETTE[stableHash(normalizedSeed) % SUBAGENT_ICON_PALETTE.length]
  const backgroundLuminance = relativeLuminance(background)
  const candidates = backgroundLuminance > 0.45
    ? [palette.dark, palette.light, '#111827']
    : [palette.light, palette.dark, '#f8fafc']
  const backgroundHex = toHex(background)
  let bestColor = candidates[0]
  let bestContrast = getColorContrastRatio(bestColor, backgroundHex)

  for (const candidate of candidates) {
    const contrast = getColorContrastRatio(candidate, backgroundHex)
    if (contrast >= MIN_ICON_CONTRAST_RATIO) {
      return candidate
    }
    if (contrast > bestContrast) {
      bestColor = candidate
      bestContrast = contrast
    }
  }
  return bestColor
}
