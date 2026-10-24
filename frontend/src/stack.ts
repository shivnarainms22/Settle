import type { RetrievalEval, RetrievalSystem } from './api'

export const SYSTEMS: { key: RetrievalSystem; label: string }[] = [
  { key: 'sqlite_fts', label: 'SQLite FTS (keyword)' },
  { key: 'moss', label: 'Moss (semantic)' },
  { key: 'fused', label: 'FTS + Moss fused' },
  { key: 'sqlite_fts+rerank', label: 'FTS + Bitdeer rerank' },
  { key: 'moss+rerank', label: 'Moss + Bitdeer rerank' },
  { key: 'fused+rerank', label: 'FTS + Moss + Bitdeer rerank' },
]

type Summary = Partial<RetrievalEval['summary']>

export interface ComponentDelta {
  label: string
  /** recall@5 difference; null when either system is missing from the summary. */
  delta: number | null
}

const diff = (s: Summary, a: RetrievalSystem, b: RetrievalSystem): number | null => {
  const x = s[a]?.recall_at_5
  const y = s[b]?.recall_at_5
  return x === undefined || y === undefined ? null : Math.round((x - y) * 1000) / 1000
}

export function componentDeltas(s: Summary): ComponentDelta[] {
  return [
    { label: 'Moss adds (on top of FTS + rerank)', delta: diff(s, 'fused+rerank', 'sqlite_fts+rerank') },
    { label: 'Bitdeer rerank adds (on top of fused)', delta: diff(s, 'fused+rerank', 'fused') },
    { label: 'Fusion vs Moss alone', delta: diff(s, 'fused', 'moss') },
  ]
}

export function formatDelta(d: number | null): string {
  if (d === null) return 'n/a'
  return `${d >= 0 ? '+' : '-'}${Math.abs(d).toFixed(2)} recall@5`
}

/** Key of the highest value; ties go to the first. Null for an empty record. */
export function bestKey(values: Record<string, number>, keys: string[]): string | null {
  let best: string | null = null
  for (const k of keys) {
    const v = values[k]
    if (typeof v === 'number' && (best === null || v > values[best])) best = k
  }
  return best
}

/** All keys tied for the highest value (per-situation "best cell bold"). */
export function bestKeys(values: Record<string, number>, keys: string[]): Set<string> {
  const present = keys.filter((k) => typeof values[k] === 'number')
  const max = Math.max(...present.map((k) => values[k]))
  return new Set(present.filter((k) => values[k] === max))
}

const CHECK_NAMES: Record<string, string> = {
  chain: 'Hash chain intact',
  provenance: "Every decision's input recorded & hash-verified",
  policy_replay: 'Policy re-run reproduces every tier',
  guardrails: 'No blocked action executed; approvals present',
  invoice_replay: 'Invoice state rebuilt from audit diffs',
  ledger: 'Ledger balances & ties to subledger',
  messages: 'Every email audited',
  memory: 'Memory only from humans or outcomes',
  work_items: 'Work items consistent',
}

/** Human check name; unknown names fall back to a de-snake-cased version. */
export function checkLabel(name: string): string {
  if (CHECK_NAMES[name]) return CHECK_NAMES[name]
  const s = name.replace(/_/g, ' ').trim()
  return s ? s[0].toUpperCase() + s.slice(1) : 'Unnamed check'
}
