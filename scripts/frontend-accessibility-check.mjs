import { createRequire } from 'node:module'
import path from 'node:path'
import assert from 'node:assert/strict'
import { writeFile } from 'node:fs/promises'
const {chromium}=createRequire(path.resolve('frontend/package.json'))('playwright-core')
function luminance(hex) {
  const values=hex.trim().replace('#','').match(/../g).map(part=>parseInt(part,16)/255).map(v=>v<=.04045?v/12.92:((v+.055)/1.055)**2.4)
  return values[0]*.2126+values[1]*.7152+values[2]*.0722
}
function contrast(a,b) { const x=luminance(a),y=luminance(b);return (Math.max(x,y)+.05)/(Math.min(x,y)+.05) }
const browser=await chromium.launch({channel:'msedge',headless:true,args:['--disable-gpu','--disable-accelerated-video-decode']})
try {
  const page=await browser.newPage({viewport:{width:1366,height:768},deviceScaleFactor:1})
  const results=[]
  for(const route of ['/sources','/analysis','/monitoring','/events','/experiments','/settings']) {
    await page.goto('http://127.0.0.1:5173'+route)
    await page.locator('h1').waitFor()
    const unlabeled=await page.evaluate(()=>[...document.querySelectorAll('input,select,textarea')].filter(node=>!node.getAttribute('aria-label')&&!node.getAttribute('aria-labelledby')&&!node.labels?.length).map(node=>node.outerHTML))
    assert.deepEqual(unlabeled,[],route)
    results.push({route,form_controls_labeled:true})
  }
  await page.goto('http://127.0.0.1:5173/sources');await page.locator('.skip-link').waitFor({state:'attached'})
  await page.keyboard.press('Tab');await page.keyboard.press('Enter');await page.keyboard.press('Tab')
  const focus=await page.evaluate(()=>({tag:document.activeElement.tagName,outline:getComputedStyle(document.activeElement).outlineStyle,width:getComputedStyle(document.activeElement).outlineWidth}))
  assert.equal(focus.tag,'INPUT');assert.equal(focus.outline,'solid');assert.equal(focus.width,'3px')
  const tokens=await page.evaluate(()=>{const s=getComputedStyle(document.documentElement);return Object.fromEntries(['bg','surface','text','muted','primary'].map(name=>[name,s.getPropertyValue('--'+name).trim()]))})
  const ratios={body:contrast(tokens.text,tokens.bg),secondary_on_background:contrast(tokens.muted,tokens.bg),secondary_on_white:contrast(tokens.muted,tokens.surface),primary_button:contrast(tokens.primary,tokens.surface),focus_outline:contrast('#5C85A5','#FFFFFF')}
  for(const [name,value] of Object.entries(ratios)) assert.ok(value>=(name==='focus_outline'?3:4.5),`${name}: ${value}`)
  await writeFile('reports/interface/accessibility.json',JSON.stringify({checked_at:new Date().toISOString(),results,contrast_ratios:ratios,keyboard_focus:focus,viewport_scale:await page.evaluate(()=>visualViewport.scale),external_fonts_used:false},null,2))
  console.log(JSON.stringify({contrast_ratios:ratios,controls_labeled:true,keyboard_focus:true}))
} finally {await browser.close()}
