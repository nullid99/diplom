import { StrictMode, useEffect } from 'react'
import { createRoot } from 'react-dom/client'
import './style.css'
import { AppLayout } from './AppLayout'
import { AppLink, navigate, usePathname } from './router'
import { VideoSources } from './VideoSources'
import { VideoAnalysis } from './VideoAnalysis'
import { ExperimentsPage, MonitoringPage } from './FuturePages'
import { EventsPage } from './EventsPage'
import { SettingsPage } from './SettingsPage'
import { EmptyState, PageHeading } from './ui'
function App() {
  const path = usePathname()
  useEffect(() => { if (path === '/') navigate('/sources', true) }, [path])
  const content = path === '/sources' || path === '/' ? <VideoSources /> : path === '/analysis' ? <VideoAnalysis /> : path === '/monitoring' ? <MonitoringPage /> : path === '/events' ? <EventsPage /> : path === '/experiments' ? <ExperimentsPage /> : path === '/settings' ? <SettingsPage /> : <><PageHeading title="Сторінку не знайдено" description="Перевірте адресу або оберіть розділ у меню." /><EmptyState title="Такої сторінки немає" action={<AppLink className="button" href="/sources">До відеоджерел</AppLink>}>Ви можете повернутися до робочого простору.</EmptyState></>
  return <AppLayout path={path === '/' ? '/sources' : path}>{content}</AppLayout>
}
createRoot(document.getElementById('root')!).render(<StrictMode><App /></StrictMode>)
