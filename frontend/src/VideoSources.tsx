import { EmptyState, Icon, Notice, PageHeading, Panel } from './ui'
import { useEffect, useRef, useState, type FormEvent } from 'react'

interface VideoSource {
  id: string
  name: string
  original_filename: string
  file_size_bytes: number | null
  sha256: string | null
  duration_seconds: string | null
  width: number | null
  height: number | null
  fps: string | null
  avg_frame_rate: string | null
  r_frame_rate: string | null
  container_format: string | null
  video_codec: string | null
  created_at: string
}

interface SourcePage {
  items: VideoSource[]
  total: number
  upload_limit_bytes: number
}

const api = import.meta.env.VITE_API_BASE_URL?.trim().replace(/\/$/, '')
const size = (bytes: number | null) => bytes === null ? 'Невідомо' : `${(bytes / 1024 / 1024).toLocaleString('uk-UA', { maximumFractionDigits: 2 })} МіБ`
const duration = (seconds: string | null) => seconds === null ? 'Невідомо' : `${Number(seconds).toLocaleString('uk-UA', { maximumFractionDigits: 2 })} с`
const resolution = (source: VideoSource) => source.width && source.height ? `${source.width} × ${source.height}` : 'Невідомо'

async function readResponse(response: Response) {
  let data
  try { data = await response.json() } catch { throw new Error('API повернуло некоректну відповідь.') }
  if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'Не вдалося виконати запит.')
  return data
}

