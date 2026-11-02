import { useState } from 'react'
import { useRemotePage, type ModelVersion, type SourceOption } from './api'
import { AppLink } from './router'
import { Badge, EmptyState, Icon, Notice, PageHeading, Panel, Planned } from './ui'

function SourceSelect({ label = 'Відеоджерело', value, onChange, sources }: { label?: string; value: string; onChange: (value: string) => void; sources: SourceOption[] }) {
  return <label>{label}<select value={value} onChange={event => onChange(event.target.value)}><option value="">Усі джерела</option>{sources.map(source => <option key={source.id} value={source.id}>{source.name}</option>)}</select></label>
}

export function MonitoringPage() {
  const sources = useRemotePage<SourceOption>('/api/video-sources?page=1&page_size=100')
  const [selectedId, setSelectedId] = useState('')
  const selected = sources.data?.items.find(source => source.id === selectedId)
  return <div>
    <PageHeading title="Моніторинг" description="Спільний перегляд джерел і поточних подій у робочому просторі." actions={<Badge>Заплановано</Badge>} />
    <Planned>Моніторинг кількох джерел ще не реалізований. Нижче — структура майбутньої робочої області, без активних потоків.</Planned>
    <Panel title="Керування джерелами">
      {sources.error && <Notice tone="error">{sources.error}</Notice>}
      <div className="toolbar"><SourceSelect label="Джерело для підключення" value={selectedId} onChange={setSelectedId} sources={sources.data?.items || []} /><div className="form-actions"><button disabled><Icon name="play" />Почати моніторинг</button><button className="secondary" disabled>Додати джерело</button></div></div>
      <p className="field-help">{sources.loading ? 'Отримуємо список завантажених джерел…' : sources.data?.total === 0 ? 'Завантажені джерела відсутні. Їх можна додати в розділі «Відеоджерела».' : 'Вибір використовує реальний список джерел. Підключення до моніторингу заплановано.'}</p>
    </Panel>
    <div className="monitor-layout"><div className="monitor-grid">
      <div className="monitor-tile"><div className="monitor-tile-header"><strong>{selected?.name || 'Панель джерела'}</strong><Badge>Не підключено</Badge></div><div className="monitor-tile-body"><EmptyState compact icon="monitoring" title="Немає активного потоку">Тут відображатиметься відео та стан обраного джерела після реалізації моніторингу.</EmptyState></div></div>
      <div className="monitor-tile"><div className="monitor-tile-header"><strong>Додаткове джерело</strong><Badge>Заплановано</Badge></div><div className="monitor-tile-body"><EmptyState compact icon="sources" title="Місце для наступного джерела">Сітка адаптуватиметься до кількості підключених джерел.</EmptyState></div></div>
    </div><Panel title="Поточні події" actions={<Badge>Заплановано</Badge>}><EmptyState compact icon="events" title="Події ще не формуються">Часове підтвердження та журнал подій будуть реалізовані окремо.</EmptyState><AppLink className="subtle-link" href="/events">Переглянути структуру журналу</AppLink></Panel></div>
  </div>
}

