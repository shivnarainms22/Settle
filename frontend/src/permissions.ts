import type { Decision, User } from './api'

// Mirrors backend models.MONEY_MOVING.
const MONEY_MOVING = new Set(['propose_credit_memo', 'propose_payment_plan', 'apply_payment', 'issue_refund', 'write_off'])

const usd = (cents: number) => `$${(cents / 100).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`

export const isController = (u: User | null) => u?.role === 'controller'
/** Advance the sim, import books, approve/flag decisions: everyone but viewers. */
export const canOperate = (u: User | null) => u !== null && u.role !== 'viewer'

/**
 * UI hint only; the server's 403 is the truth. Returns why a clerk will likely be refused,
 * or null when the verdict should go through. Mirrors backend auth.check_approval.
 */
export function needsController(u: User | null, d: Pick<Decision, 'action' | 'amount_cents'>, keyAccount: boolean): string | null {
  if (!u || u.role !== 'ar_clerk') return null
  if (keyAccount && MONEY_MOVING.has(d.action)) return 'Money-moving decision on a key account: needs a controller'
  const limit = u.approval_limit_cents
  const amount = d.amount_cents ?? 0
  if (limit !== null && amount > limit) return `Amount ${usd(amount)} exceeds your approval limit ${usd(limit)}: needs a controller`
  return null
}
