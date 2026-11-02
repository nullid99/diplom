// Actual API/DB/evidence in a temporary test environment; never working data or YOLO claims.
import assert from 'node:assert/strict'
import {createRequire} from 'node:module'
import {spawn} from 'node:child_process'
import {writeFile} from 'node:fs/promises'
import path from 'node:path'
const {chromium}=createRequire(path.resolve('frontend/package.json'))('playwright-core')
const [api,port]=process.argv.slice(2),base=`http://127.0.0.1:${port}`,folder=path.resolve('reports/events')
const frontend=spawn(process.execPath,['frontend/node_modules/vite/bin/vite.js','frontend','--host','127.0.0.1','--port',port,'--strictPort'],{windowsHide:true,env:{...process.env,VITE_API_BASE_URL:api},stdio:'ignore'})
const browser=await chromium.launch({channel:'msedge',headless:true,args:['--disable-gpu','--disable-accelerated-video-decode']})
let page
const errors=[]
const requests=[]
try{
  page=await browser.newPage({viewport:{width:1366,height:1000}})
  page.setDefaultTimeout(10000)
  page.on('response',response=>{if(response.url().includes('/api/events'))requests.push({url:response.url(),status:response.status()})})
  page.on('pageerror',error=>errors.push(error.message));page.on('console',message=>{if(message.type()==='error')errors.push(message.text())})
  await page.addInitScript(()=>document.addEventListener('DOMContentLoaded',()=>{
    const label=document.createElement('aside');label.textContent='ІЗОЛЬОВАНИЙ ТЕСТ · fixture-детектор, не YOLO · не робочі події';label.style.cssText='position:fixed;bottom:0;left:0;right:0;padding:8px;background:#fff3cd;color:#664d03;z-index:9999;text-align:center;font:14px Segoe UI';document.body.append(label)
  }))
  for(let attempt=0;attempt<80;attempt++){try{await page.goto(base+'/events');break}catch{await new Promise(resolve=>setTimeout(resolve,100))}}
  const row=page.locator('tbody .source-title').first()
  await row.waitFor()
  await page.screenshot({path:path.join(folder,'journal-isolated-TEST-ONLY.png'),fullPage:true})
  await row.click()
  const dialog=page.getByRole('dialog')
  await dialog.getByRole('heading',{name:/Картка події/}).waitFor()
  await page.waitForFunction(()=>document.querySelector('dialog img')?.complete&&document.querySelector('dialog video')?.readyState>=2)
  await dialog.getByRole('combobox',{name:/^Оцінка оператора/}).selectOption('false_positive')
  await dialog.getByLabel('Коментар оператора',{exact:true}).fill('Ізольована перевірка: fixture-детектор, не результат YOLO.')
  await dialog.getByRole('button',{name:'Зберегти оцінку',exact:true}).click()
  await dialog.getByText('Оцінку й коментар збережено.',{exact:true}).waitFor()
  await dialog.evaluate(element=>{
    const label=document.createElement('p');label.textContent='ІЗОЛЬОВАНИЙ ТЕСТ · fixture-детектор, не YOLO · не робочі події';label.style.cssText='padding:10px;background:#fff3cd;color:#664d03;border-radius:6px;font-size:14px';element.prepend(label);element.scrollTop=0
  })
  await dialog.screenshot({path:path.join(folder,'event-card-isolated-TEST-ONLY.png')})
  const saved=(await(await page.request.get(api+'/api/events')).json()).items[0]
  assert.equal(saved.review_status,'false_positive')
  const clip=dialog.getByLabel('Фрагмент події',{exact:true})
  const duration=await clip.evaluate(video=>video.duration)
  assert.ok(duration>0)
  await page.keyboard.press('Escape')
  await page.reload();await page.locator('tbody .source-title').first().click()
  await dialog.getByLabel('Коментар оператора',{exact:true}).waitFor()
  assert.match(await dialog.getByLabel('Коментар оператора',{exact:true}).inputValue(),/fixture-детектор/)
  assert.equal(await dialog.getByRole('combobox',{name:/^Оцінка оператора/}).inputValue(),'false_positive')
  await page.keyboard.press('Escape')
  await page.getByRole('combobox',{name:/^Тип ознак/}).selectOption('fire');await page.getByRole('button',{name:'Застосувати',exact:true}).click()
  await page.getByRole('heading',{name:'Подій за цими умовами немає'}).waitFor()
  await page.getByRole('combobox',{name:/^Тип ознак/}).selectOption('smoke');await page.getByRole('combobox',{name:/^Оцінка оператора/}).selectOption('false_positive')
  await page.getByRole('button',{name:'Застосувати',exact:true}).click();await page.locator('tbody .source-title').first().waitFor()
  await page.setViewportSize({width:390,height:844})
  assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth))
  await page.locator('tbody .source-title').first().click();await dialog.getByLabel('Коментар оператора',{exact:true}).waitFor()
  await dialog.screenshot({path:path.join(folder,'event-card-390-TEST-ONLY.png')})
  assert.ok(await page.evaluate(()=>document.querySelector('dialog').scrollWidth<=document.querySelector('dialog').clientWidth))
  assert.deepEqual(errors,[])
  await writeFile(path.join(folder,'browser-isolated.json'),JSON.stringify({result:'passed',isolated:true,real_yolo:false,fixture_detector:true,review_reload:true,filters:true,evidence_files:true,escape:true,mobile_no_overflow:true,errors},null,2))
}catch(error){
  if(page){await page.screenshot({path:path.join(folder,'isolated-failure.png'),fullPage:true});await writeFile(path.join(folder,'isolated-failure.json'),JSON.stringify({error:String(error.stack),errors,requests,text:await page.locator('body').innerText()},null,2))}
  throw error
}finally{await browser.close();frontend.kill();await new Promise(resolve=>frontend.once('exit',resolve))}
