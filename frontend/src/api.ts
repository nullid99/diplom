import { useEffect, useState } from 'react'
export const apiBase = import.meta.env.VITE_API_BASE_URL?.trim().replace(/\/$/, '')
export const analysisDefaults = { smoke: .25, fire: .25, imgsz: 640, fps: 2, device: 'cpu' }
export type Page<T> = { items: T[]; total: number; page: number; page_size: number; gpu_enabled?: boolean; queue_limit?: number; upload_limit_bytes?: number }
export type SourceOption = { id: string; name: string }
export type ModelVersion = { id: string; name: string; architecture: string; class_mapping: Record<string, string>; weights_sha256: string; weights_path: string; created_at: string; available: boolean; unavailable_reason: string | null }
export function useRemotePage<T>(resource: string) {
  const [data, setData] = useState<Page<T> | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [revision, setRevision] = useState(0)
  useEffect(() => {
    const controller = new AbortController()
    let disposed = false
    const timeout = setTimeout(() => controller.abort(), 8000)
    setLoading(true); setError('')
    async function load() {
      try {
        if (!apiBase) throw new Error('Адресу API не налаштовано.')
        const response = await fetch(`${apiBase}${resource}`, { signal: controller.signal, cache: 'no-store' })
        if (!response.ok) throw new Error('Не вдалося отримати дані сервера. Перевірте API та БД.')
        const body = await response.json()
        if (!disposed) setData(body)
      } catch (reason) { if (!disposed) setError(reason instanceof Error && reason.name !== 'AbortError' ? reason.message : 'Сервер не відповів вчасно. Спробуйте оновити дані.') }
      finally { clearTimeout(timeout); if (!disposed) setLoading(false) }
    }
    void load()
    return () => { disposed = true; clearTimeout(timeout); controller.abort() }
  }, [resource, revision])
  return { data, loading, error, refresh: () => setRevision(value => value + 1) }
}
