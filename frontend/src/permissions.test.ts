import { describe, expect, it } from 'vitest'
import type { User } from './api'
import { canOperate, isController, needsController } from './permissions'

const mk = (role: User['role'], limit: number | null): User => ({ username: 'u', name: 'U', role, approval_limit_cents: limit })
const clerk = mk('ar_clerk', 100_000)

describe('needsController', () => {
  it('flags amounts over the clerk limit', () => {
    expect(needsController(clerk, { action: 'send_reminder', amount_cents: 120_000 }, false))
      .toMatch(/\$1,200\.00 exceeds your approval limit \$1,000\.00/)
  })
  it('allows amounts at the limit', () => {
    expect(needsController(clerk, { action: 'send_reminder', amount_cents: 100_000 }, false)).toBeNull()
  })
  it('treats a null amount as zero', () => {
    expect(needsController(clerk, { action: 'escalate', amount_cents: null }, false)).toBeNull()
  })
  it('flags money-moving actions on key accounts only', () => {
    expect(needsController(clerk, { action: 'propose_credit_memo', amount_cents: 100 }, true)).toMatch(/key account/)
    expect(needsController(clerk, { action: 'send_reminder', amount_cents: 100 }, true)).toBeNull()
    expect(needsController(clerk, { action: 'propose_credit_memo', amount_cents: 100 }, false)).toBeNull()
  })
  it('never flags controllers, and a null limit means unlimited', () => {
    expect(needsController(mk('controller', null), { action: 'issue_refund', amount_cents: 9e9 }, true)).toBeNull()
    expect(needsController(mk('ar_clerk', null), { action: 'send_reminder', amount_cents: 9e9 }, false)).toBeNull()
  })
})

describe('role helpers', () => {
  it('viewers and logged-out users cannot operate', () => {
    expect(canOperate(mk('viewer', 0))).toBe(false)
    expect(canOperate(null)).toBe(false)
    expect(canOperate(clerk)).toBe(true)
    expect(isController(clerk)).toBe(false)
    expect(isController(mk('controller', null))).toBe(true)
  })
})
