export function formatMoney(cents: number): string {
  const neg = cents < 0
  const abs = Math.abs(Math.round(cents))
  const dollars = Math.floor(abs / 100)
  const rem = String(abs % 100).padStart(2, '0')
  return `${neg ? '-' : ''}$${dollars.toLocaleString('en-US')}.${rem}`
}

export function formatMoneyCompact(cents: number): string {
  const neg = cents < 0
  const d = Math.abs(cents) / 100
  const trim = (n: number) => n.toFixed(1).replace(/\.0$/, '')
  let s: string
  if (d >= 1_000_000) s = `$${trim(d / 1_000_000)}M`
  else if (d >= 1_000) s = `$${Math.round(d / 1_000)}k`
  else s = `$${Math.round(d)}`
  return neg ? `-${s}` : s
}

/** value on 0..1 scale */
export function formatPercent(ratio: number, digits = 0): string {
  return `${(ratio * 100).toFixed(digits)}%`
}

/** value already on 0..100 scale */
export function formatPct100(pct: number, digits = 0): string {
  return `${pct.toFixed(digits)}%`
}

export function formatDate(iso: string): string {
  const [y, m, d] = iso.split('-').map(Number)
  if (!y || !m || !d) return iso
  return new Date(Date.UTC(y, m - 1, d)).toLocaleDateString('en-US', {
    month: 'short', day: 'numeric', year: 'numeric', timeZone: 'UTC',
  })
}

export function shortHash(h: string, n = 10): string {
  return h.length > n ? `${h.slice(0, n)}…` : h
}

/** Readable action name, e.g. request_dispute_evidence -> "request dispute evidence". */
export function actionLabel(action: string): string {
  return action.replace(/_/g, ' ')
}
