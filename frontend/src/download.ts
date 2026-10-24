import { authHeaders } from './auth'

// Strip any path component so a server value can't suggest a directory.
const sanitize = (name: string) => name.split(/[\\/]/).pop() ?? ''

/** Extract the filename from a Content-Disposition header; `fallback` when absent or unusable. */
export function filenameFromDisposition(header: string | null | undefined, fallback: string): string {
  if (!header) return fallback
  const star = /filename\*\s*=\s*utf-8''([^;]+)/i.exec(header)
  if (star) {
    try {
      const n = sanitize(decodeURIComponent(star[1].trim()))
      if (n) return n
    } catch {
      // malformed percent-escape: fall through to the plain filename
    }
  }
  const plain = /filename\s*=\s*(?:"([^"]*)"|([^;]+))/i.exec(header)
  return sanitize((plain?.[1] ?? plain?.[2] ?? '').trim()) || fallback
}

/** Authenticated download: fetch -> blob -> object URL (a plain <a href> can't send the bearer token). Returns the filename. */
export async function downloadFile(path: string, fallbackName: string): Promise<string> {
  const res = await fetch(path, { headers: authHeaders() })
  if (!res.ok) {
    let msg = `HTTP ${res.status}`
    try {
      const b = await res.json()
      if (typeof b?.detail === 'string') msg = b.detail
    } catch {
      // non-JSON error body; keep the HTTP status message
    }
    throw new Error(msg)
  }
  const name = filenameFromDisposition(res.headers.get('Content-Disposition'), fallbackName)
  const url = URL.createObjectURL(await res.blob())
  const a = document.createElement('a')
  a.href = url
  a.download = name
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
  return name
}
