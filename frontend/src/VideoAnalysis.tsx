import { AppLink } from './router'
import { ZoneEditor } from './ZoneEditor'
import { TemporalFields, temporalDefaults, type Temporal } from './TemporalFields'
import { analysisDefaults } from './api'
import { Badge, EmptyState, Icon, Notice, PageHeading, Panel } from './ui'
import { useEffect, useRef, useState, type FormEvent } from 'react'

type Source = { id: string; name: string }
type Model = { id: string; name: string; architecture: string; class_mapping: Record<string, string>; weights_path: string; weights_sha256: string; available: boolean; unavailable_reason: string | null }
type Run = { id: string; video_source_id: string; model_version_id: string; video_source_name: string; model_version_name: string; status: string; progress: number; cancel_requested_at: string | null; error_message: string | null; created_at: string; settings_snapshot: Record<string, unknown>; summary_metrics: Record<string, unknown> | null; result_paths: Record<string, string> | null }
type Page<T> = { items: T[]; total: number; page: number; page_size: number }
const api = import.meta.env.VITE_API_BASE_URL?.trim().replace(/\/$/, '')
const labels: Record<string, string> = { pending: 'Очікування', running: 'Оброблення', completed: 'Завершено', failed: 'Помилка', stopped: 'Скасовано' }
const stages: Record<string, string> = { checking: 'Перевірка файлів і часової шкали', processing: 'Оброблення кадрів', verifying: 'Перевірка результатів', completed: 'Результати збережено' }
const active = (run: Run) => ['pending', 'running'].includes(run.status)
async function read(response: Response) {
  const data = await response.json()
  if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'Перевірте параметри запиту.')
  return data
}