export function ExperimentsPage() {
  const [page, setPage] = useState(1)
  const models = useRemotePage<ModelVersion>(`/api/model-versions?page=${page}&page_size=20`)
  const [first, setFirst] = useState('')
  const [second, setSecond] = useState('')
  const [selectedId, setSelectedId] = useState('')
  const selected = models.data?.items.find(model => model.id === selectedId)
  return <div>
    <PageHeading title="Моделі та експерименти" description="Зареєстровані версії детектора та структура майбутнього порівняння експериментів." actions={<button className="secondary" disabled>Реєстрація моделі</button>} />
    <Panel title="Версії моделей" description="Реальні дані реєстру. Доступність включає перевірку файлу та SHA-256." className="table-panel" actions={<button className="secondary" onClick={models.refresh} disabled={models.loading}><Icon name="refresh" />Оновити</button>}>
      {models.loading && <div className="loading-row" role="status">Завантажуємо версії моделей…</div>}
      {models.error && <div className="panel-body"><Notice tone="error">{models.error}</Notice></div>}
      {!models.loading && !models.error && models.data?.total === 0 && <EmptyState icon="experiments" title="Зареєстрованих моделей ще немає">Після завершення навчання потрібно перевірити фінальні ваги та зареєструвати їх локально. Поточні checkpoints не підставляються автоматично.</EmptyState>}
      {models.data && models.data.items.length > 0 && !models.error && <div className="table-wrap"><table className="model-table"><thead><tr><th>Версія</th><th>Архітектура</th><th>Класи</th><th>SHA-256</th><th>Доступність</th><th>Додано</th></tr></thead><tbody>{models.data.items.map(model => <tr key={model.id} className={model.id === selectedId ? 'selected' : ''}><td><button className="source-title" onClick={() => setSelectedId(model.id)}>{model.name}</button></td><td>{model.architecture}</td><td>{Object.entries(model.class_mapping).map(([id, name]) => `${id}: ${name}`).join(', ')}</td><td><code title={model.weights_sha256}>{model.weights_sha256.slice(0, 12)}…</code></td><td><Badge tone={model.available ? 'success' : 'warning'}>{model.available ? 'Доступна' : 'Недоступна'}</Badge></td><td className="no-wrap">{new Date(model.created_at).toLocaleDateString('uk-UA')}</td></tr>)}</tbody></table></div>}
      {models.data && models.data.total > 20 && <nav className="pagination" aria-label="Сторінки моделей"><button className="secondary" disabled={page === 1} onClick={() => setPage(value => value - 1)}>Назад</button><span>Сторінка {page}</span><button className="secondary" disabled={page * 20 >= models.data.total} onClick={() => setPage(value => value + 1)}>Далі</button></nav>}
    </Panel>
    {selected && <div className="section-gap"><Panel title={selected.name}><dl><dt>Архітектура</dt><dd>{selected.architecture}</dd><dt>Файл ваг</dt><dd><code>{selected.weights_path}</code></dd><dt>SHA-256</dt><dd><code>{selected.weights_sha256}</code></dd><dt>Класи</dt><dd>{Object.entries(selected.class_mapping).map(([id, name]) => `${id} = ${name}`).join('; ')}</dd><dt>Стан файлу</dt><dd>{selected.available ? 'Доступність і контрольну суму підтверджено API.' : selected.unavailable_reason}</dd></dl></Panel></div>}
    <div className="section-gap"><Planned>Порівняння експериментів і графіки заплановані. Показники не підставляються з поточного навчання або тестових даних.</Planned></div>
    <Panel title="Порівняння експериментів" actions={<Badge>Заплановано</Badge>}>
      <div className="toolbar"><label>Перша версія<select value={first} onChange={event => setFirst(event.target.value)} disabled={!models.data?.total}><option value="">Оберіть модель</option>{models.data?.items.map(model => <option value={model.id} key={model.id}>{model.name}</option>)}</select></label><label>Друга версія<select value={second} onChange={event => setSecond(event.target.value)} disabled={!models.data?.total}><option value="">Оберіть модель</option>{models.data?.items.map(model => <option value={model.id} key={model.id}>{model.name}</option>)}</select></label><button disabled>Порівняти</button></div>
      <div className="table-wrap section-gap"><table><thead><tr><th>Модель</th><th>Precision</th><th>Recall</th><th>mAP@0.5</th><th>mAP@0.5:0.95</th><th>Час оброблення</th></tr></thead><tbody><tr><td colSpan={6}><EmptyState compact icon="experiments" title="Результати порівняння відсутні">Тут будуть фактичні метрики погоджених експериментів з описом умов оцінювання.</EmptyState></td></tr></tbody></table></div>
    </Panel>
    <div className="two-columns section-gap"><Panel title="Якість детекції" actions={<Badge>Заплановано</Badge>}><div className="chart-placeholder"><EmptyState compact icon="experiments" title="Даних для графіка немає">Жодних штучних кривих або відсотків точності.</EmptyState></div><div className="metric-headings"><span>mAP@0.5: —</span><span>mAP@0.5:0.95: —</span></div></Panel><Panel title="Швидкодія" actions={<Badge>Заплановано</Badge>}><div className="chart-placeholder"><EmptyState compact icon="clock" title="Вимірювання ще не додані">Час і використання ресурсів відображатимуться за реальними експериментами.</EmptyState></div><div className="metric-headings"><span>Час оброблення: —</span><span>Пристрій: —</span></div></Panel></div>
  </div>
}

