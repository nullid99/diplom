import { useEffect, useRef, useState, type PointerEvent } from 'react'
import { apiBase } from './api'
import { Notice, Panel } from './ui'
export type Zone = { id: string; name: string; mode: 'include' | 'exclude'; x1: number; y1: number; x2: number; y2: number }
type Drag = { id: string; mode: 'draw' | 'move' | 'resize'; x: number; y: number; original: Zone }
const clamp = (value: number) => Math.max(0, Math.min(1, value))
export function ZoneEditor({ sourceId, onDirty }: { sourceId: string; onDirty: (value: boolean) => void }) {
  const video = useRef<HTMLVideoElement>(null)
  const svg = useRef<SVGSVGElement>(null)
  const drag = useRef<Drag | null>(null)
  const [zones,setZones]=useState<Zone[]>([])
  const [selected,setSelected]=useState('')
  const [tool,setTool]=useState<'include'|'exclude'|null>(null)
  const [dirty,setDirty]=useState(false)
  const [busy,setBusy]=useState(true)
  const [loaded,setLoaded]=useState(false)
  const sourceRef=useRef(sourceId)
  sourceRef.current=sourceId
  const [error,setError]=useState('')
  const [notice,setNotice]=useState('')
  const [duration,setDuration]=useState(0)
  const [time,setTime]=useState(0)
  const [playing,setPlaying]=useState(false)
  const [imageRect,setImageRect]=useState({left:0,top:0,width:0,height:0})
  function change(next: Zone[]) { setZones(next);setDirty(true);onDirty(true);if(!drag.current)setNotice('') }
  useEffect(()=>{
    const controller=new AbortController()
    setZones([]);setSelected('');setTool(null);setDirty(false);onDirty(true);setError('');setNotice('');setBusy(true);setLoaded(false);setDuration(0);setTime(0);setPlaying(false);drag.current=null
    fetch(`${apiBase}/api/video-sources/${sourceId}/zones`,{signal:controller.signal}).then(async response=>{
      if(!response.ok)throw new Error('Не вдалося отримати зони джерела.')
      return response.json()
    }).then(body=>{if(!controller.signal.aborted){setZones(body.zones);setLoaded(true);onDirty(false)}}).catch(reason=>{if(!controller.signal.aborted)setError(reason.message)})
      .finally(()=>{if(!controller.signal.aborted)setBusy(false)})
    return ()=>controller.abort()
  },[sourceId,onDirty])
  useEffect(()=>{
    const element=video.current
    if(!element)return
    const measure=()=>{
      if(!element.videoWidth)return
      const scale=Math.min(element.clientWidth/element.videoWidth,element.clientHeight/element.videoHeight)
      const width=element.videoWidth*scale,height=element.videoHeight*scale
      setImageRect({left:element.offsetLeft+(element.clientWidth-width)/2,top:element.offsetTop+(element.clientHeight-height)/2,width,height})
    }
    const observer=new ResizeObserver(measure)
    observer.observe(element);element.addEventListener('loadedmetadata',measure);measure()
    return ()=>{observer.disconnect();element.removeEventListener('loadedmetadata',measure)}
  },[sourceId,duration])
  function position(event: PointerEvent<SVGElement>) {
    const box=svg.current!.getBoundingClientRect()
    return {x:clamp((event.clientX-box.left)/box.width),y:clamp((event.clientY-box.top)/box.height)}
  }
  function begin(event: PointerEvent<SVGElement>,zone?:Zone,resize=false) {
    if(busy||!duration||!loaded)return
    if(tool&&!resize)zone=undefined
    if(!zone&&!tool)return
    event.preventDefault();event.stopPropagation();video.current?.pause();svg.current?.setPointerCapture(event.pointerId)
    const point=position(event)
    if(zone){setSelected(zone.id);drag.current={id:zone.id,mode:resize?'resize':'move',...point,original:{...zone}}}
    else{
      const created:Zone={id:crypto.randomUUID(),name:`Зона ${zones.length+1}`,mode:tool!,x1:point.x,y1:point.y,x2:point.x,y2:point.y}
      setSelected(created.id);drag.current={id:created.id,mode:'draw',...point,original:created};change([...zones,created])
    }
  }
  function move(event:PointerEvent<SVGSVGElement>){
    const active=drag.current;if(!active)return
    const point=position(event),original=active.original
    let rectangle:Partial<Zone>
    if(active.mode==='move'){
      const dx=Math.max(-original.x1,Math.min(1-original.x2,point.x-active.x)),dy=Math.max(-original.y1,Math.min(1-original.y2,point.y-active.y))
      rectangle={x1:original.x1+dx,x2:original.x2+dx,y1:original.y1+dy,y2:original.y2+dy}
    }else if(active.mode==='resize')rectangle={x2:Math.max(original.x1+.001,point.x),y2:Math.max(original.y1+.001,point.y)}
    else rectangle={x1:Math.min(active.x,point.x),x2:Math.max(active.x,point.x),y1:Math.min(active.y,point.y),y2:Math.max(active.y,point.y)}
    change(zones.map(zone=>zone.id===active.id?{...zone,...rectangle}:zone))
  }
  function finish(){
    const active=drag.current;drag.current=null
    if(active?.mode==='draw'){change(zones.filter(zone=>zone.x2-zone.x1>=.001&&zone.y2-zone.y1>=.001));setTool(null)}
    else setNotice('')
  }
  async function save(){
    if(!loaded)return
    const savingSource=sourceId
    setBusy(true);setError('')
    try{
      const response=await fetch(`${apiBase}/api/video-sources/${sourceId}/zones`,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({zones})})
      if(!response.ok)throw new Error(response.status===422?'Перевірте координати: ліва/верхня межа має бути меншою за праву/нижню.':'Зони не збережено. Перевірте з’єднання.')
      const saved=await response.json()
      if(sourceRef.current!==savingSource)return
      setZones(saved.zones);setDirty(false);onDirty(false);setNotice('Зони джерела збережено. Минулі запуски не змінені.')
    }catch(reason){if(sourceRef.current===savingSource)setError((reason as Error).message)}finally{if(sourceRef.current===savingSource)setBusy(false)}
  }
  const current=zones.find(zone=>zone.id===selected)
  function coordinate(key:'x1'|'y1'|'x2'|'y2',percent:number){
    if(!current||!Number.isFinite(percent))return
    let value=clamp(percent/100)
    if(key==='x1')value=Math.min(value,current.x2-.001)
    if(key==='y1')value=Math.min(value,current.y2-.001)
    if(key==='x2')value=Math.max(value,current.x1+.001)
    if(key==='y2')value=Math.max(value,current.y1+.001)
    change(zones.map(zone=>zone.id===selected?{...zone,[key]:value}:zone))
  }
  return <Panel title="Зони спостереження" description="Центр рамки визначає включення. Виключення має пріоритет; без включаючих зон доступний увесь кадр.">
    {error&&<Notice tone="error">{error}</Notice>}{notice&&<Notice>{notice}</Notice>}
    <div className="zone-toolbar"><button type="button" className={tool==='include'?'':'secondary'} disabled={busy||!loaded||!duration||zones.length>=32} onClick={()=>setTool('include')}>Додати зону спостереження</button><button type="button" className={tool==='exclude'?'':'secondary'} disabled={busy||!loaded||!duration||zones.length>=32} onClick={()=>setTool('exclude')}>Додати виключення</button><button type="button" disabled={!dirty||busy||!loaded} onClick={()=>void save()}>Зберегти зони</button></div>
    <p className="field-help">{tool?'Протягніть прямокутник по кадру.':'Перетягніть область або її нижній правий кут. Координати також можна змінити з клавіатури нижче.'}</p>
    <div className="zone-stage"><video key={sourceId} ref={video} preload="auto" src={`${apiBase}/api/video-sources/${sourceId}/content`} onLoadedMetadata={event=>setDuration(event.currentTarget.duration)} onTimeUpdate={event=>setTime(event.currentTarget.currentTime)} onPlay={()=>setPlaying(true)} onPause={()=>setPlaying(false)} onError={()=>setError('Цей відеофайл не вдалося відкрити в редакторі. Перевірте підтримку кодека браузером.')} />
      <svg ref={svg} viewBox="0 0 1000 1000" preserveAspectRatio="none" style={{...imageRect,position:'absolute'}} aria-label="Редактор зон на кадрі" onPointerDown={event=>begin(event)} onPointerMove={move} onPointerUp={finish} onPointerCancel={finish}>
        {zones.map(zone=><g key={zone.id}><rect x={zone.x1*1000} y={zone.y1*1000} width={(zone.x2-zone.x1)*1000} height={(zone.y2-zone.y1)*1000} className={`zone-box ${zone.mode} ${selected===zone.id?'selected':''}`} onPointerDown={event=>begin(event,zone)} /><text x={zone.x1*1000+5} y={zone.y1*1000+25} className="zone-caption">{zone.name}</text>{selected===zone.id&&<rect x={zone.x2*1000-9} y={zone.y2*1000-9} width="18" height="18" className="zone-handle" onPointerDown={event=>begin(event,zone,true)} />}</g>)}
      </svg>
    </div>
    <div className="zone-playback"><button className="secondary" type="button" disabled={!duration} onClick={()=>{const element=video.current!;if(playing)element.pause();else void element.play().catch(()=>setError('Браузер не зміг почати відтворення.'))}}>{playing?'Пауза':'Відтворити'}</button><input aria-label="Кадр для редагування зон" type="range" min="0" max={duration||1} step="0.01" value={time} onChange={event=>{if(video.current)video.current.currentTime=+event.target.value}} /><span>{time.toFixed(2)} с</span></div>
    {zones.length===0&&<p className="muted">Зон немає — аналізується весь кадр.</p>}
    <div className="zone-list">{zones.map(zone=><button type="button" className={selected===zone.id?'':'secondary'} key={zone.id} onClick={()=>setSelected(zone.id)}>{zone.name} · {zone.mode==='include'?'спостереження':'виключення'}</button>)}</div>
    {current&&<div className="zone-properties"><label>Назва зони<input maxLength={80} value={current.name} onChange={event=>change(zones.map(zone=>zone.id===selected?{...zone,name:event.target.value}:zone))} /></label><label>Правило зони<select value={current.mode} onChange={event=>change(zones.map(zone=>zone.id===selected?{...zone,mode:event.target.value as Zone['mode']}:zone))}><option value="include">Спостереження</option><option value="exclude">Виключення</option></select></label>{(['x1','y1','x2','y2'] as const).map(key=><label key={key}>{key}, %<input type="number" min="0" max="100" step="0.1" value={Number.isFinite(current[key])?Math.round(current[key]*1000)/10:''} onChange={event=>coordinate(key,event.target.valueAsNumber)} /></label>)}<button type="button" className="danger" onClick={()=>{change(zones.filter(zone=>zone.id!==selected));setSelected('')}}>Видалити зону</button></div>}
    {dirty&&<p className="field-help">Є незбережені зміни. Збережіть зони перед запуском аналізу.</p>}
  </Panel>
}
