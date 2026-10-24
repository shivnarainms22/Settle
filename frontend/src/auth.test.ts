import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { authHeaders, clearToken, getToken, setToken, setUnauthorizedHandler, streamUrl } from './auth'
import { api, ApiError } from './api'

function memoryStorage() {
  const m = new Map<string, string>()
  return {
    getItem: (k: string) => m.get(k) ?? null,
    setItem: (k: string, v: string) => void m.set(k, v),
    removeItem: (k: string) => void m.delete(k),
  }
}

beforeEach(() => { vi.stubGlobal('localStorage', memoryStorage()) })
afterEach(() => { vi.unstubAllGlobals(); setUnauthorizedHandler(null) })

describe('token storage', () => {
  it('round-trips and clears', () => {
    expect(getToken()).toBeNull()
    setToken('abc')
    expect(getToken()).toBe('abc')
    clearToken()
    expect(getToken()).toBeNull()
  })
  it('does not throw when storage is unavailable', () => {
    const boom = () => { throw new Error('denied') }
    vi.stubGlobal('localStorage', { getItem: boom, setItem: boom, removeItem: boom })
    expect(getToken()).toBeNull()
    expect(() => setToken('x')).not.toThrow()
    expect(() => clearToken()).not.toThrow()
  })
})

describe('header and stream injection', () => {
  it('omits auth when logged out, adds bearer when logged in', () => {
    expect(authHeaders()).toEqual({})
    setToken('t k')
    expect(authHeaders()).toEqual({ Authorization: 'Bearer t k' })
  })
  it('puts the encoded token on the SSE url', () => {
    expect(streamUrl()).toBe('/api/stream')
    setToken('t k')
    expect(streamUrl()).toBe('/api/stream?token=t%20k')
  })
})

describe('api requests', () => {
  const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status })

  it('sends the bearer token on GET and POST', async () => {
    setToken('tok')
    const f = vi.fn().mockImplementation(() => Promise.resolve(json({})))
    vi.stubGlobal('fetch', f)
    await api.me()
    await api.advanceTo('2026-07-15')
    expect(f.mock.calls[0][1].headers).toEqual({ Authorization: 'Bearer tok' })
    expect(f.mock.calls[1][1].headers).toEqual({ Authorization: 'Bearer tok', 'Content-Type': 'application/json' })
    expect(f.mock.calls[1][1].body).toBe('{"to":"2026-07-15"}')
  })
  it('clears the token and notifies on 401 when a token was held', async () => {
    const handler = vi.fn()
    setUnauthorizedHandler(handler)
    setToken('stale')
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(json({ detail: 'invalid token' }, 401)))
    await expect(api.me()).rejects.toMatchObject({ status: 401, message: 'invalid token' })
    expect(getToken()).toBeNull()
    expect(handler).toHaveBeenCalledOnce()
  })
  it('does not treat a failed login as a session expiry', async () => {
    const handler = vi.fn()
    setUnauthorizedHandler(handler)
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(json({ detail: 'bad credentials' }, 401)))
    await expect(api.login('x', 'y')).rejects.toBeInstanceOf(ApiError)
    expect(handler).not.toHaveBeenCalled()
  })
  it('surfaces the 403 detail verbatim and keeps the session', async () => {
    setToken('tok')
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(json({ detail: 'amount $1,200.00 exceeds your approval limit $1,000.00' }, 403)))
    await expect(api.decide(1, { verdict: 'approve' })).rejects.toMatchObject({
      status: 403,
      message: 'amount $1,200.00 exceeds your approval limit $1,000.00',
    })
    expect(getToken()).toBe('tok')
  })
})
