import assert from 'node:assert/strict'
import { spawn } from 'node:child_process'
import { once } from 'node:events'
import { mkdir, writeFile } from 'node:fs/promises'
import net from 'node:net'
import path from 'node:path'
import { createRequire } from 'node:module'
import { fileURLToPath } from 'node:url'

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const require = createRequire(path.join(root, 'frontend', 'package.json'))
const { chromium } = require('playwright-core')
const api = 'http://127.0.0.1:18000'
const ui = 'http://127.0.0.1:15173'
const processes = []
const checks = []
let browser

async function assertFree(port) {
  const server = net.createServer()
  await new Promise((resolve, reject) => {
    server.once('error', reject)
    server.listen(port, '127.0.0.1', resolve)
  })
  await new Promise((resolve) => server.close(resolve))
}

function start(executable, args, extraEnv = {}) {
  const child = spawn(executable, args, {
    cwd: root,
    windowsHide: true,
    env: { ...process.env, ...extraEnv },
    stdio: ['ignore', 'pipe', 'pipe'],
  })
  child.output = ''
  child.stdout.on('data', (data) => { child.output += data })
  child.stderr.on('data', (data) => { child.output += data })
  child.on('error', (error) => { child.output += error.message })
  processes.push(child)
  return child
}

async function ready(url, child) {
  for (let i = 0; i < 100; i++) {
    if (child.exitCode !== null) throw new Error(child.output)
    try {
      if ((await fetch(url, { signal: AbortSignal.timeout(1000) })).ok) return
    } catch { /* Очікуємо запуск процесу. */ }
    await new Promise((resolve) => setTimeout(resolve, 200))
  }
  throw new Error(`Не вдалося запустити ${url}: ${child.output}`)
}

async function stop(child) {
  if (child.exitCode !== null || child.signalCode !== null) return
  const closed = once(child, 'close')
  child.kill()
  await closed
}

try {
  await mkdir(path.join(root, '.tmp'), { recursive: true })
  await assertFree(18000)
  await assertFree(15173)
  const backend = start(path.join(root, '.venv-api', 'Scripts', 'python.exe'), [
    '-m', 'uvicorn', 'backend.app.main:app', '--host', '127.0.0.1', '--port', '18000',
  ], { CORS_ORIGINS: ui })
  await ready(`${api}/api/health`, backend)
  const response = await fetch(`${api}/api/health`, { headers: { Origin: ui } })
  assert.deepEqual(await response.json(), { status: 'ok', service: 'api' })
  assert.equal(response.headers.get('access-control-allow-origin'), ui)
  const denied = await fetch(`${api}/api/health`, { headers: { Origin: 'http://untrusted.invalid' } })
  assert.equal(denied.headers.get('access-control-allow-origin'), null)
  checks.push('GET /api/health: HTTP 200, точне тіло; CORS дозволяє налаштоване джерело й відхиляє стороннє')

  const frontend = start(process.execPath, [
    'frontend/node_modules/vite/bin/vite.js', 'frontend',
    '--host', '127.0.0.1', '--port', '15173', '--strictPort',
  ], { VITE_API_BASE_URL: api })
  await ready(ui, frontend)
  browser = await chromium.launch({ channel: 'msedge', headless: true, args: ['--disable-gpu', '--disable-accelerated-video-decode'] })
  const page = await browser.newPage()
  const errors = []
  page.on('pageerror', (error) => errors.push(error.message))
  await page.route('**/api/health', async (route) => {
    await new Promise((resolve) => setTimeout(resolve, 600))
    await route.continue()
  })
  await page.goto(ui)
  await page.locator('[data-state="waiting"]').waitFor()
  checks.push('Браузер: стан очікування')
  await page.locator('[data-state="connected"]').waitFor()
  assert.equal(await page.locator('[data-state="connected"]').innerText(), 'Сервер підключено')
  checks.push('Браузер: отримано реальну відповідь API та показано підключення')
  await page.unroute('**/api/health')
  await stop(backend)
  await page.locator('[data-state="error"]').waitFor({ timeout: 12000 })
  assert.equal(await page.locator('[data-state="error"]').innerText(), 'Сервер недоступний')
  checks.push('Браузер: після зупинення сервера показано помилку без перезавантаження сторінки')
  assert.deepEqual(errors, [])
  await writeFile(path.join(root, '.tmp', 'smoke-results.json'), JSON.stringify({
    checkedAt: new Date().toISOString(), browser: await browser.version(), checks,
  }, null, 2))
  console.log(checks.join('\n'))
} finally {
  if (browser) await browser.close()
  for (const child of processes.reverse()) await stop(child)
}
