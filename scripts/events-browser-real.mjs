// Real working API/browser. Temporary zone/default edits are restored in finally.
// Does not create events, analysis runs, models, or invoke any detector.
import assert from 'node:assert/strict'
import {createRequire} from 'node:module'
import {mkdir,writeFile} from 'node:fs/promises'
import path from 'node:path'
const {chromium}=createRequire(path.resolve('frontend/package.json'))('playwright-core')
const api='http://127.0.0.1:8000',base='http://127.0.0.1:5173',output=path.resolve('reports/events')
await mkdir(output,{recursive:true})
const browser=await chromium.launch({channel:'msedge',headless:true,args:['--disable-gpu','--disable-accelerated-video-decode']})
const context=await browser.newContext({viewport:{width:1366,height:1000},deviceScaleFactor:1})
const page=await context.newPage()
const errors=[]
page.on('pageerror',error=>errors.push(error.message))
page.on('console',message=>{if(message.type()==='error')errors.push(message.text())})
const sources=await(await context.request.get(api+'/api/video-sources')).json()
const source=sources.items[0]
assert.ok(source,'A previously uploaded source is required')
const originalZones=await(await context.request.get(api+`/api/video-sources/${source.id}/zones`)).json()
const originalDefaults=await(await context.request.get(api+'/api/analysis-defaults')).json()
const evidence={source_id:source.id,source_name:source.name,natural_video_test:false,created_events:false,created_runs:false,checks:[],errors}
async function saveZones(){
  const response=page.waitForResponse(response=>response.url().endsWith('/zones')&&response.request().method()==='PUT')
  await page.getByRole('button',{name:'Зберегти зони',exact:true}).click()
  assert.equal((await response).status(),200)
}
async function selectSource(){
  await page.getByLabel('Відеоджерело',{exact:true}).selectOption(source.id)
  await page.getByRole('button',{name:'Додати зону спостереження',exact:true}).waitFor()
  await page.waitForFunction(()=>[...document.querySelectorAll('button')].some(button=>button.textContent==='Додати зону спостереження'&&!button.disabled))
}
async function draw(button,start,end){
  await page.getByRole('button',{name:button,exact:true}).click()
  const area=await page.getByLabel('Редактор зон на кадрі',{exact:true}).boundingBox()
  await page.mouse.move(area.x+area.width*start[0],area.y+area.height*start[1])
  await page.mouse.down();await page.mouse.move(area.x+area.width*end[0],area.y+area.height*end[1],{steps:8});await page.mouse.up()
}
try{
  await page.goto(base+'/analysis');await selectSource()
  // Work on an empty temporary configuration; preserve original above.
  if(originalZones.zones.length)throw new Error('Existing zones require a dedicated source for this check; no edits made')
  await draw('Додати зону спостереження',[.1,.2],[.8,.85])
  await page.getByLabel('Назва зони',{exact:true}).fill('Перевірка · спостереження')
  await saveZones()
  let body=await(await context.request.get(api+`/api/video-sources/${source.id}/zones`)).json()
  assert.equal(body.zones.length,1)
  for(const [key,value] of Object.entries({x1:.1,y1:.2,x2:.8,y2:.85}))assert.ok(Math.abs(body.zones[0][key]-value)<.003)
  evidence.checks.push('Drawing uses actual image area, not letterboxing')
  await draw('Додати виключення',[.3,.35],[.5,.55])
  await page.getByLabel('Назва зони',{exact:true}).fill('Перевірка · виключення')
  await saveZones()
  let area=await page.getByLabel('Редактор зон на кадрі',{exact:true}).boundingBox()
  await page.mouse.move(area.x+area.width*.2,area.y+area.height*.25)
  await page.mouse.down();await page.mouse.move(area.x+area.width*.23,area.y+area.height*.29,{steps:6});await page.mouse.up()
  await saveZones()
  body=await(await context.request.get(api+`/api/video-sources/${source.id}/zones`)).json()
  let include=body.zones.find(zone=>zone.mode==='include')
  assert.ok(Math.abs(include.x1-.13)<.003&&Math.abs(include.y1-.24)<.003,JSON.stringify(include))
  area=await page.getByLabel('Редактор зон на кадрі',{exact:true}).boundingBox()
  await page.mouse.move(area.x+area.width*include.x2,area.y+area.height*include.y2)
  await page.mouse.down();await page.mouse.move(area.x+area.width*.88,area.y+area.height*.93,{steps:6});await page.mouse.up()
  await saveZones()
  body=await(await context.request.get(api+`/api/video-sources/${source.id}/zones`)).json()
  include=body.zones.find(zone=>zone.mode==='include')
  assert.ok(Math.abs(include.x2-.88)<.003&&Math.abs(include.y2-.93)<.003)
  evidence.checks.push('Pointer move and resize preserve normalized coordinates')
  await page.reload();await selectSource()
  await page.getByRole('button',{name:'Перевірка · виключення · виключення',exact:true}).waitFor()
  evidence.checks.push('Include/exclude zones saved and restored after reload')
  const panel=page.locator('section.panel').filter({has:page.getByRole('heading',{name:'Зони спостереження',exact:true})})
  await panel.screenshot({path:path.join(output,'zones-editor-1366.png')})
  await page.setViewportSize({width:390,height:844})
  await panel.screenshot({path:path.join(output,'zones-editor-390.png')})
  assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth))
  await page.setViewportSize({width:1366,height:1000})
  await page.getByRole('button',{name:'Перевірка · виключення · виключення',exact:true}).click()
  await page.getByRole('button',{name:'Видалити зону',exact:true}).click();await saveZones()
  body=await(await context.request.get(api+`/api/video-sources/${source.id}/zones`)).json()
  assert.equal(body.zones.length,1)
  await page.getByRole('button',{name:'Перевірка · спостереження · спостереження',exact:true}).click()
  await page.getByLabel('x1, %',{exact:true}).fill('15')
  await saveZones()
  body=await(await context.request.get(api+`/api/video-sources/${source.id}/zones`)).json()
  assert.equal(body.zones[0].x1,.15)
  evidence.checks.push('Keyboard coordinate editing and deletion persisted')
  await page.goto(base+'/settings')
  await page.getByLabel('Мінімум різних кадрів',{exact:true}).fill('4')
  const saved=page.waitForResponse(response=>response.url().endsWith('/analysis-defaults')&&response.request().method()==='PUT')
  await page.getByRole('button',{name:'Зберегти налаштування',exact:true}).click();assert.equal((await saved).status(),200)
  await page.reload()
  await page.waitForFunction(()=>[...document.querySelectorAll('input')].some(input=>input.value==='4'))
  assert.equal(await page.getByLabel('Мінімум різних кадрів',{exact:true}).inputValue(),'4')
  evidence.checks.push('Temporal defaults saved and restored after reload')
  await page.goto(base+'/events')
  await page.getByRole('heading',{name:'Подій за цими умовами немає'}).waitFor()
  await page.screenshot({path:path.join(output,'journal-real-empty.png'),fullPage:true})
  evidence.checks.push('Working journal uses real empty API, no invented events')
  assert.deepEqual(errors,[])
  evidence.result='passed'
}catch(error){evidence.result='failed';evidence.failure=String(error.stack||error);throw error}
finally{
  assert.equal((await context.request.put(api+`/api/video-sources/${source.id}/zones`,{data:{zones:originalZones.zones}})).status(),200)
  assert.equal((await context.request.put(api+'/api/analysis-defaults',{data:originalDefaults})).status(),200)
  evidence.original_configuration_restored=true
  await writeFile(path.join(output,'browser-real.json'),JSON.stringify(evidence,null,2))
  await browser.close()
}
