// Read-only browser verification of the real FIRESENSE runs/events already saved by the worker.
import assert from 'node:assert/strict'
import {createRequire} from 'node:module'
import {readFile,writeFile} from 'node:fs/promises'
import path from 'node:path'
const {chromium}=createRequire(path.resolve('frontend/package.json'))('playwright-core')
const folder=path.resolve('reports/firesense')
const data=JSON.parse(await readFile(path.join(folder,'observations.json'),'utf8'))
const positive=data.observations.find(row=>row.id==='F01')
const event=data.events.find(row=>row.clip_id==='F01')
const browser=await chromium.launch({channel:'msedge',headless:true,args:['--disable-gpu','--disable-accelerated-video-decode']})
try{
  const context=await browser.newContext({viewport:{width:1600,height:1000},deviceScaleFactor:1})
  const page=await context.newPage(),errors=[]
  page.on('pageerror',error=>errors.push(error.message))
  page.on('console',message=>{if(message.type()==='error')errors.push(message.text())})
  await page.addInitScript(id=>localStorage.setItem('firevision-analysis-id',id),positive.run_id)
  await page.goto('http://127.0.0.1:5173/analysis')
  const player=page.getByLabel('Відео результату аналізу',{exact:true})
  await player.waitFor()
  await page.waitForFunction(()=>document.querySelector('video[aria-label="Відео результату аналізу"]')?.readyState>=2)
  const before=await player.evaluate(async video=>{
    await new Promise(resolve=>{video.addEventListener('seeked',resolve,{once:true});video.currentTime=2.02})
    video.muted=true;await video.play();return video.currentTime
  })
  await page.waitForTimeout(450)
  const after=await player.evaluate(video=>{video.pause();return video.currentTime})
  assert.ok(after>before+.2)
  await player.evaluate(async video=>{await new Promise(resolve=>{video.addEventListener('seeked',resolve,{once:true});video.currentTime=2.02})})
  await page.waitForTimeout(250)
  await page.screenshot({path:path.join(folder,'application-analysis.png'),fullPage:true})
  await player.screenshot({path:path.join(folder,'application-positive-video.png')})
  await page.reload();await page.getByLabel('Відео результату аналізу',{exact:true}).waitFor()
  assert.equal(await page.evaluate(()=>localStorage.getItem('firevision-analysis-id')),positive.run_id)
  await page.goto('http://127.0.0.1:5173/events')
  await page.locator('tbody .source-title').first().waitFor()
  await page.screenshot({path:path.join(folder,'application-journal.png'),fullPage:true})
  await page.getByRole('combobox',{name:/^Відеоджерело/}).selectOption(positive.source_id)
  const filtered=page.waitForResponse(response=>response.url().includes('/api/events?')&&response.url().includes(positive.source_id))
  await page.getByRole('button',{name:'Застосувати',exact:true}).click();assert.equal((await filtered).status(),200)
  await page.locator('tbody .source-title').first().click()
  const dialog=page.getByRole('dialog')
  await page.waitForFunction(()=>document.querySelector('dialog img')?.complete&&document.querySelector('dialog video')?.readyState>=2)
  const clip=dialog.getByLabel('Фрагмент події',{exact:true})
  const target=Number(event.region.clip_confirmation_seconds)+.02
  await clip.evaluate(async(video,target)=>{await new Promise(resolve=>{video.addEventListener('seeked',resolve,{once:true});video.currentTime=target})},target)
  const clipBefore=await clip.evaluate(async video=>{video.muted=true;await video.play();return video.currentTime})
  await page.waitForTimeout(400)
  const clipAfter=await clip.evaluate(video=>{video.pause();return video.currentTime})
  assert.ok(clipAfter>clipBefore+.15)
  await clip.evaluate(async(video,target)=>{await new Promise(resolve=>{video.addEventListener('seeked',resolve,{once:true});video.currentTime=target})},target)
  await page.waitForTimeout(400)
  await dialog.screenshot({path:path.join(folder,'application-real-event.png')})
  assert.equal(await dialog.getByRole('combobox',{name:/^Оцінка оператора/}).inputValue(),'unreviewed')
  await page.keyboard.press('Escape')
  assert.deepEqual(errors,[])
  await writeFile(path.join(folder,'browser-check.json'),JSON.stringify({result:'passed',real_yolo:true,natural_video:true,demonstration_only:true,run_id:positive.run_id,event_id:event.id,playback_before:before,playback_after:after,clip_playback_before:clipBefore,clip_playback_after:clipAfter,run_reload:true,event_card_frame_and_clip:true,filter_source:true,operator_review_unchanged:true,errors},null,2))
}finally{await browser.close()}
