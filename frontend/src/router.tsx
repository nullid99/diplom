import { useSyncExternalStore, type AnchorHTMLAttributes, type MouseEvent } from 'react'
const subscribe = (notify: () => void) => { window.addEventListener('popstate', notify); return () => window.removeEventListener('popstate', notify) }
export function usePathname() { return useSyncExternalStore(subscribe, () => window.location.pathname) }
export function navigate(path: string, replace = false) {
  if (window.location.pathname === path) return
  window.history[replace ? 'replaceState' : 'pushState']({}, '', path)
  window.dispatchEvent(new PopStateEvent('popstate'))
  window.scrollTo(0, 0)
}
export function AppLink({ href, onClick, ...props }: AnchorHTMLAttributes<HTMLAnchorElement> & { href: string }) {
  function follow(event: MouseEvent<HTMLAnchorElement>) {
    onClick?.(event)
    if (!event.defaultPrevented && event.button === 0 && !event.ctrlKey && !event.metaKey && !event.shiftKey && !event.altKey && !props.target) {
      event.preventDefault(); navigate(href)
    }
  }
  return <a href={href} onClick={follow} {...props} />
}
