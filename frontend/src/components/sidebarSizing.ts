export const SIDEBAR_MIN_WIDTH = 200
export const SIDEBAR_MAX_WIDTH = 275
export const SIDEBAR_KEYBOARD_STEP = 8
export const SIDEBAR_WIDTH_STORAGE_KEY = 'cornagent-sidebar-width:v1'

export function clampSidebarWidth(width: number): number {
  return Math.min(SIDEBAR_MAX_WIDTH, Math.max(SIDEBAR_MIN_WIDTH, Math.round(width)))
}

export function readSidebarWidth(): number {
  try {
    const savedWidth = Number(window.localStorage?.getItem?.(SIDEBAR_WIDTH_STORAGE_KEY))
    return Number.isFinite(savedWidth) && savedWidth > 0
      ? clampSidebarWidth(savedWidth)
      : SIDEBAR_MAX_WIDTH
  } catch {
    return SIDEBAR_MAX_WIDTH
  }
}

export function storeSidebarWidth(width: number) {
  try {
    window.localStorage?.setItem?.(SIDEBAR_WIDTH_STORAGE_KEY, String(width))
  } catch {
    // Storage is an enhancement; the current page keeps the chosen width.
  }
}
