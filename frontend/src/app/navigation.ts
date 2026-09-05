import { useSyncExternalStore } from 'react'
const subscribe = (listener: () => void) => {
  window.addEventListener('popstate', listener)
  return () => window.removeEventListener('popstate', listener)
}
const pathname = () => window.location.pathname
export const usePathname = () => useSyncExternalStore(subscribe, pathname, () => '/chat')
export function navigate(path: string) {
  if (pathname() === path) return
  window.history.pushState({}, '', path)
  window.dispatchEvent(new PopStateEvent('popstate'))
}
const subscribeMobile = (listener: () => void) => {
  const media = window.matchMedia('(max-width: 864px)')
  media.addEventListener('change', listener)
  return () => media.removeEventListener('change', listener)
}
const isMobile = () => window.matchMedia('(max-width: 864px)').matches
export const useMobileLayout = () => useSyncExternalStore(subscribeMobile, isMobile, () => false)