export function VideoSources() {
  const [name, setName] = useState('')
  const [file, setFile] = useState<File | null>(null)
  const [phase, setPhase] = useState<'idle' | 'uploading' | 'checking'>('idle')
  const [percent, setPercent] = useState<number | null>(null)
  const [notice, setNotice] = useState('')
  const [uploadError, setUploadError] = useState('')
  const [listError, setListError] = useState('')
  const [listLoading, setListLoading] = useState(true)
  const [page, setPage] = useState(1)
  const [refresh, setRefresh] = useState(0)
  const [result, setResult] = useState<SourcePage | null>(null)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [selected, setSelected] = useState<VideoSource | null>(null)
  const [detailError, setDetailError] = useState('')
  const [playerError, setPlayerError] = useState('')
  const fileInput = useRef<HTMLInputElement>(null)
  const xhrRef = useRef<XMLHttpRequest | null>(null)

  useEffect(() => () => xhrRef.current?.abort(), [])

  useEffect(() => {
    const controller = new AbortController()
    setListLoading(true)
    setListError('')
    if (!api) {
      setListError('Адресу API не налаштовано.')
      setListLoading(false)
      return
    }
    fetch(`${api}/api/video-sources?page=${page}&page_size=10`, { signal: controller.signal })
      .then(readResponse).then((data: SourcePage) => setResult(data))
      .catch((error: Error) => { if (!controller.signal.aborted) setListError(error instanceof TypeError ? 'Не вдалося підключитися до API.' : error.message || 'Не вдалося отримати список.') })
      .finally(() => { if (!controller.signal.aborted) setListLoading(false) })
    return () => controller.abort()
  }, [page, refresh])

  useEffect(() => {
    setSelected(null)
    setDetailError('')
    setPlayerError('')
    if (!selectedId || !api) return
    const controller = new AbortController()
    fetch(`${api}/api/video-sources/${selectedId}`, { signal: controller.signal })
      .then(readResponse).then((data: VideoSource) => setSelected(data))
      .catch((error: Error) => { if (!controller.signal.aborted) setDetailError(error instanceof TypeError ? 'Не вдалося підключитися до API.' : error.message) })
    return () => controller.abort()
  }, [selectedId])

  function upload(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setNotice('')
    setUploadError('')
    if (!file || !name.trim() || !api) {
      setUploadError('Укажіть назву, виберіть файл і перевірте підключення до API.')
      return
    }
    if (result && file.size > result.upload_limit_bytes) {
      setUploadError(`Файл перевищує ліміт ${size(result.upload_limit_bytes)}.`)
      return
    }
    const data = new FormData()
    data.append('name', name.trim())
    data.append('file', file)
    const xhr = new XMLHttpRequest()
    xhrRef.current = xhr
    setPhase('uploading')
    setPercent(null)
    xhr.open('POST', `${api}/api/video-sources`)
    xhr.timeout = 30 * 60 * 1000
    xhr.upload.onprogress = (progress) => {
      if (progress.lengthComputable) setPercent(Math.round(progress.loaded / progress.total * 100))
    }
    xhr.upload.onload = () => setPhase('checking')
    xhr.onload = () => {
      try {
        let response
        try { response = JSON.parse(xhr.responseText) } catch { throw new Error('API повернуло некоректну відповідь.') }
        if (xhr.status !== 201) throw new Error(typeof response.detail === 'string' ? response.detail : 'Не вдалося завантажити відео.')
        setNotice('Відеоджерело збережено.')
        setSelectedId(response.id)
        setPage(1)
        setRefresh((value) => value + 1)
        setName('')
        setFile(null)
        if (fileInput.current) fileInput.current.value = ''
      } catch (error) {
        setUploadError(error instanceof Error ? error.message : 'Помилка завантаження.')
      } finally { setPhase('idle') }
    }
    const connectionError = () => {
      setUploadError('З’єднання перервано або час завантаження вичерпано. Оновіть список, щоб перевірити результат.')
      setPhase('idle')
    }
    xhr.onerror = connectionError
    xhr.ontimeout = connectionError
    xhr.send(data)
  }

  return <div>
    <PageHeading title="Відеоджерела" description="Завантажуйте записи, перевіряйте їхні параметри та обирайте відео для аналізу." />
    <Panel title="Завантажити відео" description="Оригінальний файл і його метадані зберігаються після перевірки." className="upload-panel">
      <form onSubmit={upload}>
        <div className="upload-grid">
          <label>Назва джерела<input name="name" placeholder="Наприклад, запис із камери" value={name} onChange={event => setName(event.target.value)} maxLength={255} required disabled={phase !== 'idle'} /></label>
          <div><label htmlFor="video-file">Відеофайл</label><div className="file-picker">
            <input id="video-file" className="visually-hidden" ref={fileInput} name="file" type="file" accept="video/*,.mkv,.avi,.mov" onChange={event => setFile(event.target.files?.[0] ?? null)} required disabled={phase !== 'idle'} />
            <button className="secondary" type="button" onClick={() => fileInput.current?.click()} disabled={phase !== 'idle'}><Icon name="file" />Вибрати файл</button><span title={file?.name}>{file?.name ?? 'Файл не вибрано'}</span>
          </div></div>
          <button className="upload-submit" type="submit" disabled={phase !== 'idle' || !name.trim() || !file}><Icon name="upload" />{phase === 'idle' ? 'Завантажити відео' : phase === 'uploading' ? 'Завантаження…' : 'Перевірка…'}</button>
        </div>
        <p className="field-help">{result ? `До ${size(result.upload_limit_bytes)} на файл. ` : ''}Розширення файлу не замінює перевірку відеопотоку.</p>
        <div className="upload-feedback" aria-live="polite">
          {phase === 'uploading' && <Notice>Завантаження{percent !== null ? `: ${percent}%` : '…'}{percent !== null && <progress max="100" value={percent} aria-label="Прогрес завантаження" />}</Notice>}
          {phase === 'checking' && <Notice>Перевірка відео та збереження… Дочекайтеся відповіді сервера.</Notice>}
          {notice && <Notice tone="success">{notice}</Notice>}
          {uploadError && <Notice tone="error">{uploadError}</Notice>}
        </div>
      </form>
    </Panel>
    <div className={`sources-content ${selectedId ? 'has-selection' : ''}`}>
      <Panel title="Збережені джерела" description={result && !listError ? `${result.total} ${result.total === 1 ? 'джерело' : 'джерел'} у сховищі` : 'Записи, доступні для перегляду й аналізу'} className="table-panel" actions={<button className="secondary" type="button" onClick={() => setRefresh(value => value + 1)} disabled={listLoading}><Icon name="refresh" />Оновити</button>}>
        {listLoading && <div className="loading-row" role="status">Завантажуємо список…</div>}
        {listError && <div className="panel-body"><Notice tone="error">{listError}</Notice></div>}
        {!listLoading && !listError && result?.total === 0 && <EmptyState icon="sources" title="Відеоджерел ще немає">Додайте перший відеозапис через форму вище. Після перевірки він з’явиться тут.</EmptyState>}
        {result && !listError && result.items.length > 0 && <>
          <div className="table-wrap"><table className="sources-table"><thead><tr><th>Назва / файл</th><th>Тривалість</th><th>Роздільність</th><th>Розмір</th><th>Додано</th><th><span className="visually-hidden">Дії</span></th></tr></thead>
            <tbody className="source-list">{result.items.map(source => <tr key={source.id} className={selectedId === source.id ? 'selected' : ''}>
              <td><button className="source-title" type="button" onClick={() => setSelectedId(source.id)} aria-pressed={selectedId === source.id}>{source.name}</button><p className="file-caption" title={source.original_filename}>{source.original_filename}</p></td>
              <td className="no-wrap">{duration(source.duration_seconds)}</td><td className="no-wrap">{resolution(source)}</td><td className="no-wrap">{size(source.file_size_bytes)}</td><td className="no-wrap"><time dateTime={source.created_at}>{new Date(source.created_at).toLocaleDateString('uk-UA')}</time></td>
              <td><button type="button" className="icon-button" aria-label={`Переглянути ${source.name}`} onClick={() => setSelectedId(source.id)}><Icon name="play" /></button></td>
            </tr>)}</tbody></table></div>
          {result.total > 10 && <nav aria-label="Сторінки списку" className="pagination"><button className="secondary" type="button" disabled={page === 1 || listLoading} onClick={() => setPage(value => value - 1)}>Назад</button><span>Сторінка {page} з {Math.ceil(result.total / 10)}</span><button className="secondary" type="button" disabled={page * 10 >= result.total || listLoading} onClick={() => setPage(value => value + 1)}>Далі</button></nav>}
        </>}
      </Panel>
      {selectedId && <Panel title="Перегляд джерела" className="source-preview" actions={<button className="icon-button" aria-label="Закрити перегляд" onClick={() => setSelectedId(null)}><Icon name="close" /></button>}>
        {detailError && <Notice tone="error">{detailError}</Notice>}
        {!selected && !detailError && <div className="loading-row" role="status">Завантажуємо деталі…</div>}
        {selected && <>
          <video className="video-player" key={selected.id} controls preload="metadata" aria-label={`Відео: ${selected.name}`} src={`${api}/api/video-sources/${selected.id}/content`} onError={event => {
            const code = event.currentTarget.error?.code
            setPlayerError(code === 3 || code === 4 ? 'Браузер не підтримує контейнер або кодек цього відео, або запис не декодується. Автоматичне перекодування не виконується.' : 'Не вдалося отримати відео. Перевірте підключення до API та наявність файлу.')
          }} onLoadedMetadata={() => setPlayerError('')} />
          {playerError && <div className="section-gap"><Notice tone="error">{playerError}</Notice></div>}
          <div className="video-meta"><h3>{selected.name}</h3><dl>
            <dt>Оригінальний файл</dt><dd>{selected.original_filename}</dd><dt>Тривалість</dt><dd>{duration(selected.duration_seconds)}</dd><dt>Роздільність</dt><dd>{resolution(selected)}</dd><dt>Розмір</dt><dd>{size(selected.file_size_bytes)}</dd><dt>Додано</dt><dd>{new Date(selected.created_at).toLocaleString('uk-UA')}</dd><dt>Контейнер / кодек</dt><dd>{selected.container_format ?? 'Невідомо'} / {selected.video_codec ?? 'Невідомо'}</dd><dt>Середня частота</dt><dd>{selected.avg_frame_rate ?? 'Невідомо'}</dd>
          </dl><p className="muted">Середня частота не означає сталу частоту кадрів. Відтворення залежить від контейнера, кодека й браузера.</p></div>
        </>}
      </Panel>}
    </div>
  </div>
}
