import { useEffect, useRef, useState, type ReactNode } from 'react'
import { AppLink } from './router'
import { Icon, type IconName } from './ui'

export const routes: { path: string; title: string; icon: IconName }[] = [
  { path: '/sources', title: 'Відеоджерела', icon: 'sources' },
  { path: '/analysis', title: 'Аналіз відео', icon: 'analysis' },
  { path: '/monitoring', title: 'Моніторинг', icon: 'monitoring' },
  { path: '/events', title: 'Журнал подій', icon: 'events' },
  { path: '/experiments', title: 'Моделі та експерименти', icon: 'experiments' },
  { path: '/settings', title: 'Налаштування', icon: 'settings' },
]
type Connection = 'waiting' | 'connected' | 'error'
const connectionLabels: Record<Connection, string> = { waiting: 'З’єднання…', connected: 'Сервер підключено', error: 'Сервер недоступний' }
function ServerConnection() {
  const [status, setStatus] = useState<Connection>('waiting')
  useEffect(() => {
    let disposed = false
    let timer: ReturnType<typeof setTimeout>
    let controller: AbortController
    async function check() {
      controller = new AbortController()
      const timeout = setTimeout(() => controller.abort(), 4000)
      try {
        const api = import.meta.env.VITE_API_BASE_URL?.trim().replace(/\/$/, '')
        if (!api) throw new Error('API URL missing')
        const response = await fetch(`${api}/api/health`, { signal: controller.signal, cache: 'no-store' })
        if (!response.ok) throw new Error('API unavailable')
        const body = await response.json()
        if (body.status !== 'ok' || body.service !== 'api') throw new Error('Invalid health')
        if (!disposed) setStatus('connected')
      } catch { if (!disposed) setStatus('error') }
      finally { clearTimeout(timeout); if (!disposed) timer = setTimeout(check, 3000) }
    }
    void check()
    return () => { disposed = true; clearTimeout(timer); controller?.abort() }
  }, [])
  return <span className={`server-status ${status}`} data-state={status} role="status" aria-live="polite"><span className="status-dot" />{connectionLabels[status]}</span>
}

export function AppLayout({ path, children }: { path: string; children: ReactNode }) {
  const [open, setOpen] = useState(false)
  const drawer = useRef<HTMLDialogElement>(null)
  const menu = useRef<HTMLButtonElement>(null)
  const current = routes.find(route => route.path === path)
  useEffect(() => { drawer.current?.close(); setOpen(false); document.title = `${current?.title || 'Сторінку не знайдено'} · FireVision` }, [path, current?.title])
  useEffect(() => {
    const media = window.matchMedia('(min-width: 1000px)')
    const resize = () => { if (media.matches) { drawer.current?.close(); setOpen(false) } }
    media.addEventListener('change', resize)
    return () => media.removeEventListener('change', resize)
  }, [])
  function navigation(mobile: boolean) {
    return <>
      <div className="sidebar-brand"><AppLink href="/sources" aria-label="FireVision — відеоджерела"><span className="brand-mark"><svg width="22" height="26" viewBox="0 0 22 26" fill="none" aria-hidden="true"><path d="M12 2C13 8 19 8 19 15a8 8 0 0 1-16 0c0-4 3-7 5-9 0 4 1 5 2 6 3-2 3-5 2-10Z" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round" /><path d="M11 15c3 2 4 5 1 8" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" /></svg></span><strong>FireVision</strong></AppLink><p>Аналіз відеопотоків</p></div>
      <nav aria-label={mobile ? 'Мобільна навігація' : 'Головна навігація'}>{routes.map(route => <AppLink key={route.path} href={route.path} className={`nav-item ${path === route.path ? 'active' : ''}`} aria-current={path === route.path ? 'page' : undefined}><Icon name={route.icon} /><span>{route.title}</span></AppLink>)}</nav>
      <div className="sidebar-footer"><span className="workspace-dot" /><div><strong>Робочий простір</strong><p>Локальне середовище</p></div></div>
    </>
  }
  return <div className="app-shell">
    <a className="skip-link" href="#main-content">Перейти до вмісту</a>
    <aside className="sidebar">{navigation(false)}</aside>
    <dialog className="mobile-drawer" ref={drawer} aria-label="Навігація FireVision" onClose={() => { setOpen(false); menu.current?.focus() }} onClick={event => { if (event.target === event.currentTarget) drawer.current?.close() }}>
      <button className="icon-button drawer-close" aria-label="Закрити меню" onClick={() => drawer.current?.close()}><Icon name="close" /></button>{navigation(true)}
    </dialog>
    <div className="workspace">
      <header className="app-header"><div className="header-section"><button className="icon-button menu-toggle" ref={menu} aria-label="Відкрити меню" aria-expanded={open} onClick={() => { drawer.current?.showModal(); setOpen(true) }}><Icon name="menu" /></button><span className="header-workspace">Робочий простір</span><span className="header-divider">/</span><span>{current?.title || 'Сторінку не знайдено'}</span></div><ServerConnection /></header>
      <main id="main-content" tabIndex={-1}><div className="page-container" key={path}>{children}</div></main>
    </div>
  </div>
}
