// Test-only API and storage. Browser GPU acceleration is explicitly disabled.
import assert from 'node:assert/strict'
import { spawn } from 'node:child_process'
import { createRequire } from 'node:module'
import path from 'node:path'
const require = createRequire(path.resolve('frontend/package.json'))
const { chromium } = require('playwright-core')
const [api, port, mode, screenshot] = process.argv.slice(2)
const frontend = spawn(process.execPath, ['frontend/node_modules/vite/bin/vite.js', 'frontend', '--host', '127.0.0.1', '--port', port, '--strictPort'], { windowsHide: true, env: { ...process.env, VITE_API_BASE_URL: api }, stdio: 'ignore' })
let browser
try {
  browser = await chromium.launch({ channel: 'msedge', headless: true, args: ['--disable-gpu', '--disable-accelerated-video-decode'] })
  const page = await browser.newPage()
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  await page.addInitScript(() => {
    window.__analysisSockets = []
    const Native = window.WebSocket
    window.WebSocket = class extends Native {
      constructor(...args) { super(...args); window.__analysisSockets.push(this) }
    }
  })
  for (let retry = 0; retry < 70; retry++) {
    try { await page.goto(`http://127.0.0.1:${port}`); break } catch { await new Promise(resolve => setTimeout(resolve, 150)) }
  }
  const openAnalysis = () => page.getByRole('link', { name: 'Аналіз відео', exact: true }).click()
  await openAnalysis()
  await page.getByTestId('analysis-connection').filter({ hasText: 'підключено' }).waitFor()
  if (mode === 'empty') {
    await page.getByTestId('no-model').waitFor()
    assert.equal(await page.getByRole('button', { name: 'Запустити аналіз', exact: true }).isDisabled(), true)
    const initial = await page.evaluate(() => window.__analysisSockets.length)
    await page.evaluate(() => window.__analysisSockets.at(-1).close())
    await page.waitForFunction(value => window.__analysisSockets.length > value && window.__analysisSockets.at(-1).readyState === 1, initial)
    await page.getByTestId('analysis-connection').filter({ hasText: 'підключено' }).waitFor()
    const seeded = await (await page.request.post(`${api}/test/model`)).json()
    await page.getByRole('button', { name: 'Оновити дані', exact: true }).click()
    await page.getByLabel('Версія моделі', { exact: true }).selectOption(seeded.id)
    await page.getByLabel('Відеоджерело', { exact: true }).selectOption({ index: 1 })
    await page.getByRole('button', { name: 'Запустити аналіз', exact: true }).click()
    await page.getByRole('article', { name: 'Деталі аналізу' }).getByRole('heading', { name: 'Очікування', exact: true }).waitFor()
    const selected = await page.evaluate(() => localStorage.getItem('firevision-analysis-id'))
    await page.reload(); await openAnalysis()
    await page.getByRole('article', { name: 'Деталі аналізу' }).getByRole('heading', { name: 'Очікування', exact: true }).waitFor()
    assert.equal((await (await page.request.get(`${api}/api/analysis-runs/${selected}`)).json()).status, 'pending')
    await page.getByRole('button', { name: 'Скасувати аналіз', exact: true }).click()
    await page.getByRole('article', { name: 'Деталі аналізу' }).getByRole('heading', { name: 'Скасовано', exact: true }).waitFor()
  } else {
    await page.locator('.source-list .source-title').first().click()
    const detail = page.getByRole('article', { name: 'Деталі аналізу' })
    await detail.getByRole('heading', { name: 'Завершено', exact: true }).waitFor()
    const video = page.locator('video[aria-label="Відео результату аналізу"]')
    await page.waitForFunction(() => document.querySelector('video')?.readyState >= 1)
    await video.evaluate(async element => {
      await new Promise((resolve, reject) => {
        const timer = setTimeout(() => reject(new Error('seek timeout')), 10000)
        element.addEventListener('seeked', () => { clearTimeout(timer); resolve() }, { once: true })
        element.currentTime = .5
      })
    })
    const source = await video.getAttribute('src')
    const range = await page.request.get(source, { headers: { Range: 'bytes=0-31' } })
    assert.equal(range.status(), 206)
    const output = await page.request.get(await page.getByRole('link', { name: 'Виявлення JSONL' }).getAttribute('href'))
    assert.equal(output.status(), 200)
    assert.match(output.headers()['content-disposition'], /attachment/)
    assert.equal((await output.text()).trim().split('\n').length, 9)
  }
  await page.getByText('Завантажуємо джерела та моделі…', { exact: true }).waitFor({ state: 'hidden' })
  if (screenshot) await page.screenshot({ path: screenshot, fullPage: true })
  assert.deepEqual(errors, [])
  console.log(`Analysis browser ${mode}: passed (CPU renderer, isolated fixtures)`)
} finally {
  await browser?.close()
  frontend.kill()
}