export function VideoAnalysis() {
  const [sources, setSources] = useState<Page<Source> | null>(null)
  const [models, setModels] = useState<Page<Model> | null>(null)
  const [runs, setRuns] = useState<Page<Run> | null>(null)
  const [sourcePage, setSourcePage] = useState(1)
  const [modelPage, setModelPage] = useState(1)
  const [page, setPage] = useState(1)
  const [sourceId, setSourceId] = useState('')
  const [modelId, setModelId] = useState('')
  const [smoke, setSmoke] = useState(analysisDefaults.smoke)
  const [fire, setFire] = useState(analysisDefaults.fire)
  const [fps, setFps] = useState(analysisDefaults.fps)
  const [temporal,setTemporal]=useState<Temporal>(temporalDefaults)
  const [defaultsReady,setDefaultsReady]=useState(false)
  const [zonesDirty,setZonesDirty]=useState(false)
  const [imgsz, setImgsz] = useState(analysisDefaults.imgsz)
  const [device, setDevice] = useState('cpu')
  const [gpuEnabled, setGpuEnabled] = useState(false)
  const [selectedId, setSelectedId] = useState(() => localStorage.getItem('firevision-analysis-id') || '')
  const [selected, setSelected] = useState<Run | null>(null)
  const [error, setError] = useState('')
  const [playerError, setPlayerError] = useState('')
  const [busy, setBusy] = useState(false)
  const [loading, setLoading] = useState(true)
  const [notice, setNotice] = useState('')
  const [connection, setConnection] = useState('З’єднання…')
  const [refresh, setRefresh] = useState(0)
  const socket = useRef<WebSocket | null>(null)
  const selectedModel = models?.items.find(model => model.id === modelId)
  useEffect(()=>{
    const controller=new AbortController()
    fetch(`${api}/api/analysis-defaults`,{signal:controller.signal}).then(async response=>{if(!response.ok)throw new Error();return response.json()}).then(body=>{setTemporal(body.temporal);setFps(body.analysis_fps);setDefaultsReady(true)}).catch(()=>{if(!controller.signal.aborted)setError('Не вдалося отримати типові часові налаштування.')})
    return()=>controller.abort()
  },[])

  useEffect(() => {
    if (!api) { setError('Адресу API не налаштовано.'); setLoading(false); return }
    const controller = new AbortController()
    setLoading(true)
    setError('')
    Promise.all([
      fetch(`${api}/api/video-sources?page=${sourcePage}&page_size=20`, { signal: controller.signal }).then(read),
      fetch(`${api}/api/model-versions?page=${modelPage}&page_size=20`, { signal: controller.signal }).then(read),
    ]).then(([sourceData, modelData]) => {
      setSources(sourceData); setModels(modelData); setGpuEnabled(modelData.gpu_enabled)
    }).catch(() => { if (!controller.signal.aborted) setError('Не вдалося отримати відеоджерела або моделі. Перевірте API та БД.') })
      .finally(() => { if (!controller.signal.aborted) setLoading(false) })
    return () => controller.abort()
  }, [sourcePage, modelPage, refresh])

  useEffect(() => {
    if (!api) return
    let disposed = false
    let timer: ReturnType<typeof setTimeout>
    let delay = 1000
    const controller = new AbortController()
    const base = api
    async function restore() {
      try {
        const list = await fetch(`${base}/api/analysis-runs?page=${page}`, { signal: controller.signal, cache: 'no-store' }).then(read)
        if (!disposed) setRuns(list)
        if (selectedId) {
          const detail = await fetch(`${base}/api/analysis-runs/${selectedId}`, { signal: controller.signal, cache: 'no-store' }).then(read)
          if (!disposed) setSelected(detail)
        }
      } catch { if (!disposed) setError('Не вдалося відновити стан запусків із сервера.') }
    }
    function connect() {
      if (disposed) return
      const url = new URL(`${base}/api/analysis-runs/ws`)
      url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:'
      url.searchParams.set('page', String(page))
      if (selectedId) url.searchParams.set('selected_id', selectedId)
      const ws = new WebSocket(url)
      socket.current = ws
      ws.onopen = () => { if (!disposed) { delay = 1000; setConnection('Оновлення наживо підключено'); void restore() } }
      ws.onmessage = event => {
        if (disposed) return
        try {
          const data = JSON.parse(event.data)
          if (data.type === 'snapshot') {
            setRuns(data.runs)
            if (selectedId) setSelected(data.selected)
            setConnection('Оновлення наживо підключено')
          } else setConnection('Стан БД тимчасово недоступний')
        } catch { setConnection('Некоректне повідомлення сервера') }
      }
      ws.onclose = () => {
        if (!disposed) { setConnection('З’єднання втрачено. Відновлюємо…'); timer = setTimeout(connect, delay); delay = Math.min(delay * 2, 10000) }
      }
      ws.onerror = () => ws.close()
    }
    void restore()
    timer = setTimeout(connect, 0)
    return () => {
      disposed = true; clearTimeout(timer); controller.abort()
      const current = socket.current
      if (current?.readyState === WebSocket.CONNECTING) {
        current.onopen = () => current.close()
        current.onmessage = null; current.onclose = null; current.onerror = null
      } else current?.close()
      socket.current = null
    }
  }, [page, selectedId, refresh])

  function choose(runId: string) {
    localStorage.setItem('firevision-analysis-id', runId)
    setSelected(null); setSelectedId(runId); setPlayerError('')
  }

  async function start(event: FormEvent) {
    event.preventDefault()
    if (!api || !sourceId || !selectedModel?.available) return
    setBusy(true); setError(''); setNotice('')
    try {
      const run: Run = await fetch(`${api}/api/analysis-runs`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ video_source_id: sourceId, model_version_id: modelId, settings: { smoke_threshold: smoke, fire_threshold: fire, imgsz, analysis_fps: fps, device, temporal } }) }).then(read)
      choose(run.id); setPage(1); setRefresh(value => value + 1)
      setNotice('Запуск додано до черги. Оброблення виконує окремий worker.')
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Не вдалося створити запуск.') }
    finally { setBusy(false) }
  }

  async function cancel() {
    if (!api || !selected) return
    setBusy(true); setError('')
    try {
      const run: Run = await fetch(`${api}/api/analysis-runs/${selected.id}/cancel`, { method: 'POST' }).then(read)
      setSelected(run)
      setNotice(run.status === 'stopped' ? 'Запуск скасовано.' : run.status === 'completed' ? 'Запуск уже завершився. Результати збережено.' : run.status === 'failed' ? 'Запуск уже завершився помилкою.' : 'Запит скасування надіслано. Очікуємо фактичної зупинки worker.')
      if (socket.current?.readyState === WebSocket.OPEN) socket.current.send('refresh')
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Не вдалося скасувати запуск.') }
    finally { setBusy(false) }
  }

  const fileUrl = (kind: string, download = false) => `${api}/api/analysis-runs/${selected?.id}/files/${kind}${download ? '?download=true' : ''}`
  const statusTone = (status: string): 'neutral' | 'blue' | 'success' | 'danger' => status === 'completed' ? 'success' : status === 'failed' ? 'danger' : status === 'running' ? 'blue' : 'neutral'
  return <div>
    <PageHeading title="Аналіз відео" description="Оберіть запис і версію моделі. Стан оброблення та результати зберігаються на сервері." actions={<button className="secondary" onClick={() => setRefresh(value => value + 1)}><Icon name="refresh" />Оновити дані</button>} />
    {error && <Notice tone="error">{error}</Notice>}
    {notice && <Notice>{notice}</Notice>}
    <div className="analysis-layout">
      <Panel title="Параметри запуску" className="analysis-config">
        <form onSubmit={start} className="form-stack">
          {loading && <p className="muted" role="status">Завантажуємо джерела та моделі…</p>}
          {!loading && models?.total === 0 && <Notice><span data-testid="no-model">Готової моделі ще немає. Після завершення навчання потрібно перевірити й зареєструвати фінальні ваги.</span></Notice>}
          {!loading && sources?.total === 0 && <p className="field-help">Спочатку додайте запис у розділі <AppLink href="/sources">«Відеоджерела»</AppLink>.</p>}
          <label>Відеоджерело<select aria-label="Відеоджерело" required value={sourceId} onChange={event => setSourceId(event.target.value)}><option value="">Оберіть відео</option>{sources?.items.map(source => <option key={source.id} value={source.id}>{source.name}</option>)}</select></label>
          {sources && sources.total > 20 && <div className="pagination"><button className="secondary" type="button" disabled={sourcePage === 1} onClick={() => { setSourcePage(value => value - 1); setSourceId('') }}>Попередні відео</button><span>{sourcePage}</span><button className="secondary" type="button" disabled={sourcePage * 20 >= sources.total} onClick={() => { setSourcePage(value => value + 1); setSourceId('') }}>Наступні відео</button></div>}
          <label>Версія моделі<select aria-label="Версія моделі" required value={modelId} onChange={event => setModelId(event.target.value)}><option value="">Оберіть модель</option>{models?.items.map(model => <option key={model.id} value={model.id} disabled={!model.available}>{model.name}{model.available ? '' : ' — недоступна'}</option>)}</select></label>
          {models && models.total > 20 && <div className="pagination"><button className="secondary" type="button" disabled={modelPage === 1} onClick={() => { setModelPage(value => value - 1); setModelId('') }}>Попередні моделі</button><button className="secondary" type="button" disabled={modelPage * 20 >= models.total} onClick={() => { setModelPage(value => value + 1); setModelId('') }}>Наступні моделі</button></div>}
          {selectedModel && <details><summary>Відомості моделі</summary><p>{selectedModel.architecture}; 0 = smoke, 1 = fire</p><p className="muted">SHA-256<br /><code>{selectedModel.weights_sha256}</code></p><p className="muted">Ваги<br /><code>{selectedModel.weights_path}</code></p>{selectedModel.unavailable_reason && <Notice tone="error">{selectedModel.unavailable_reason}</Notice>}</details>}
          <hr className="form-separator" />
          <div className="analysis-fields">
            <label>Поріг smoke<input type="number" min="0.01" max="1" step="0.01" required value={Number.isFinite(smoke) ? smoke : ''} onChange={event => setSmoke(event.target.valueAsNumber)} /></label>
            <label>Поріг fire<input type="number" min="0.01" max="1" step="0.01" required value={Number.isFinite(fire) ? fire : ''} onChange={event => setFire(event.target.valueAsNumber)} /></label>
            <label>Частота аналізу<input aria-label="Частота аналізу, кадрів/с" type="number" min="0.1" max="60" step="0.1" required value={Number.isFinite(fps) ? fps : ''} onChange={event => setFps(event.target.valueAsNumber)} /><span className="field-help">Кадрів за секунду</span></label>
            <label>Розмір зображення<input aria-label="Розмір зображення (imgsz)" type="number" min="320" max="1280" step="32" required value={Number.isFinite(imgsz) ? imgsz : ''} onChange={event => setImgsz(event.target.valueAsNumber)} /><span className="field-help">Кратний 32 (imgsz)</span></label>
          </div>
          <label>Пристрій<select value={device} onChange={event => setDevice(event.target.value)}><option value="cpu">CPU</option><option value="cuda:0" disabled={!gpuEnabled}>GPU (CUDA:0)</option></select></label>
          {!gpuEnabled && <p className="field-help">GPU для аналізу вимкнено в налаштуваннях проєкту.</p>}
          <details><summary>Часове підтвердження подій</summary><TemporalFields value={temporal} onChange={setTemporal} /><p className="field-help">Інженерні налаштування. Зберігаються незмінним знімком цього запуску.</p></details>
          <button className="full-width" type="submit" disabled={busy || loading || !defaultsReady || zonesDirty || !sourceId || !selectedModel?.available}><Icon name="play" />{busy ? 'Надсилаємо…' : 'Запустити аналіз'}</button>
          <p className="field-help">Детектор перевіряє вибрані кадри. Відео результату зберігає всі кадри й вихідний час, без звуку.</p>
        </form>
      </Panel>
      <div className="stack">
        {sourceId&&<ZoneEditor sourceId={sourceId} onDirty={setZonesDirty} />}
        <Panel title="Результат аналізу" className="analysis-view" actions={selected ? <Badge tone={statusTone(selected.status)}>{labels[selected.status] || selected.status}</Badge> : <Badge>Не вибрано</Badge>}>
          {selected?.status === 'completed' && selected.result_paths ? <>
            <video className="video-player" key={selected.id} controls preload="metadata" aria-label="Відео результату аналізу" src={fileUrl('video')} onError={() => setPlayerError('Браузер не зміг відкрити результат. Завантажте відеофайл для локального перегляду.')} onLoadedMetadata={() => setPlayerError('')} />
            {playerError && <div className="section-gap"><Notice tone="error">{playerError}</Notice></div>}
            <div className="result-links"><a className="button secondary" href={fileUrl('video', true)}><Icon name="download" />Відео</a><a className="button secondary" href={fileUrl('detections', true)}>Виявлення JSONL</a><a className="button secondary" href={fileUrl('summary', true)}>Підсумок JSON</a></div>
          </> : selected && active(selected) ? <EmptyState icon="analysis" title={selected.status === 'pending' ? 'Запис очікує оброблення' : 'Відео обробляється'}>Готовий запис з’явиться після збереження та перевірки результатів. Часткові файли не відображаються.</EmptyState> : selected?.status === 'failed' || selected?.status === 'stopped' ? <EmptyState icon="video" title="Готового відео немає">{selected.status === 'stopped' ? 'Оброблення скасовано. Часткові результати недоступні.' : 'Запуск завершився помилкою. Причину наведено нижче.'}</EmptyState> : <EmptyState icon="video" title="Оберіть запуск для перегляду">Тут з’явиться відео з рамками й файлами результатів. Створіть новий запуск або оберіть завершений в історії.</EmptyState>}
        </Panel>
        <Panel title="Стан оброблення" actions={<p className={`inline-status ${connection === 'Оновлення наживо підключено' ? 'connected' : ''}`} data-testid="analysis-connection"><span className="status-dot" />{connection}</p>}>
          {selected ? <article className="run-status" aria-label="Деталі аналізу">
            <div className="progress-heading"><h3>{labels[selected.status] || selected.status}</h3><span>{(selected.progress * 100).toFixed(1)}%</span></div>
            <progress max="1" value={selected.progress} aria-label="Прогрес аналізу" />
            <p role="status">{selected.status === 'stopped' ? 'Оброблення припинено. Часткові результати недоступні.' : selected.status === 'failed' ? 'Оброблення завершилося помилкою.' : selected.cancel_requested_at && active(selected) ? 'Скасування запитано. Worker ще не підтвердив зупинку.' : stages[String(selected.summary_metrics?.stage)] || 'Стан збережено в БД.'}</p>
            {selected.summary_metrics?.frames_read !== undefined && <div className="run-summary"><span>Прочитано кадрів: <strong>{String(selected.summary_metrics.frames_read)}</strong></span><span>Проаналізовано: <strong>{String(selected.summary_metrics.frames_analyzed)}</strong></span></div>}
            {selected.error_message && <Notice tone="error">{selected.error_message}</Notice>}
            {active(selected) && <div className="form-actions"><button className="danger" disabled={busy || !!selected.cancel_requested_at} onClick={() => void cancel()}><Icon name="close" />Скасувати аналіз</button></div>}
            <p>{selected.video_source_name} · {selected.model_version_name}</p>
            <details><summary>Параметри цього запуску</summary><dl><dt>Поріг smoke</dt><dd>{String(selected.settings_snapshot.smoke_threshold)}</dd><dt>Поріг fire</dt><dd>{String(selected.settings_snapshot.fire_threshold)}</dd><dt>Частота</dt><dd>{String(selected.settings_snapshot.analysis_fps)} кадрів/с</dd><dt>Розмір</dt><dd>{String(selected.settings_snapshot.imgsz)}</dd><dt>Пристрій</dt><dd>{String(selected.settings_snapshot.device)}</dd><dt>SHA-256 ваг</dt><dd><code>{String(selected.settings_snapshot.model_sha256)}</code></dd><dt>Ідентифікатор</dt><dd><code>{selected.id}</code></dd></dl></details>
            <details><summary>Зони та часові правила цього запуску</summary><pre>{JSON.stringify({zones:selected.settings_snapshot.zones??'Немає у попередній версії запуску',temporal:selected.settings_snapshot.temporal??'Часові події не виконувалися'},null,2)}</pre></details>
            {selected.status === 'completed' && <p>Час оброблення: {Number(selected.summary_metrics?.wall_seconds || 0).toFixed(2)} с. Покадрові рамки не є кількістю подій. <AppLink href="/events">Відкрити журнал подій</AppLink></p>}
          </article> : <p className="muted" style={{ marginBottom: 0 }}>Запуск не вибрано. Після створення завдання тут відображатиметься реальний прогрес із сервера.</p>}
        </Panel>
        <Panel title="Історія запусків" className="table-panel" description="Закриття сторінки не зупиняє оброблення на сервері.">
          {!runs && !error && <div className="loading-row" role="status">Завантажуємо історію…</div>}
          {runs?.total === 0 && <EmptyState compact icon="clock" title="Запусків аналізу ще немає">Оберіть джерело й доступну модель, щоб створити перший запуск.</EmptyState>}
          {runs && runs.items.length > 0 && <div className="table-wrap"><table className="history-table"><thead><tr><th>Створено</th><th>Джерело / модель</th><th>Стан</th><th>Прогрес</th></tr></thead><tbody className="source-list">{runs.items.map(run => <tr key={run.id} className={selectedId === run.id ? 'selected' : ''}><td className="no-wrap"><button className="source-title" aria-pressed={selectedId === run.id} onClick={() => choose(run.id)}>{new Date(run.created_at).toLocaleString('uk-UA')}</button></td><td>{run.video_source_name}<p className="file-caption">{run.model_version_name}</p></td><td><Badge tone={statusTone(run.status)}>{labels[run.status] || run.status}</Badge>{run.cancel_requested_at && active(run) && <p className="file-caption">Очікуємо зупинки</p>}</td><td>{(run.progress * 100).toFixed(1)}%</td></tr>)}</tbody></table></div>}
          {runs && runs.total > runs.page_size && <nav aria-label="Сторінки запусків" className="pagination"><button className="secondary" disabled={page === 1} onClick={() => setPage(value => value - 1)}>Назад</button><span>Сторінка {page} з {Math.ceil(runs.total / runs.page_size)}</span><button className="secondary" disabled={page * runs.page_size >= runs.total} onClick={() => setPage(value => value + 1)}>Далі</button></nav>}
        </Panel>
      </div>
    </div>
  </div>
}
