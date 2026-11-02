// Read-only playback checks for the completed real integration run.
import assert from 'node:assert/strict'
import {createRequire} from 'node:module'
import {readFile,writeFile} from 'node:fs/promises'
import path from 'node:path'
const require=createRequire(path.resolve('frontend/package.json'))
const {chromium}=require('playwright-core')
const folder=path.resolve('reports/ml/final-verification-20261102/application')
const checked=JSON.parse(await readFile(path.join(folder,'browser-check.json'),'utf8'))
assert.equal(checked.result,'passed')
const browser=await chromium.launch({channel:'msedge',headless:true,args:['--disable-gpu','--disable-accelerated-video-decode']})
try{
  const page=await browser.newPage({viewport:{width:1600,height:1000}})
  const errors=[]
  page.on('pageerror',error=>errors.push(error.message))
  await page.addInitScript(id=>localStorage.setItem('firevision-analysis-id',id),checked.run_id)
  await page.goto('http://127.0.0.1:5173/analysis')
  const player=page.getByLabel('Відео результату аналізу',{exact:true})
  await player.waitFor()
  await page.waitForFunction(()=>document.querySelector('video')?.readyState>=2)
  const seeks=[]
  for(const time of [8.02,12.02]){
    await player.evaluate(async(video,target)=>{
      await new Promise(resolve=>{video.addEventListener('seeked',resolve,{once:true});video.currentTime=target})
    },time)
    const actual=await player.evaluate(video=>video.currentTime)
    assert.ok(Math.abs(actual-time)<.02)
    seeks.push({requested:time,actual})
    await page.waitForTimeout(300) // Let the decoded seek frame and native controls paint.
    await player.screenshot({path:path.join(folder,`video-at-${time}s.png`)})
  }
  const before=await player.evaluate(async video=>{video.muted=true;const time=video.currentTime;await video.play();return time})
  await page.waitForTimeout(650)
  const after=await player.evaluate(video=>{video.pause();return {time:video.currentTime,error:video.error?.message||null}})
  assert.equal(after.error,null)
  assert.ok(after.time>before+.2)
  assert.deepEqual(errors,[])
  const evidence={result:'passed',run_id:checked.run_id,seeks,playback_before:before,playback_after:after.time,page_errors:errors,browser_gpu_disabled:true}
  await writeFile(path.join(folder,'playback-check.json'),JSON.stringify(evidence,null,2))
  console.log(JSON.stringify(evidence))
}finally{await browser.close()}
