// Frontend-only checks. No DB fixtures, worker, training or GPU usage.
import assert from 'node:assert/strict'
import { createRequire } from 'node:module'
import { mkdir, readFile, readdir, writeFile } from 'node:fs/promises'
import path from 'node:path'
const require = createRequire(path.resolve('frontend/package.json'))
const { chromium } = require('playwright-core')
const base = 'http://127.0.0.1:5173'
const output = path.resolve('reports/interface')
await mkdir(output, { recursive: true })
const routes = ['/sources', '/analysis', '/monitoring', '/events', '/experiments', '/settings']
const contractsOnly = process.argv.includes('--contracts-only')
const report = contractsOnly ? JSON.parse(await readFile(path.join(output, 'checks.json'), 'utf8')) : { checked_at: new Date().toISOString(), browser_zoom: 1, gpu_disabled: true, live: [], mocked_frontend_contracts: [], errors: [] }
if (contractsOnly) { assert.equal(report.result, 'passed'); report.contracts_updated_at = new Date().toISOString(); report.mocked_frontend_contracts = [] }
const browser = await chromium.launch({ channel: 'msedge', headless: true, args: ['--disable-gpu', '--disable-accelerated-video-decode'] })
function observe(page, errors) {
  page.on('pageerror', error => errors.push(error.message))
  page.on('console', message => { if (message.type() === 'error') errors.push(message.text()) })
}
async function ready(page, route) {
  await page.goto(base + route)
  await page.locator('h1').waitFor()
  await page.locator('[data-state="connected"]').waitFor()
  await page.waitForTimeout(350)
}
async function geometry(page, width) {
  return await page.evaluate(width => {
    const content = document.querySelector('.page-container').getBoundingClientRect()
    const sidebar = document.querySelector('.sidebar')
    return { viewport: width, root_width: document.querySelector('#root').getBoundingClientRect().width, scroll_width: document.documentElement.scrollWidth, content_width: content.width, header_height: document.querySelector('.app-header').getBoundingClientRect().height, sidebar_width: getComputedStyle(sidebar).display === 'none' ? 0 : sidebar.getBoundingClientRect().width, font_size: getComputedStyle(document.documentElement).fontSize, heading_size: getComputedStyle(document.querySelector('h1')).fontSize, zoom: getComputedStyle(document.body).zoom, device_pixel_ratio: devicePixelRatio }
  }, width)
}
try {
  if (!contractsOnly) {
  for (const [width, height] of [[1920, 1080], [1366, 768], [390, 844]]) {
    const context = await browser.newContext({ viewport: { width, height }, deviceScaleFactor: 1 })
    const page = await context.newPage()
    const errors = []; observe(page, errors)
    for (const route of routes) {
      await ready(page, route)
      const layout = await geometry(page, width)
      assert.ok(layout.scroll_width <= width + 1, `${route} ${width}: document overflow ${layout.scroll_width}`)
      assert.equal(layout.header_height, 64)
      assert.equal(layout.sidebar_width, width >= 1000 ? 240 : 0)
      assert.equal(layout.font_size, '16px')
      assert.ok(layout.content_width > (width === 1920 ? 1500 : width === 1366 ? 1000 : 340), `${route}: narrow content`)
      assert.equal(await page.locator('h1').count(), 1)
      const activeSelector = width >= 1000 ? '.sidebar [aria-current="page"]' : '.mobile-drawer [aria-current="page"]'
      assert.equal(await page.locator(activeSelector).getAttribute('href'), route)
      await page.reload()
      await page.locator('h1').waitFor()
      assert.equal(new URL(page.url()).pathname, route)
      report.live.push({ route, width, height, ...layout, refresh: true })
      if (['/sources', '/analysis', '/monitoring'].includes(route)) {
        await page.waitForTimeout(350)
        await page.screenshot({ path: path.join(output, `${route.slice(1)}-${width}.png`), fullPage: true })
      }
    }
    if (width < 1000) {
      await page.getByRole('button', { name: 'Відкрити меню', exact: true }).click()
      assert.equal(await page.locator('.mobile-drawer').evaluate(dialog => dialog.open), true)
      await page.locator('.mobile-drawer a[href="/events"]').click()
      await page.waitForURL('**/events')
      assert.equal(await page.locator('.mobile-drawer').evaluate(dialog => dialog.open), false)
      await page.getByRole('button', { name: 'Відкрити меню', exact: true }).click()
      await page.keyboard.press('Escape')
      await page.waitForFunction(() => document.querySelector('.menu-toggle')?.getAttribute('aria-expanded') === 'false')
      assert.equal(await page.getByRole('button', { name: 'Відкрити меню', exact: true }).getAttribute('aria-expanded'), 'false')
    } else {
      await page.locator('.sidebar .nav-item[href="/sources"]').click()
      await page.locator('.sidebar a[href="/analysis"]').click()
      await page.goBack(); await page.waitForURL('**/sources')
      await page.goForward(); await page.waitForURL('**/analysis')
    }
    await page.goto(base + '/events')
    await page.getByRole('heading', { name: 'Події', exact: true }).waitFor()
    // The journal is functional; its populated dialog is checked separately
    // against an isolated DB by events-browser-isolated.mjs, without working writes.
    await page.goto(base + '/sources')
    await page.locator('.skip-link').waitFor({ state: 'attached' })
    await page.keyboard.press('Tab')
    assert.equal(await page.evaluate(() => document.activeElement?.className), 'skip-link')
    await page.keyboard.press('Enter')
    assert.equal(await page.evaluate(() => document.activeElement?.id), 'main-content')
    if (errors.length) report.errors.push(...errors.map(error => `${width}: ${error}`))
    await context.close()
  }
  const context = await browser.newContext({ viewport: { width: 1366, height: 768 } })
  const page = await context.newPage()
  await page.addInitScript(() => { window.__sockets = []; const Native = WebSocket; window.WebSocket = class extends Native { constructor(...args) { super(...args); window.__sockets.push(this) } } })
  await ready(page, '/analysis')
  await page.getByTestId('analysis-connection').filter({ hasText: 'підключено' }).waitFor()
  const initial = await page.evaluate(() => window.__sockets.length)
  await page.evaluate(() => window.__sockets.at(-1).close())
  await page.waitForFunction(initial => window.__sockets.length > initial && window.__sockets.at(-1).readyState === 1, initial)
  assert.equal(await page.getByRole('button', { name: 'Запустити аналіз', exact: true }).isDisabled(), true)
  report.live_websocket_reconnect = true
  await context.close()
  }

  // UI success/error contracts are intercepted only inside this browser context.
  // They never create real sources/models/runs and are not used in screenshots.
  const fixtureContext = await browser.newContext({ viewport: { width: 1366, height: 768 } })
  const fixturePage = await fixtureContext.newPage()
  let material
  for (const entry of await readdir('.tmp', { withFileTypes: true })) {
    if (entry.isDirectory() && entry.name.startsWith('analysis-test-')) {
      try { material = await readFile(path.join('.tmp', entry.name, 'technical-test-not-training.mp4')); break } catch { /* next local test artifact */ }
    }
  }
  assert.ok(material, 'A previous short technical test clip is required; training data is never used')
  const source = { id: '11111111-1111-4111-8111-111111111111', name: 'ТЕСТ UI: не робочі дані', original_filename: 'technical-ui-test.mp4', duration_seconds: '1.2', width: 160, height: 120, file_size_bytes: material.length, sha256: 'a'.repeat(64), fps: '7.5', avg_frame_rate: '15/2', r_frame_rate: '10/1', video_codec: 'h264', container_format: 'mov,mp4', created_at: new Date().toISOString() }
  const model = { id: '22222222-2222-4222-8222-222222222222', name: 'ТЕСТ UI: контракт API, не YOLO', architecture: 'YOLO11n', class_mapping: { 0: 'smoke', 1: 'fire' }, weights_sha256: 'b'.repeat(64), weights_path: 'models/ui-fixture/weights.pt', available: true, unavailable_reason: null }
  let uploaded = false, several = false, run = null, runNumber = 0, cancelCalls = 0, postBody = null, uploadCalls = 0, rejectCreate = true
  const sockets = new Set()
  const snapshot = () => ({ type: 'snapshot', runs: { items: run ? [run] : [], total: run ? 1 : 0, page: 1, page_size: 20 }, selected: run })
  const publish = () => { for (const socket of sockets) socket.send(JSON.stringify(snapshot())) }
  await fixturePage.routeWebSocket('**/api/analysis-runs/ws*', socket => { sockets.add(socket); socket.send(JSON.stringify(snapshot())); socket.onMessage(() => socket.send(JSON.stringify(snapshot()))); socket.onClose(() => sockets.delete(socket)) })
  await fixturePage.route('**/api/**', async route => {
    const request = route.request(), url = new URL(request.url()), endpoint = url.pathname
    const cors = { 'Access-Control-Allow-Origin': base, 'Access-Control-Allow-Methods': 'GET,POST,OPTIONS', 'Access-Control-Allow-Headers': 'Content-Type,Range' }
    if (request.method() === 'OPTIONS') return route.fulfill({ status: 204, headers: cors })
    const json = body => route.fulfill({ status: 200, contentType: 'application/json', headers: cors, body: JSON.stringify(body) })
    if (endpoint === '/api/analysis-defaults') return json({analysis_fps:2,temporal:{window_seconds:3,min_hits:3,min_span_seconds:1,absence_seconds:2,match_iou:.1,center_distance:.12,clip_before_seconds:2,clip_after_seconds:3}})
    if (endpoint.endsWith('/zones')) return json({zones:[],width:source.width,height:source.height})
    if (endpoint === '/api/health') return json({ status: 'ok', service: 'api' })
    if (endpoint === '/api/model-versions') return json({ items: [model], total: 1, page: 1, page_size: 20, gpu_enabled: false, queue_limit: 10 })
    if (endpoint === '/api/video-sources' && request.method() === 'POST') { uploaded = true; uploadCalls++; assert.ok(request.postDataBuffer()?.includes(Buffer.from('technical-ui-test.mp4'))); return route.fulfill({ status: 201, contentType: 'application/json', headers: cors, body: JSON.stringify(source) }) }
    if (endpoint === '/api/video-sources') {
      const current = Number(url.searchParams.get('page') || 1)
      const rows = several ? Array.from({ length: 11 }, (_, index) => ({ ...source, id: `${index}1111111-1111-4111-8111-111111111111`, name: `ТЕСТ UI ${index + 1}` })) : uploaded ? [source] : []
      return json({ items: rows.slice((current - 1) * 10, current * 10), total: rows.length, page: current, page_size: 10, upload_limit_bytes: 1073741824 })
    }
    if (endpoint === `/api/video-sources/${source.id}`) return json(source)
    if (endpoint.endsWith('/content') || endpoint.endsWith('/files/video')) {
      const match = /bytes=(\d+)-(\d*)/.exec(request.headers().range || '')
      if (match) { const start = Number(match[1]), end = match[2] ? Math.min(Number(match[2]), material.length - 1) : material.length - 1; return route.fulfill({ status: 206, contentType: 'video/mp4', headers: { ...cors, 'Accept-Ranges': 'bytes', 'Content-Range': `bytes ${start}-${end}/${material.length}` }, body: material.subarray(start, end + 1) }) }
      return route.fulfill({ status: 200, contentType: 'video/mp4', headers: { ...cors, 'Accept-Ranges': 'bytes' }, body: material })
    }
    if (endpoint === '/api/analysis-runs' && request.method() === 'POST') {
      if (rejectCreate) { rejectCreate = false; return route.fulfill({ status: 409, contentType: 'application/json', headers: cors, body: JSON.stringify({ detail: 'Файл зареєстрованої моделі недоступний.' }) }) }
      postBody = request.postDataJSON(); runNumber++
      run = { id: `33333333-3333-4333-8333-${String(runNumber).padStart(12, '0')}`, video_source_id: source.id, model_version_id: model.id, video_source_name: source.name, model_version_name: model.name, created_at: new Date().toISOString(), status: 'pending', progress: 0, cancel_requested_at: null, settings_snapshot: { ...postBody.settings, model_sha256: model.weights_sha256 }, summary_metrics: null, error_message: null, result_paths: null }
      return route.fulfill({ status: 201, contentType: 'application/json', headers: cors, body: JSON.stringify(run) })
    }
    if (endpoint === '/api/analysis-runs') return json(snapshot().runs)
    if (endpoint.endsWith('/cancel')) { cancelCalls++; run.cancel_requested_at = new Date().toISOString(); return json(run) }
    if (endpoint.endsWith('/files/detections')) return route.fulfill({ status: 200, contentType: 'application/x-ndjson', body: '{"test_only":true,"detections":[]}\n' })
    if (endpoint.endsWith('/files/summary')) return json({ test_only: true })
    if (run && endpoint === `/api/analysis-runs/${run.id}`) return json(run)
    return route.fulfill({ status: 404, contentType: 'application/json', body: '{"detail":"Тестовий маршрут не знайдено"}' })
  })
  await fixturePage.goto(base + '/sources')
  await fixturePage.getByLabel('Назва джерела', { exact: true }).fill(source.name)
  await fixturePage.locator('#video-file').setInputFiles({ name: 'technical-ui-test.mp4', mimeType: 'video/mp4', buffer: material })
  await fixturePage.getByRole('button', { name: 'Завантажити відео', exact: true }).click()
  await fixturePage.getByText('Відеоджерело збережено.', { exact: true }).waitFor()
  await fixturePage.locator('video').waitFor()
  await fixturePage.waitForFunction(() => document.querySelector('video')?.readyState >= 1)
  assert.equal(await fixturePage.locator('nav[aria-label="Сторінки списку"]').count(), 0)
  await fixturePage.locator('video').evaluate(async video => { await new Promise(resolve => { video.addEventListener('seeked', resolve, { once: true }); video.currentTime = .5 }) })
  await fixturePage.locator('video').evaluate(video => { Object.defineProperty(video, 'error', { configurable: true, value: { code: 4 } }); video.dispatchEvent(new Event('error')) })
  await fixturePage.getByText(/Браузер не підтримує контейнер або кодек/).waitFor()
  await fixturePage.getByLabel('Назва джерела', { exact: true }).fill('ТЕСТ UI: перевищений ліміт')
  await fixturePage.locator('#video-file').setInputFiles({ name: 'technical-ui-test.mp4', mimeType: 'video/mp4', buffer: material })
  await fixturePage.locator('#video-file').evaluate(input => Object.defineProperty(input.files[0], 'size', { value: 1073741825 }))
  await fixturePage.getByRole('button', { name: 'Завантажити відео', exact: true }).click()
  await fixturePage.getByText(/Файл перевищує ліміт/).waitFor()
  assert.equal(uploadCalls, 1)
  several = true
  await fixturePage.getByRole('button', { name: 'Оновити', exact: true }).click()
  await fixturePage.getByRole('navigation', { name: 'Сторінки списку' }).waitFor()
  await fixturePage.getByRole('button', { name: 'Далі', exact: true }).click()
  await fixturePage.getByText('Сторінка 2 з 2', { exact: true }).waitFor()
  several = false
  await fixturePage.locator('.sidebar a[href="/analysis"]').click()
  await fixturePage.getByLabel('Відеоджерело', { exact: true }).selectOption(source.id)
  await fixturePage.getByLabel('Версія моделі', { exact: true }).selectOption(model.id)
  await fixturePage.getByLabel('Поріг smoke', { exact: true }).fill('0.65')
  await fixturePage.getByLabel('Поріг fire', { exact: true }).fill('0.45')
  await fixturePage.getByRole('button', { name: 'Запустити аналіз', exact: true }).click()
  await fixturePage.getByText('Файл зареєстрованої моделі недоступний.', { exact: true }).waitFor()
  assert.equal(run, null)
  await fixturePage.getByRole('button', { name: 'Запустити аналіз', exact: true }).click()
  await fixturePage.getByRole('article', { name: 'Деталі аналізу' }).waitFor()
  assert.equal(postBody.settings.smoke_threshold, .65); assert.equal(postBody.settings.fire_threshold, .45); assert.equal(postBody.settings.device, 'cpu')
  run.status = 'running'; run.progress = .38; run.summary_metrics = { stage: 'processing', frames_read: 3, frames_analyzed: 1 }; publish()
  await fixturePage.getByText('38.0%', { exact: true }).first().waitFor()
  await fixturePage.getByRole('button', { name: 'Скасувати аналіз', exact: true }).click()
  await fixturePage.getByText('Скасування запитано. Worker ще не підтвердив зупинку.', { exact: true }).waitFor()
  assert.equal(run.status, 'running')
  run.status = 'stopped'; publish()
  await fixturePage.getByText('Оброблення припинено. Часткові результати недоступні.', { exact: true }).waitFor()
  await fixturePage.getByRole('button', { name: 'Запустити аналіз', exact: true }).click()
  await fixturePage.waitForTimeout(200)
  run.status = 'completed'; run.progress = 1; run.result_paths = { video: 'test-only/annotated.mp4', detections: 'test-only/detections.jsonl', summary: 'test-only/summary.json' }; run.summary_metrics = { stage: 'completed', frames_read: 9, frames_analyzed: 3, wall_seconds: 1 }; publish()
  await fixturePage.getByRole('link', { name: 'Виявлення JSONL', exact: true }).waitFor()
  await fixturePage.waitForFunction(() => document.querySelector('video')?.readyState >= 1)
  await fixturePage.reload()
  await fixturePage.getByRole('link', { name: 'Виявлення JSONL', exact: true }).waitFor()
  assert.equal(cancelCalls, 1, 'Reload/navigation must not cancel worker jobs')
  report.mocked_frontend_contracts.push('upload multipart + 201 feedback + metadata/player/seek', 'size limit rejected before upload + unsupported codec message', 'conditional pagination', 'analysis parameters + rejected create without phantom run + successful create', 'WebSocket progress + request/ack cancellation', 'completed results + download links + reload restoration; no implicit cancel')
  await fixtureContext.close()
  assert.deepEqual(report.errors, [])
  report.result = 'passed'
} catch (error) {
  report.result = 'failed'; report.failure = error.stack
  throw error
} finally {
  await writeFile(path.join(output, 'checks.json'), JSON.stringify(report, null, 2))
  await browser.close()
}
console.log(contractsOnly ? 'Frontend UI contracts including expected errors passed; previously successful live layout checks were not repeated.' : 'Frontend design: six routes × three viewports, keyboard/navigation, live WS reconnect, UI contracts passed; no GPU/backend writes.')
