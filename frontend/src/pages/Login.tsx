import { useState } from 'react'
import { api, type User } from '../api'
import { formatMoney } from '../format'
import { useResource } from '../hooks'
import { Button, Card, Chip, ErrorBanner } from '../components/ui'

const DEMO_PASSWORD = 'demo'

export const ROLE_LABEL: Record<User['role'], string> = { controller: 'Controller', ar_clerk: 'AR clerk', viewer: 'Viewer' }
export const ROLE_STYLE: Record<User['role'], string> = {
  controller: 'bg-indigo-100 text-indigo-800',
  ar_clerk: 'bg-sky-100 text-sky-800',
  viewer: 'bg-slate-200 text-slate-700',
}

const limitText = (u: User) =>
  u.role === 'viewer' ? 'read-only' : u.approval_limit_cents === null ? 'no approval limit' : `approves up to ${formatMoney(u.approval_limit_cents)}`

export default function Login({ onLogin }: { onLogin: (username: string, password: string) => Promise<void> }) {
  const users = useResource(api.users)
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<Error | null>(null)

  async function submit(u: string, p: string) {
    setBusy(true)
    setError(null)
    try { await onLogin(u, p) }
    catch (e) { setError(e instanceof Error ? e : new Error(String(e))); setBusy(false) }
  }

  return (
    <div className="mx-auto flex min-h-screen max-w-2xl flex-col justify-center px-6 py-10">
      <div className="mb-8">
        <div className="text-3xl font-bold tracking-tight text-slate-900">Settle<span className="text-indigo-500">.</span></div>
        <div className="mt-1 text-sm text-slate-500">Autonomous accounts receivable. Sign in to continue.</div>
      </div>
      {error && <ErrorBanner error={error} />}

      <Card title="Demo users" right={<span className="text-xs text-slate-400">one click, password "{DEMO_PASSWORD}"</span>}>
        {users.error && <ErrorBanner error={users.error} />}
        <div className="grid grid-cols-3 gap-3">
          {(users.data ?? []).map((u) => (
            <button
              key={u.username}
              disabled={busy}
              onClick={() => submit(u.username, DEMO_PASSWORD)}
              className="rounded-lg border border-slate-200 p-3 text-left transition hover:border-accent hover:bg-slate-50 disabled:opacity-50"
            >
              <div className="text-sm font-semibold text-slate-900">{u.name}</div>
              <Chip className={`mt-1 ${ROLE_STYLE[u.role]}`}>{ROLE_LABEL[u.role]}</Chip>
              <div className="mt-1.5 text-xs text-slate-500">{limitText(u)}</div>
            </button>
          ))}
        </div>
      </Card>

      <Card title="Sign in" className="mt-4">
        <form className="grid gap-3" onSubmit={(e) => { e.preventDefault(); void submit(username.trim(), password) }}>
          <input
            aria-label="Username"
            className="rounded-md border border-slate-300 px-3 py-2 text-sm"
            placeholder="Username"
            autoComplete="username"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
          />
          <input
            aria-label="Password"
            type="password"
            className="rounded-md border border-slate-300 px-3 py-2 text-sm"
            placeholder="Password"
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
          <Button type="submit" variant="primary" disabled={busy || username.trim() === '' || password === ''}>
            {busy ? 'Signing in...' : 'Sign in'}
          </Button>
        </form>
      </Card>
    </div>
  )
}
