import { useEffect, useRef, useState, type FormEvent } from 'react'
import { apiBase, useRemotePage, type Page, type SourceOption } from './api'
import { Badge, EmptyState, Notice, PageHeading, Panel } from './ui'
type EventRow = { id:string; source_name:string; analysis_run_id:string; model_version_id:string; feature_type:string; automatic_status:string; start_seconds:number; confirmed_seconds:number|null; last_seen_seconds:number|null; closed_seconds:number|null; closure_reason:string|null; confidence:number|null; review_status:string; operator_comment:string|null; created_at:string; updated_at:string; has_frame:boolean; has_clip:boolean; region?:Record<string,unknown>; settings_snapshot?:Record<string,unknown> }
const reviews:Record<string,string>={unreviewed:'Не перевірено',confirmed:'Підтверджено оператором',false_positive:'Хибне спрацювання',needs_review:'Потребує перевірки'}
const statuses:Record<string,string>={suspected:'Кандидат',confirmed:'Підтверджено алгоритмом',completed:'Завершено',interrupted:'Перервано'}
const reasons:Record<string,string>={absence:'Відсутність ознак',eof:'Кінець відео',cancelled:'Скасування аналізу',failed:'Помилка аналізу',worker_interrupted:'Аварія worker (точний час зупинки невідомий)'}
const seconds=(value:number|null|undefined)=>value===null||value===undefined?'—':`${Number(value).toFixed(3)} с`
export function EventsPage(){
  const sources=useRemotePage<SourceOption>('/api/video-sources?page=1&page_size=100')
  const [source,setSource]=useState(''),[feature,setFeature]=useState(''),[review,setReview]=useState(''),[from,setFrom]=useState(''),[to,setTo]=useState('')
  const [query,setQuery]=useState(''),[page,setPage]=useState(1),[revision,setRevision]=useState(0)
  const [result,setResult]=useState<Page<EventRow>|null>(null),[loading,setLoading]=useState(true),[error,setError]=useState('')
  const [selected,setSelected]=useState<EventRow|null>(null),[cardError,setCardError]=useState(''),[cardLoading,setCardLoading]=useState(false)
  const [operatorStatus,setOperatorStatus]=useState('unreviewed'),[comment,setComment]=useState(''),[saving,setSaving]=useState(false),[notice,setNotice]=useState('')
  const dialog=useRef<HTMLDialogElement>(null)
  const opener=useRef<HTMLButtonElement|null>(null)
  useEffect(()=>{
    const controller=new AbortController();setLoading(true);setError('')
    fetch(`${apiBase}/api/events?page=${page}&page_size=20${query}`,{signal:controller.signal,cache:'no-store'}).then(async response=>{
      if(!response.ok)throw new Error(response.status===422?'Перевірте період і фільтри.':'Не вдалося завантажити журнал подій.')
      return response.json()
    }).then(setResult).catch(reason=>{if(!controller.signal.aborted)setError(reason.message)}).finally(()=>{if(!controller.signal.aborted)setLoading(false)})
    return()=>controller.abort()
  },[page,query,revision])
  function filter(event:FormEvent){
    event.preventDefault();const params=new URLSearchParams()
    if(source)params.set('source_id',source);if(feature)params.set('feature_type',feature);if(review)params.set('review_status',review)
    if(from)params.set('since',new Date(from).toISOString());if(to)params.set('until',new Date(to).toISOString())
    setPage(1);setQuery('&'+params.toString());setRevision(value=>value+1)
  }
  async function open(id:string,button:HTMLButtonElement){
    opener.current=button;setSelected(null);setCardError('');setNotice('');setCardLoading(true);dialog.current?.showModal()
    try{
      const response=await fetch(`${apiBase}/api/events/${id}`,{cache:'no-store'})
      if(!response.ok)throw new Error('Картка події недоступна.')
      const detail=await response.json();setSelected(detail);setOperatorStatus(detail.review_status);setComment(detail.operator_comment||'')
    }catch(reason){setCardError((reason as Error).message)}finally{setCardLoading(false)}
  }
  async function save(event:FormEvent){
    event.preventDefault();if(!selected)return;setSaving(true);setCardError('');setNotice('')
    try{
      const response=await fetch(`${apiBase}/api/events/${selected.id}/review`,{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify({review_status:operatorStatus,operator_comment:comment,expected_updated_at:selected.updated_at})})
      if(!response.ok)throw new Error(response.status===409?'Картка змінилась. Закрийте й відкрийте її знову перед збереженням.':'Оцінку не збережено. Перевірте з’єднання.')
      setSelected(await response.json());setNotice('Оцінку й коментар збережено.');setRevision(value=>value+1)
    }catch(reason){setCardError((reason as Error).message)}finally{setSaving(false)}
  }
  return <div><PageHeading title="Журнал подій" description="Підтверджені часовим алгоритмом області та окрема перевірка оператором." actions={<button className="secondary" onClick={()=>setRevision(value=>value+1)}>Оновити журнал</button>} />
    <Panel title="Фільтри"><form className="filters" onSubmit={filter}><label>Відеоджерело<select value={source} onChange={event=>setSource(event.target.value)}><option value="">Усі джерела</option>{sources.data?.items.map(item=><option key={item.id} value={item.id}>{item.name}</option>)}</select></label><label>Тип ознак<select value={feature} onChange={event=>setFeature(event.target.value)}><option value="">Усі типи</option><option value="smoke">Дим (smoke)</option><option value="fire">Вогонь (fire)</option></select></label><label>Період від<input type="datetime-local" value={from} onChange={event=>setFrom(event.target.value)} /></label><label>Період до<input type="datetime-local" value={to} onChange={event=>setTo(event.target.value)} /></label><label>Оцінка оператора<select value={review} onChange={event=>setReview(event.target.value)}><option value="">Усі оцінки</option>{Object.entries(reviews).map(([key,title])=><option key={key} value={key}>{title}</option>)}</select></label><button type="submit">Застосувати</button></form><p className="field-help">Період фільтрує дату реєстрації події, не секунди відео. Введений місцевий час передається з часовим поясом.</p>{sources.error&&<Notice tone="error">{sources.error}</Notice>}</Panel>
    <div className="section-gap"><Panel title="Події" description={result?`${result.total} подій за фільтрами`:undefined} className="table-panel">
      {loading&&<div className="loading-row" role="status">Завантажуємо події…</div>}{error&&<Notice tone="error">{error}</Notice>}
      {!loading&&!error&&result?.total===0&&<EmptyState icon="events" title="Подій за цими умовами немає">Події з’являться після нового аналізу з часовим підтвердженням. Старі покадрові результати автоматично не перетворюються на події.</EmptyState>}
      {!loading&&!error&&!!result?.items.length&&<div className="table-wrap"><table><thead><tr><th>Зареєстровано</th><th>Джерело</th><th>Ознаки</th><th>Підтвердження у відео</th><th>Автоматичний стан</th><th>Оцінка оператора</th></tr></thead><tbody>{result.items.map(item=><tr key={item.id}><td><button className="source-title" onClick={event=>void open(item.id,event.currentTarget)}>{new Date(item.created_at).toLocaleString('uk-UA')}</button></td><td>{item.source_name}</td><td><Badge tone={item.feature_type==='fire'?'warning':'blue'}>{item.feature_type}</Badge></td><td>{seconds(item.confirmed_seconds)}</td><td>{statuses[item.automatic_status]}</td><td>{reviews[item.review_status]}</td></tr>)}</tbody></table></div>}
      {result&&result.total>result.page_size&&<nav className="pagination" aria-label="Сторінки подій"><button className="secondary" disabled={page===1} onClick={()=>setPage(page-1)}>Назад</button><span>Сторінка {page}</span><button className="secondary" disabled={page*result.page_size>=result.total} onClick={()=>setPage(page+1)}>Далі</button></nav>}
    </Panel></div>
    <dialog ref={dialog} className="event-dialog" aria-labelledby="event-title" onClose={()=>opener.current?.focus()}><div className="dialog-heading"><h2 id="event-title">Картка події{selected?` · ${selected.feature_type}`:''}</h2><button className="secondary" onClick={()=>dialog.current?.close()}>Закрити</button></div>
      {cardLoading&&<p role="status">Завантажуємо картку…</p>}{cardError&&<Notice tone="error">{cardError}</Notice>}{notice&&<Notice>{notice}</Notice>}
      {selected&&<><p>{selected.source_name} · {statuses[selected.automatic_status]}</p><div className="event-evidence-grid">{selected.has_frame?<img className="event-frame" src={`${apiBase}/api/events/${selected.id}/files/frame`} alt={`Кадр підтвердження ${selected.feature_type} на ${seconds(selected.confirmed_seconds)}`} onError={()=>setCardError('Кадр події недоступний.')} />:<p className="muted">Кадр недоступний.</p>}{selected.has_clip?<video key={selected.id} className="video-player" controls preload="metadata" aria-label="Фрагмент події" src={`${apiBase}/api/events/${selected.id}/files/clip`} onError={()=>setCardError('Фрагмент не відкрився. Перевірте наявність файлу й підтримку кодека.')} />:<p className="muted">Фрагмент недоступний.</p>}</div>
        <dl className="event-times"><dt>Перше виявлення</dt><dd>{seconds(selected.start_seconds)}</dd><dt>Підтвердження</dt><dd>{seconds(selected.confirmed_seconds)}</dd><dt>Останнє виявлення</dt><dd>{seconds(selected.last_seen_seconds)}</dd><dt>Закриття</dt><dd>{seconds(selected.closed_seconds)}</dd><dt>Причина закриття</dt><dd>{selected.closure_reason?reasons[selected.closure_reason]:'Подія активна'}</dd><dt>Максимальна впевненість</dt><dd>{selected.confidence===null?'—':Number(selected.confidence).toFixed(3)}</dd><dt>Початок / кінець фрагмента у джерелі</dt><dd>{seconds(selected.region?.clip_start_seconds as number)} / {seconds(selected.region?.clip_end_seconds as number)}</dd><dt>Підтвердження від початку фрагмента</dt><dd>{seconds(selected.region?.clip_confirmation_seconds as number)}</dd></dl>
        <form onSubmit={save}><label>Оцінка оператора<select aria-label="Оцінка оператора" value={operatorStatus} onChange={event=>setOperatorStatus(event.target.value)}>{Object.entries(reviews).map(([key,title])=><option key={key} value={key}>{title}</option>)}</select></label><label>Коментар оператора<textarea aria-label="Коментар оператора" maxLength={4000} rows={3} value={comment} onChange={event=>setComment(event.target.value)} /></label><div className="form-actions"><button disabled={saving} type="submit">{saving?'Зберігаємо…':'Зберегти оцінку'}</button></div></form><p className="field-help">Оцінка не змінює автоматичний стан і не запускає донавчання.</p><details><summary>Запуск, модель і знімок налаштувань</summary><p>Запуск: <code>{selected.analysis_run_id}</code></p><p>Модель: <code>{selected.model_version_id}</code></p><pre>{JSON.stringify(selected.settings_snapshot,null,2)}</pre></details>
      </>}
    </dialog>
  </div>
}
