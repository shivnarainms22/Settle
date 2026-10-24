import { useEffect, type ReactNode } from 'react'
import type { AgentState, Tier } from '../api'
import { statusLabel } from '../status'

export function Card({ title, right, children, className = '' }: {
  title?: ReactNode; right?: ReactNode; children: ReactNode; className?: string
}) {
  return (
    <section className={`rounded-xl border border-slate-200 bg-white shadow-sm ${className}`}>
      {(title || right) && (
        <header className="flex items-center justify-between border-b border-slate-100 px-5 py-3">
          <h2 className="text-sm font-semibold tracking-wide text-slate-700">{title}</h2>
          {right}
        </header>
      )}
      <div className="p-5">{children}</div>
    </section>
  )
}

export function PageHeader({ title, subtitle, right }: { title: string; subtitle?: string; right?: ReactNode }) {
  return (
    <div className="mb-6 flex items-end justify-between gap-4">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-slate-900">{title}</h1>
        {subtitle && <p className="mt-1 text-sm text-slate-500">{subtitle}</p>}
      </div>
      {right}
    </div>
  )
}

export function Chip({ children, className = '' }: { children: ReactNode; className?: string }) {
  return (
    <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${className}`}>
      {children}
    </span>
  )
}

const TIER_STYLE: Record<Tier, string> = {
  0: 'bg-emerald-100 text-emerald-800',
  1: 'bg-sky-100 text-sky-800',
  2: 'bg-amber-100 text-amber-800',
  3: 'bg-rose-100 text-rose-800',
}
export function TierChip({ tier }: { tier: Tier }) {
  return <Chip className={`${TIER_STYLE[tier]} font-semibold`}>T{tier}</Chip>
}

const STATE_STYLE: Record<AgentState, string> = {
  'Agent Working': 'bg-indigo-600 text-white',
  'Self-Learning': 'bg-violet-600 text-white',
  'Input Needed': 'bg-amber-500 text-white',
  Blocked: 'bg-rose-600 text-white',
}
export function AgentStateChip({ state }: { state: AgentState }) {
  return (
    <Chip className={`${STATE_STYLE[state]} px-2.5 uppercase tracking-wide text-[10px] font-semibold`}>{state}</Chip>
  )
}

const STATUS_STYLE: Record<string, string> = {
  executed: 'bg-emerald-100 text-emerald-800',
  approved: 'bg-emerald-100 text-emerald-800',
  paid: 'bg-emerald-100 text-emerald-800',
  active: 'bg-emerald-100 text-emerald-800',
  pending_approval: 'bg-amber-100 text-amber-800',
  proposed: 'bg-amber-100 text-amber-800',
  needs_review: 'bg-amber-200 text-amber-900 font-semibold',
  edited: 'bg-sky-100 text-sky-800',
  reminded: 'bg-sky-100 text-sky-800',
  partially_paid: 'bg-sky-100 text-sky-800',
  plan: 'bg-sky-100 text-sky-800',
  rejected: 'bg-rose-100 text-rose-800',
  blocked: 'bg-rose-100 text-rose-800',
  disputed: 'bg-rose-100 text-rose-800',
  escalated: 'bg-orange-100 text-orange-800',
  on_hold: 'bg-slate-200 text-slate-700',
  disabled: 'bg-slate-200 text-slate-700',
  scheduled: 'bg-slate-100 text-slate-600',
  open: 'bg-indigo-100 text-indigo-800',
  shadow: 'bg-purple-100 text-purple-800',
  superseded: 'bg-slate-200 text-slate-600',
}
export function StatusChip({ status }: { status: string }) {
  return <Chip className={STATUS_STYLE[status] ?? 'bg-slate-100 text-slate-700'}>{statusLabel(status)}</Chip>
}

export function Mono({ children, className = '' }: { children: ReactNode; className?: string }) {
  return <span className={`font-mono text-xs ${className}`}>{children}</span>
}

export function Spinner({ label }: { label?: string }) {
  return (
    <span className="inline-flex items-center gap-2 text-sm text-slate-500">
      <span className="h-4 w-4 animate-spin rounded-full border-2 border-slate-300 border-t-accent" />
      {label}
    </span>
  )
}

export function Loading({ label = 'Loading...' }: { label?: string }) {
  return <div className="py-16 text-center"><Spinner label={label} /></div>
}

export function ErrorBanner({ error }: { error: Error & { status?: number } }) {
  const unreachable = error.status === 0
  return (
    <div role="alert" className="mb-4 rounded-lg border border-rose-300 bg-rose-50 px-4 py-3 text-sm text-rose-800">
      <strong className="font-semibold">
        {unreachable ? 'Backend not reachable at :8000' : 'Request failed'}
      </strong>
      <span className="ml-2 text-rose-700">{unreachable ? 'Start it with `uv run uvicorn settle.api:app --port 8000`.' : error.message}</span>
    </div>
  )
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="py-10 text-center text-sm text-slate-400">{children}</div>
}

export function Toast({ message, onDone }: { message: string | null; onDone: () => void }) {
  useEffect(() => {
    if (!message) return
    const t = setTimeout(onDone, 2600)
    return () => clearTimeout(t)
  }, [message, onDone])
  if (!message) return null
  return (
    <div className="fixed bottom-6 right-6 z-50 rounded-lg bg-ink-900 px-4 py-3 text-sm font-medium text-white shadow-xl">
      <span className="mr-2 text-emerald-400">&#10003;</span>
      {message}
    </div>
  )
}

export function Button({ variant = 'secondary', className = '', ...p }: React.ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: 'primary' | 'secondary' | 'danger' | 'ghost'
}) {
  const v = {
    primary: 'bg-accent text-white hover:bg-accent-dark',
    secondary: 'border border-slate-300 bg-white text-slate-700 hover:bg-slate-50',
    danger: 'border border-rose-300 bg-white text-rose-700 hover:bg-rose-50',
    ghost: 'text-slate-600 hover:bg-slate-100',
  }[variant]
  return (
    <button
      {...p}
      className={`rounded-md px-3.5 py-1.5 text-sm font-medium transition disabled:cursor-not-allowed disabled:opacity-50 ${v} ${className}`}
    />
  )
}

export function ConfidenceBar({ value }: { value: number }) {
  const pct = Math.max(0, Math.min(1, value)) * 100
  const color = pct >= 80 ? 'bg-emerald-500' : pct >= 55 ? 'bg-amber-500' : 'bg-rose-500'
  return (
    <div className="flex items-center gap-2">
      <div className="h-2 w-28 overflow-hidden rounded-full bg-slate-200">
        <div className={`h-full ${color}`} style={{ width: `${pct}%` }} />
      </div>
      <span className="tnum text-xs text-slate-600">{pct.toFixed(0)}%</span>
    </div>
  )
}

export function Json({ value }: { value: unknown }) {
  return (
    <pre className="overflow-x-auto whitespace-pre-wrap break-words rounded-md bg-slate-900 p-3 font-mono text-xs leading-relaxed text-slate-100">
      {JSON.stringify(value, null, 2)}
    </pre>
  )
}

export const th = 'px-3 py-2 text-left text-xs font-semibold uppercase tracking-wide text-slate-500'
export const td = 'px-3 py-2.5 text-sm'
