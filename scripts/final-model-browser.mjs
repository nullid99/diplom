// Real, explicitly authorized integration check. Creates one video source/run;
// uses registered final weights, the real API/DB/worker, and no mocked detector.
import assert from 'node:assert/strict'
import { createRequire } from 'node:module'
import { spawn } from 'node:child_process'
import { openSync, closeSync } from 'node:fs'
import { mkdir, readFile, writeFile } from 'node:fs/promises'
import path from 'node:path'
const require=createRequire(path.resolve('frontend/package.json'))
const {chromium}=require('playwright-core')
const output=path.resolve('reports/ml/final-verification-20261102')
const material=JSON.parse(await readFile(path.join(output,'examples/evidence.json'),'utf8'))
const api='http://127.0.0.1:8000'
const sourceName='Технічний відеоряд val D-Fire — не незалежне відео'
const modelId='8c37f231-7e6e-4db4-8405-0e4f731c4b87'
await mkdir(path.join(output,'application'),{recursive:true})
const evidence={started_at:new Date().toISOString(),mocked:false,test_used:false,device:'cuda:0',
  material_limitation:material.limitation,ws_snapshots:[],page_errors:[],console_errors:[]}
const save=()=>writeFile(path.join(output,'application/browser-check.json'),JSON.stringify(evidence,null,2))
const browser=await chromium.launch({channel:'msedge',headless:true,args:['--disable-gpu','--disable-accelerated-video-decode']})
let worker
try {
  const page=await browser.newPage({viewport:{width:1600,height:1000},deviceScaleFactor:1})
  page.setDefaultTimeout(30000)
  page.on('pageerror',error=>evidence.page_errors.push(error.message))
  page.on('console',message=>{if(message.type()==='error')evidence.console_errors.push(message.text())})
  page.on('websocket',socket=>socket.on('framereceived',event=>{
    try {
      const body=JSON.parse(String(event.payload))
      const run=body.selected
      if(run) evidence.ws_snapshots.push({at:new Date().toISOString(),id:run.id,status:run.status,progress:run.progress,summary:run.summary_metrics})
    } catch {}
  }))
  const models=await(await page.request.get(api+'/api/model-versions')).json()
  assert.equal(models.gpu_enabled,true)
  assert.ok(models.items.some(model=>model.id===modelId&&model.available))
  const prior=await(await page.request.get(api+'/api/analysis-runs')).json()
  assert.equal(prior.items.filter(run=>['pending','running'].includes(run.status)).length,0,'Another analysis is already queued/running')
  await page.goto('http://127.0.0.1:5173/sources')
  const sources=await(await page.request.get(api+'/api/video-sources')).json()
  let source=sources.items.find(item=>item.name===sourceName)
  if(!source){
    await page.getByLabel('Назва джерела',{exact:true}).fill(sourceName)
    await page.locator('#video-file').setInputFiles(path.resolve(material.video))
    const uploaded=page.waitForResponse(response=>response.url()===api+'/api/video-sources'&&response.request().method()==='POST')
    await page.getByRole('button',{name:'Завантажити відео',exact:true}).click()
    const response=await uploaded
    assert.equal(response.status(),201)
    source=await response.json()
    evidence.uploaded_via_ui=true
  }
  evidence.source=source
  await page.screenshot({path:path.join(output,'application/source.png'),fullPage:true})
  await page.goto('http://127.0.0.1:5173/analysis')
  await page.getByLabel('Відеоджерело',{exact:true}).selectOption(source.id)
  await page.getByLabel('Версія моделі',{exact:true}).selectOption(modelId)
  await page.getByRole('combobox',{name:/^Пристрій/}).selectOption('cuda:0')
  await page.getByLabel('Поріг smoke',{exact:true}).fill('0.25')
  await page.getByLabel('Поріг fire',{exact:true}).fill('0.25')
  await page.getByLabel('Частота аналізу, кадрів/с',{exact:true}).fill('2')
  const created=page.waitForResponse(response=>response.url()===api+'/api/analysis-runs'&&response.request().method()==='POST')
  await page.getByRole('button',{name:'Запустити аналіз',exact:true}).click()
  const response=await created
  assert.equal(response.status(),201)
  const run=await response.json()
  evidence.run_id=run.id
  evidence.created=run
  await save()
  const stdout=openSync(path.join(output,'application/worker-stdout.log'),'wx')
  const stderr=openSync(path.join(output,'application/worker-stderr.log'),'wx')
  worker=spawn('powershell.exe',['-NoProfile','-ExecutionPolicy','Bypass','-Command',
    ". .\\scripts\\analysis-env.ps1; $env:ANALYSIS_ALLOW_GPU='true'; Use-AnalysisEnvironment { & .\\.venv\\Scripts\\python.exe -X utf8 -u -m backend.app.analysis_worker --once; exit $LASTEXITCODE }"],
    {cwd:process.cwd(),windowsHide:true,stdio:['ignore',stdout,stderr]})
  closeSync(stdout);closeSync(stderr)
  evidence.worker_launcher_pid=worker.pid
  const exited=new Promise(resolve=>worker.once('exit',(code,signal)=>resolve({code,signal})))
  await save()
  const deadline=Date.now()+240000
  let finished
  while(Date.now()<deadline){
    const detail=await page.request.get(api+'/api/analysis-runs/'+run.id)
    assert.equal(detail.status(),200)
    finished=await detail.json()
    evidence.latest=finished
    await save()
    if(['completed','failed','stopped'].includes(finished.status))break
    await page.waitForTimeout(500)
  }
  assert.equal(finished.status,'completed',JSON.stringify(finished))
  evidence.worker_exit=await exited
  assert.equal(evidence.worker_exit.code,0)
  await page.waitForFunction(()=>document.querySelector('video[aria-label="Відео результату аналізу"]'))
  const video=page.getByLabel('Відео результату аналізу',{exact:true})
  await page.waitForFunction(()=>document.querySelector('video')?.readyState>=2)
  evidence.video_metadata=await video.evaluate(element=>({duration:element.duration,width:element.videoWidth,height:element.videoHeight,error:element.error?.message||null}))
  assert.equal(evidence.video_metadata.error,null)
  assert.ok(Math.abs(evidence.video_metadata.duration-material.duration_seconds)<.001)
  const detectionsResponse=await page.request.get(api+`/api/analysis-runs/${run.id}/files/detections`)
  assert.equal(detectionsResponse.status(),200)
  const jsonl=await detectionsResponse.text()
  const detections=jsonl.trim().split('\n').map(line=>JSON.parse(line))
  await writeFile(path.join(output,'application/detections-downloaded.jsonl'),jsonl)
  evidence.frames=detections.length
  assert.equal(detections.length,material.frames.length)
  for(let index=0;index<detections.length;index++){
    assert.equal(detections[index].frame_index,index)
    assert.ok(Math.abs(detections[index].time_seconds-material.frames[index].time_seconds)<.000002)
    assert.equal(detections[index].analyzed,index%2===0)
  }
  const range=await page.request.get(api+`/api/analysis-runs/${run.id}/files/video`,{headers:{Range:'bytes=100-199'}})
  assert.equal(range.status(),206)
  assert.equal((await range.body()).length,100)
  evidence.range={status:range.status(),content_range:range.headers()['content-range']}
  const target=detections.find(row=>row.detections.length>0)
  assert.ok(target,'No real detections on the technical montage')
  evidence.preview_frame=target
  await video.evaluate(async(element,time)=>{
    await new Promise((resolve,reject)=>{
      element.addEventListener('seeked',resolve,{once:true})
      element.addEventListener('error',reject,{once:true})
      element.currentTime=time
    })
  },target.time_seconds+.02)
  evidence.seek_time=await video.evaluate(element=>element.currentTime)
  await video.screenshot({path:path.join(output,'application/annotated-video-frame.png')})
  await page.screenshot({path:path.join(output,'application/completed.png'),fullPage:true})
  const downloadPromise=page.waitForEvent('download')
  await page.getByRole('link',{name:'Виявлення JSONL',exact:true}).click()
  const download=await downloadPromise
  await download.saveAs(path.join(output,'application/detections-ui-download.jsonl'))
  assert.equal(await readFile(path.join(output,'application/detections-ui-download.jsonl'),'utf8'),jsonl)
  evidence.ui_download=true
  await page.reload()
  await page.getByLabel('Відео результату аналізу',{exact:true}).waitFor()
  assert.equal(await page.evaluate(()=>localStorage.getItem('firevision-analysis-id')),run.id)
  assert.equal((await(await page.request.get(api+'/api/analysis-runs/'+run.id)).json()).status,'completed')
  evidence.persisted_after_reload=true
  assert.ok(evidence.ws_snapshots.some(row=>row.id===run.id&&row.status==='running'&&row.progress>0&&row.progress<1),'No real intermediate WebSocket progress observed')
  assert.deepEqual(evidence.page_errors,[])
  assert.deepEqual(evidence.console_errors,[])
  evidence.result='passed'
  evidence.finished_at=new Date().toISOString()
  await save()
  console.log(JSON.stringify({result:evidence.result,run_id:run.id,frames:evidence.frames,summary:finished.summary_metrics}))
} catch(error){
  evidence.result='failed'
  evidence.failure=String(error.stack||error)
  await save()
  throw error
} finally {
  await browser.close()
}
