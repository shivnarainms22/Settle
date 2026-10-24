import { describe, expect, it } from 'vitest'
import type { Decision } from './api'
import { TOUR_STEPS, nextStepIndex, stepTarget } from './tour'
import { filenameFromDisposition } from './download'
import { statusLabel } from './status'

describe('TOUR_STEPS', () => {
  it('has ISO dates in strictly increasing order and absolute paths', () => {
    const dates = TOUR_STEPS.map((s) => s.to)
    for (const d of dates) expect(d).toMatch(/^\d{4}-\d{2}-\d{2}$/)
    expect([...dates].sort()).toEqual(dates)
    expect(new Set(dates).size).toBe(dates.length)
    for (const s of TOUR_STEPS) expect(s.path.startsWith('/')).toBe(true)
  })

  const dec = (over: Partial<Decision>) => ({ id: 1, sim_date: '2026-07-20', action: 'send_reminder', status: 'executed',
    customer_name: 'X', work_item: { kind: 'overdue', ref: 'INV-1', summary: '' }, ...over }) as Decision

  it('opens the first matching decision, else the step page', () => {
    const fraud = TOUR_STEPS.find((s) => s.title.startsWith('Fraud'))!
    const ds = [dec({ id: 9, action: 'issue_refund', status: 'blocked' }), dec({ id: 3, action: 'issue_refund', status: 'blocked' })]
    expect(stepTarget(fraud, ds)).toBe('/decisions/3')
    expect(stepTarget(fraud, [dec({ action: 'issue_refund', status: 'pending_approval' })])).toBe(fraud.path)
    const noPick = TOUR_STEPS.find((s) => !s.pick)!
    expect(stepTarget(noPick, ds)).toBe(noPick.path)
  })

  it('finds the injection decision by customer, date and email', () => {
    const inj = TOUR_STEPS.find((s) => s.title.startsWith('Prompt injection'))!
    const ds = [
      dec({ id: 5, sim_date: '2026-08-01', customer_name: 'Halvorsen Biologics', work_item: { kind: 'overdue', ref: 'INV-9', summary: '' } }),
      dec({ id: 4, sim_date: '2026-08-01', customer_name: 'Halvorsen Biologics', work_item: { kind: 'email', ref: 'E-86', summary: '' } }),
    ]
    expect(stepTarget(inj, ds)).toBe('/decisions/4')
  })

  it('finds the unknown-payer wire by its bank line', () => {
    const alias = TOUR_STEPS.find((s) => s.title.startsWith('A payer'))!
    const ds = [
      dec({ id: 7, work_item: { kind: 'bank_line', ref: 'B-56', summary: '$1 from MRWBRDG SHARED SVCS AP' } }),
      dec({ id: 6, work_item: { kind: 'bank_line', ref: 'B-43', summary: '$2 from MRWBRDG SHARED SVCS AP' } }),
      dec({ id: 2, work_item: { kind: 'bank_line', ref: 'B-1', summary: '$3 from ACME' } }),
    ]
    expect(stepTarget(alias, ds)).toBe('/decisions/6')
  })

  it('tracks the next step from the sim date', () => {
    expect(nextStepIndex(undefined)).toBe(0)
    expect(nextStepIndex('2026-07-01')).toBe(0)
    expect(nextStepIndex(TOUR_STEPS[0].to)).toBe(1)
    expect(nextStepIndex('2026-12-31')).toBe(TOUR_STEPS.length)
  })
})

describe('filenameFromDisposition', () => {
  it('reads a quoted filename', () =>
    expect(filenameFromDisposition('attachment; filename="settle-audit-abc123.jsonl"', 'x')).toBe('settle-audit-abc123.jsonl'))
  it('reads an unquoted filename', () => expect(filenameFromDisposition('attachment; filename=d.csv', 'x')).toBe('d.csv'))
  it('prefers RFC 5987 filename*', () =>
    expect(filenameFromDisposition('attachment; filename="a.csv"; filename*=UTF-8\'\'b%20c.csv', 'x')).toBe('b c.csv'))
  it('falls back when missing or empty', () => {
    expect(filenameFromDisposition(null, 'fb.csv')).toBe('fb.csv')
    expect(filenameFromDisposition('attachment', 'fb.csv')).toBe('fb.csv')
    expect(filenameFromDisposition('attachment; filename=""', 'fb.csv')).toBe('fb.csv')
  })
  it('strips path components', () =>
    expect(filenameFromDisposition('attachment; filename="../../evil.sh"', 'x')).toBe('evil.sh'))
})

describe('statusLabel', () => {
  it('labels shadow as not executed', () => expect(statusLabel('shadow')).toBe('shadow — not executed'))
  it('keeps existing labels', () => {
    expect(statusLabel('pending_approval')).toBe('pending approval')
    expect(statusLabel('needs_review')).toBe('Suspended: needs review')
  })
})
