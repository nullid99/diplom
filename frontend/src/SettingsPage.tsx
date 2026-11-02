import { useEffect, useState, type FormEvent } from 'react'
import { apiBase, analysisDefaults, useRemotePage, type ModelVersion } from './api'
import { TemporalFields, temporalDefaults, type Temporal } from './TemporalFields'
import { Notice, PageHeading, Panel } from './ui'
export function SettingsPage(){
  const [temporal,setTemporal]=useState<Temporal>(temporalDefaults),[fps,setFps]=useState(2),[loading,setLoading]=useState(true),[saving,setSaving]=useState(false),[error,setError]=useState(''),[notice,setNotice]=useState('')
  const config=useRemotePage<ModelVersion>('/api/model-versions?page_size=1')
  useEffect(()=>{
    const controller=new AbortController()
    fetch(`${apiBase}/api/analysis-defaults`,{signal:controller.signal}).then(async response=>{if(!response.ok)throw new Error('Не вдалося отримати налаштування.');return response.json()}).then(body=>{setTemporal(body.temporal);setFps(body.analysis_fps)}).catch(reason=>{if(!controller.signal.aborted)setError(reason.message)}).finally(()=>{if(!controller.signal.aborted)setLoading(false)})
    return()=>controller.abort()
  },[])
  async function save(event:FormEvent){
    event.preventDefault();setSaving(true);setError('');setNotice('')
    try{
      const response=await fetch(`${apiBase}/api/analysis-defaults`,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({analysis_fps:fps,temporal})})
      if(!response.ok)throw new Error(response.status===422?'Часові параметри неузгоджені: перевірте вікно, кількість кадрів, мінімальну тривалість і частоту аналізу.':'Налаштування не збережені. Перевірте з’єднання.')
      const saved=await response.json();setTemporal(saved.temporal);setFps(saved.analysis_fps);setNotice('Типові налаштування збережено для нових запусків. Попередні запуски не змінені.')
    }catch(reason){setError((reason as Error).message)}finally{setSaving(false)}
  }
  return <div><PageHeading title="Налаштування" description="Типові часові правила для нових запусків. Інженерні початкові значення, без твердження про оптимальність." />{error&&<Notice tone="error">{error}</Notice>}{notice&&<Notice>{notice}</Notice>}
    <form onSubmit={save}><div className="settings-layout"><Panel title="Часове підтвердження" description="Окреме зіставлення областей smoke/fire. Кілька рамок одного кадру не замінюють спостереження в різні моменти часу.">{loading?<p role="status">Завантажуємо налаштування…</p>:<TemporalFields value={temporal} onChange={setTemporal} />}</Panel><div className="stack"><Panel title="Оброблення відео"><label>Типова частота аналізу, кадрів/с<input required type="number" min="0.1" max="60" step="0.1" value={Number.isFinite(fps)?fps:''} disabled={loading} onChange={event=>setFps(event.target.valueAsNumber)} /></label><p className="field-help">Для N підтверджень потрібно щонайменше (N−1)/частота секунд у вікні. Інтервал відсутності не повинен бути меншим за інтервал аналізу. Реальне відео може мати рідші або нерівні кадри.</p><dl><dt>Відео</dt><dd>MP4 · H.264, усі кадри й вихідні часові мітки; без звуку</dd><dt>Виявлення</dt><dd>Покадровий JSONL, окремо від PostgreSQL</dd></dl></Panel><Panel title="Детектор"><p>Пороги класів, розмір зображення та пристрій задаються для конкретного запуску на сторінці «Аналіз відео».</p><dl><dt>Початкові пороги smoke/fire</dt><dd>{analysisDefaults.smoke} / {analysisDefaults.fire}</dd><dt>GPU дозволено сервером</dt><dd>{typeof config.data?.gpu_enabled==='boolean'?config.data.gpu_enabled?'Так':'Ні':'—'}</dd></dl></Panel></div></div><div className="settings-footer"><p>Зони зберігаються окремо для кожного джерела в редакторі аналізу.</p><button disabled={loading||saving} type="submit">{saving?'Зберігаємо…':'Зберегти налаштування'}</button></div></form>
  </div>
}
