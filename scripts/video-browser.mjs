import assert from 'node:assert/strict'
import { spawn } from 'node:child_process'
import { createRequire } from 'node:module'
import { once } from 'node:events'
import path from 'node:path'

const require = createRequire(path.resolve('frontend/package.json'))
const { chromium } = require('playwright-core')
const [api, uiPort, sample] = process.argv.slice(2)
const ui = `http://127.0.0.1:${uiPort}`
const frontend = spawn(process.execPath, [
  'frontend/node_modules/vite/bin/vite.js', 'frontend', '--host', '127.0.0.1', '--port', uiPort, '--strictPort',
], { windowsHide: true, env: { ...process.env, VITE_API_BASE_URL: api }, stdio: 'ignore' })
let browser
try {
  for (let attempt = 0; attempt < 100; attempt++) {
    try { if ((await fetch(ui)).ok) break } catch { /* Очікуємо Vite. */ }
    if (frontend.exitCode !== null) throw new Error('Vite не запустився.')
    await new Promise((resolve) => setTimeout(resolve, 100))
  }
  browser = await chromium.launch({ channel: 'msedge', headless: true, args: ['--disable-gpu', '--disable-accelerated-video-decode'] })
  const page = await browser.newPage()
  await page.goto(ui)
  await page.getByLabel('Назва джерела', { exact: true }).fill('Тестовий технічний ролик — не навчальні дані')
  await page.getByLabel('Відеофайл', { exact: true }).setInputFiles(sample)
  await page.getByRole('button', { name: 'Завантажити відео', exact: true }).click()
  await page.getByText('Відеоджерело збережено.', { exact: true }).waitFor({ timeout: 30000 })
  await page.waitForFunction(() => document.querySelector('video')?.readyState >= 1)
  await page.locator('video').evaluate(async (video) => {
    await new Promise((resolve, reject) => {
      const timeout = setTimeout(() => reject(new Error('Перемотування не завершено.')), 10000)
      video.addEventListener('seeked', () => { clearTimeout(timeout); resolve() }, { once: true })
      video.currentTime = 2
    })
  })
  assert.ok(await page.locator('video').evaluate((video) => Math.abs(video.currentTime - 2) < 0.2))
  await page.reload()
  await page.getByRole('button', { name: 'Тестовий технічний ролик — не навчальні дані', exact: true }).waitFor()
  await page.getByRole('button', { name: 'Тестовий технічний ролик — не навчальні дані', exact: true }).click()
  await page.waitForFunction(() => document.querySelector('video')?.readyState >= 1)
  await page.locator('video').evaluate((video) => {
    Object.defineProperty(video, 'error', { configurable: true, value: { code: 4 } })
    video.dispatchEvent(new Event('error'))
  })
  await page.getByText(/Браузер не підтримує контейнер або кодек/).waitFor()
  await page.screenshot({ path: path.join(path.dirname(sample), 'video-sources.png'), fullPage: true })
  console.log('Браузер: завантаження, список після reload, метадані плеєра, перемотування й повідомлення про непідтримуваний кодек — успішно.')
} finally {
  if (browser) await browser.close()
  if (frontend.exitCode === null && frontend.signalCode === null) {
    const closed = once(frontend, 'close')
    frontend.kill()
    await closed
  }
}
