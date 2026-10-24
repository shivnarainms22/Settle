import type { AuditEvent } from './api'
import { formatMoney } from './format'

export interface Ref {
  kind: string
  id: string
}

/** "invoice:INV-1088" -> {kind:"invoice", id:"INV-1088"}. The bare ref "run" has no id. Null when invalid. */
export function parseRef(ref: string): Ref | null {
  const s = ref.trim()
  if (s === 'run') return { kind: 'run', id: '' }
  const i = s.indexOf(':')
  if (i <= 0 || i === s.length - 1) return null
  return { kind: s.slice(0, i), id: s.slice(i + 1) }
}

/** Router path for a ref; the colon and any special characters are URL-encoded. */
export function traceHref(ref: string): string {
  return `/trace/${encodeURIComponent(ref)}`
}

export interface EventSummary {
  /** One line, shown beside the event type label. */
  headline: string
  /** Additional "field: old -> new" style rows. */
  rows: string[]
  /** Collapsible long text (email body). */
  expandable?: string
  /** Link target for decision events. */
  decisionId?: number
  /** Pretty JSON, only for event types with no dedicated summary. */
  json?: string
}

type Body = Record<string, unknown>

const str = (v: unknown): string => (typeof v === 'string' ? v : v === undefined || v === null ? '' : JSON.stringify(v))
const num = (v: unknown): number | undefined => (typeof v === 'number' ? v : undefined)

function changeRows(changes: unknown): string[] {
  if (changes === null || typeof changes !== 'object') return []
  return Object.entries(changes as Record<string, unknown>).map(([field, c]) => {
    const { old, new: next } = (c ?? {}) as { old?: unknown; new?: unknown }
    return `${field}: ${str(old) || 'null'} → ${str(next) || 'null'}`
  })
}

export function summarizeEvent(e: Pick<AuditEvent, 'event_type' | 'event'>): EventSummary {
  const b: Body = e.event
  const type = e.event_type
  if (type === 'invoice_updated') {
    const who = [str(b.actor) && `actor ${str(b.actor)}`, str(b.reason) && `reason: ${str(b.reason)}`].filter(Boolean)
    return { headline: who.join(' · '), rows: changeRows(b.changes) }
  }
  if (type === 'gl_post') {
    const amount = num(b.amount_cents)
    return {
      headline: `Dr ${str(b.debit)} / Cr ${str(b.credit)}${amount === undefined ? '' : ` ${formatMoney(amount)}`}`,
      rows: str(b.memo) ? [str(b.memo)] : [],
    }
  }
  if (type === 'email_sent' || type === 'email_received') {
    return { headline: str(b.subject) || '(no subject)', rows: [], expandable: str(b.body) || undefined }
  }
  if (type === 'decision') {
    const origin = str(b.component) || str(b.source)
    const source = str(b.source)
    return {
      headline: `${str(b.action)} · tier ${str(b.tier)} · ${source}${origin && origin !== source ? `/${origin}` : ''}`,
      rows: [],
      decisionId: num(b.decision_id),
    }
  }
  if (type === 'approval') {
    return { headline: `${str(b.verdict)} by ${str(b.approver)}`, rows: str(b.note) ? [`note: ${str(b.note)}`] : [] }
  }
  if (type === 'memory_write') return { headline: str(b.content), rows: [] }
  if (type === 'profile_updated') {
    return { headline: `${str(b.field)}: ${str(b.old) || 'null'} → ${str(b.new) || 'null'}`, rows: [] }
  }
  if (type.startsWith('playbook_')) return { headline: str(b.reason), rows: [] }
  return { headline: '', rows: [], json: JSON.stringify(e.event, null, 2) }
}

export interface RetrievalInfo {
  backend: string
  reranker: string | null
  memoryIds: number[]
}

/** The memory_retrieval step's output is a JSON string; null when it is not parseable or not that shape. */
export function parseRetrieval(output: string | undefined): RetrievalInfo | null {
  if (!output) return null
  let o: unknown
  try { o = JSON.parse(output) } catch { return null }
  if (o === null || typeof o !== 'object') return null
  const r = o as { backend?: unknown; reranker?: unknown; candidates?: unknown }
  if (typeof r.backend !== 'string') return null
  const memoryIds = Array.isArray(r.candidates)
    ? r.candidates.flatMap((c) => {
        const id = typeof c === 'number' ? c : (c as { id?: unknown } | null)?.id
        return typeof id === 'number' ? [id] : []
      })
    : []
  return { backend: r.backend, reranker: typeof r.reranker === 'string' ? r.reranker : null, memoryIds }
}

const KIND_ALIASES: Record<string, string> = {
  overdue: 'invoice', deduction: 'invoice', invoice_issue: 'invoice', bank_line: 'bank',
}

/** Builds a `kind:id` trace ref from a work-item / GL kind and bare id (e.g. bank_line + B-1 -> bank:B-1). */
export function toTraceRef(kind: string, id: string): string {
  return `${KIND_ALIASES[kind] ?? kind}:${id}`
}
