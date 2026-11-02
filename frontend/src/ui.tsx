import type { ReactNode, SVGProps } from 'react'
export type IconName = 'sources' | 'analysis' | 'monitoring' | 'events' | 'experiments' | 'settings' | 'upload' | 'refresh' | 'video' | 'close' | 'menu' | 'arrow' | 'play' | 'download' | 'clock' | 'filter' | 'image' | 'check' | 'file' | 'info'
const paths: Record<IconName, ReactNode> = {
  sources: <><rect x="3" y="4" width="18" height="16" rx="3" /><path d="m10 8 5 4-5 4Z" /></>,
  analysis: <><path d="M4 5h11M4 12h7M4 19h11" /><circle cx="16" cy="11" r="4" /><path d="m19 14 3 3" /></>,
  monitoring: <><rect x="3" y="4" width="18" height="13" rx="2" /><path d="M8 21h8m-4-4v4M7 11h2l2-3 3 6 2-3h2" /></>,
  events: <><rect x="5" y="4" width="14" height="17" rx="2" /><path d="M9 3h6v3H9zM9 11h6m-6 4h6" /></>,
  experiments: <><path d="m12 3 9 5-9 5-9-5 9-5Zm-9 9 9 5 9-5M3 16l9 5 9-5" /></>,
  settings: <><path d="M4 6h16M4 12h16M4 18h16" /><circle cx="8" cy="6" r="2" /><circle cx="16" cy="12" r="2" /><circle cx="10" cy="18" r="2" /></>,
  upload: <path d="M12 16V3m-5 5 5-5 5 5M4 15v4a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-4" />,
  refresh: <><path d="M20 7v5h-5M4 17v-5h5" /><path d="M6 7a7 7 0 0 1 12-2l2 3M4 16l2 3a7 7 0 0 0 12-2" /></>,
  video: <><rect x="3" y="6" width="12" height="12" rx="2" /><path d="m15 10 6-3v10l-6-3" /></>,
  close: <path d="m6 6 12 12M6 18 18 6" />,
  menu: <path d="M4 6h16M4 12h16M4 18h16" />,
  arrow: <path d="M5 12h14m-5-5 5 5-5 5" />,
  play: <path d="m9 5 11 7-11 7Z" />,
  download: <path d="M12 3v12m-5-5 5 5 5-5M4 16v4h16v-4" />,
  clock: <><circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 2" /></>,
  filter: <path d="M3 5h18l-7 8v6l-4 2v-8Z" />,
  image: <><rect x="3" y="3" width="18" height="18" rx="2" /><circle cx="8" cy="8" r="1" /><path d="m3 17 6-6 5 5 3-3 4 4" /></>,
  check: <path d="m5 12 4 4L19 6" />,
  file: <><path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9l-6-6Z" /><path d="M14 3v6h6" /></>,
  info: <><circle cx="12" cy="12" r="9" /><path d="M12 11v6m0-10v1" /></>,
}
export function Icon({ name, ...props }: SVGProps<SVGSVGElement> & { name: IconName }) {
  return <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" {...props}>{paths[name]}</svg>
}
export function PageHeading({ title, description, actions }: { title: string; description: string; actions?: ReactNode }) {
  return <div className="page-heading"><div><h1>{title}</h1><p>{description}</p></div>{actions && <div className="heading-actions">{actions}</div>}</div>
}
export function Panel({ title, description, actions, children, className = '' }: { title?: string; description?: string; actions?: ReactNode; children: ReactNode; className?: string }) {
  return <section className={`panel ${className}`}>{title && <div className="panel-heading"><div><h2>{title}</h2>{description && <p>{description}</p>}</div>{actions}</div>}<div className="panel-body">{children}</div></section>
}
export function EmptyState({ icon = 'video', title, children, action, compact = false }: { icon?: IconName; title: string; children: ReactNode; action?: ReactNode; compact?: boolean }) {
  return <div className={`empty-state ${compact ? 'compact' : ''}`}><span className="empty-icon"><Icon name={icon} /></span><h3>{title}</h3><p>{children}</p>{action}</div>
}
export function Badge({ children, tone = 'neutral' }: { children: ReactNode; tone?: 'neutral' | 'blue' | 'success' | 'warning' | 'danger' }) {
  return <span className={`badge ${tone}`}>{children}</span>
}
export function Planned({ children }: { children?: ReactNode }) {
  return <div className="planned-note"><Icon name="info" /><p>{children || 'Це макет майбутніх можливостей. Дії стануть доступними після реалізації модуля.'}</p><Badge>Заплановано</Badge></div>
}
export function Notice({ children, tone = 'info' }: { children: ReactNode; tone?: 'info' | 'error' | 'success' }) {
  return <div className={`notice ${tone}`} role={tone === 'error' ? 'alert' : 'status'}><Icon name={tone === 'success' ? 'check' : 'info'} /><div>{children}</div></div>
}
