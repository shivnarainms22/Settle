import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from 'react'
import { api, type User } from '../api'
import { clearToken, getToken, setToken, setUnauthorizedHandler } from '../auth'
import { Loading } from './ui'
import Login from '../pages/Login'

interface AuthCtx {
  user: User
  logout: () => void
}

const Ctx = createContext<AuthCtx | null>(null)

/** The logged-in user. Only usable below <AuthGate>. */
export function useAuth(): AuthCtx {
  const c = useContext(Ctx)
  if (!c) throw new Error('useAuth outside AuthGate')
  return c
}

/** Renders the login page until a valid session exists, then the app. A 401 anywhere returns here. */
export function AuthGate({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [checking, setChecking] = useState(() => getToken() !== null)

  useEffect(() => {
    setUnauthorizedHandler(() => setUser(null))
    return () => setUnauthorizedHandler(null)
  }, [])

  // Validate a stored token once on load.
  useEffect(() => {
    if (!getToken()) return
    api.me().then(
      (u) => { setUser(u); setChecking(false) },
      () => setChecking(false), // 401 already cleared the token; other failures fall back to login
    )
  }, [])

  const login = useCallback(async (username: string, password: string) => {
    const r = await api.login(username, password)
    setToken(r.token)
    setUser(r.user)
  }, [])

  const logout = useCallback(() => { clearToken(); setUser(null) }, [])

  if (checking) return <Loading label="Checking session..." />
  if (!user) return <Login onLogin={login} />
  return <Ctx.Provider value={{ user, logout }}>{children}</Ctx.Provider>
}
