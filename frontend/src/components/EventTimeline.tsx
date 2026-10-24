import { useState } from 'react'
import { Link } from 'react-router-dom'
import type { AuditEvent } from '../api'
import { formatDate, shortHash } from '../format'
import { summarizeEvent } from '../trace'
import RefChip from './RefChip'
import { Chip, Empty, Mono } from './ui'

function labelStyle(type: string): string {
  if (type === 'decision' || type.startsWith('decision_')) return 'bg-indigo-100 text-indigo-800'
  if (type === 'approval') return 'bg-amber-100 text-amber-800'
  if (type.startsWith('email')) return 'bg-sky-100 text-sky-800'
  if (type === 'gl_post') return 'bg-emerald-100 text-emerald-800'
  if (type === 'invoice_updated') return 'bg-teal-100 text-teal-800'
  if (type.startsWith('memory') || type === 'profile_updated') return 'bg-violet-100 text-violet-800'
  if (type.startsWith('playbook')) return 'bg-fuchsia-100 text-fuchsia-800'
  return 'bg-slate-100 text-slate-700'
}

function EventItem({ e }: { e: AuditEvent }) {
  const [open, setOpen] = useState(false)
  const s = summarizeEvent(e)
  return (
    <li className="relative pb-5 pl-7 last:pb-0">
      <span className="absolute -left-[6.5px] top-1.5 h-3 w-3 rounded-full border-2 border-white bg-accent ring-1 ring-slate-300" />
      <div className="flex flex-wrap items-center gap-2">
        <span className="tnum text-xs text-slate-500">{formatDate(e.sim_date)}</span>
        <Chip className={labelStyle(e.event_type)}>{e.event_type}</Chip>
        <Mono className="text-slate-400">#{e.id}</Mono>
      </div>
      {(s.headline || s.decisionId !== undefined) && (
        <div className="mt-1 text-sm text-slate-800">
          {s.headline}
          {s.decisionId !== undefined && (
            <Link to={`/decisions/${s.decisionId}`} className="ml-2 text-accent hover:underline">Decision #{s.decisionId}</Link>
          )}
        </div>
      )}
      {s.rows.length > 0 && (
        <ul className="mt-1 space-y-0.5 font-mono text-xs text-slate-600">{s.rows.map((r) => <li key={r}>{r}</li>)}</ul>
      )}
      {s.expandable && (
        <div className="mt-1">
          <button className="text-xs text-accent hover:underline" onClick={() => setOpen(!open)}>{open ? 'Hide body' : 'Show body'}</button>
          {open && <p className="mt-1 whitespace-pre-wrap rounded-md bg-slate-50 p-3 text-sm text-slate-700">{s.expandable}</p>}
        </div>
      )}
      {s.json && (
        <pre className="mt-1 overflow-x-auto whitespace-pre-wrap break-words rounded-md bg-slate-50 p-2 font-mono text-xs text-slate-700">{s.json}</pre>
      )}
      <div className="mt-1.5 flex flex-wrap gap-1.5">{e.refs.map((r) => <RefChip key={r} refId={r} />)}</div>
      <div className="mt-1.5 font-mono text-[11px] text-slate-400" title={`prev ${e.prev_hash}\nhash ${e.hash}`}>
        <span>{shortHash(e.prev_hash, 8)}</span> <span className="text-slate-300">&rarr;</span> <span className="text-slate-600">{shortHash(e.hash, 8)}</span>
      </div>
    </li>
  )
}

/** Vertical timeline of audit events, oldest first (as returned by the API). */
export default function EventTimeline({ events }: { events: AuditEvent[] }) {
  if (events.length === 0) return <Empty>No audit events.</Empty>
  return (
    <ol className="relative ml-1.5 border-l border-slate-200">
      {events.map((e) => <EventItem key={e.id} e={e} />)}
    </ol>
  )
}
