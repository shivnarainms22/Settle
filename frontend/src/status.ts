/** Label shown on a status pill. */
export function statusLabel(status: string): string {
  if (status === 'needs_review') return 'Suspended: needs review'
  if (status === 'shadow') return 'shadow — not executed'
  if (status === 'superseded') return 'closed as stale'
  return status.replace(/_/g, ' ')
}
