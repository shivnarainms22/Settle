// Token storage. localStorage can throw (private mode, disabled storage): never let that break the app.
const KEY = 'settle.token'

export function getToken(): string | null {
  try { return localStorage.getItem(KEY) } catch { return null }
}

export function setToken(token: string): void {
  try { localStorage.setItem(KEY, token) } catch { /* storage unavailable: login still works for this page load only */ }
}

export function clearToken(): void {
  try { localStorage.removeItem(KEY) } catch { /* nothing stored, nothing to clear */ }
}

/** Auth header for fetch, or an empty object when logged out. */
export function authHeaders(): Record<string, string> {
  const t = getToken()
  return t ? { Authorization: `Bearer ${t}` } : {}
}

/** SSE cannot set headers: the token rides on the query string. */
export function streamUrl(base = '/api/stream'): string {
  const t = getToken()
  return t ? `${base}?token=${encodeURIComponent(t)}` : base
}

let onUnauthorized: (() => void) | null = null
/** Registered by AuthProvider; called when a request returns 401 while a token was held. */
export function setUnauthorizedHandler(fn: (() => void) | null): void { onUnauthorized = fn }
export function notifyUnauthorized(): void { onUnauthorized?.() }
