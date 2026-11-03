import { err, apiInput } from './ui.js'

export const defaultApi = () => /^https?:$/.test(location.protocol)
  ? `${location.protocol}//${location.hostname}:8000`
  : 'http://127.0.0.1:8000'

export const base = () => (apiInput.value.trim() || defaultApi()).replace(/\/$/, '')

export async function api(path, method = 'GET', body) {
  err.value = ''
  try {
    const r = await fetch(base() + path, {
      method,
      headers: body ? {'Content-Type': 'application/json'} : {},
      body: body ? JSON.stringify(body) : undefined,
    })
    if (!r.ok) {
      const j = await r.json().catch(() => ({}))
      throw new Error(typeof j.detail === 'string' ? j.detail : (j.detail ? JSON.stringify(j.detail) : r.statusText))
    }
    return await r.json()
  } catch (e) {
    err.value = 'Ошибка: ' + e.message
    throw e
  }
}
