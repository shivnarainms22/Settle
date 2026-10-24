import { describe, expect, it } from 'vitest'
import { parseRef, parseRetrieval, summarizeEvent, toTraceRef, traceHref } from './trace'
import { shortHash } from './format'

const ev = (event_type: string, event: Record<string, unknown>) => ({ event_type, event })

describe('parseRef', () => {
  it('splits kind and id', () => expect(parseRef('invoice:INV-1088')).toEqual({ kind: 'invoice', id: 'INV-1088' }))
  it('keeps colons inside the id', () => expect(parseRef('gl:a:b')).toEqual({ kind: 'gl', id: 'a:b' }))
  it('accepts the bare run ref', () => expect(parseRef('run')).toEqual({ kind: 'run', id: '' }))
  it('trims whitespace', () => expect(parseRef('  bank:B-1 ')).toEqual({ kind: 'bank', id: 'B-1' }))
  it.each(['', 'invoice', ':x', 'invoice:'])('rejects %j', (s) => expect(parseRef(s)).toBeNull())
})

describe('traceHref', () => {
  it('url-encodes the ref', () => expect(traceHref('invoice:INV-1088')).toBe('/trace/invoice%3AINV-1088'))
  it('encodes slashes and spaces', () => expect(traceHref('a/b c')).toBe('/trace/a%2Fb%20c'))
})

describe('summarizeEvent', () => {
  it('renders invoice_updated changes as field old -> new rows', () => {
    const s = summarizeEvent(ev('invoice_updated', {
      actor: 'settle:agent', reason: 'reminder #1',
      changes: { status: { old: 'open', new: 'reminded' }, paid_on: { old: null, new: '2026-07-01' } },
    }))
    expect(s.rows).toEqual(['status: open → reminded', 'paid_on: null → 2026-07-01'])
    expect(s.headline).toBe('actor settle:agent · reason: reminder #1')
  })
  it('tolerates invoice_updated without changes', () => expect(summarizeEvent(ev('invoice_updated', {})).rows).toEqual([]))
  it('renders gl_post as Dr/Cr with amount', () =>
    expect(summarizeEvent(ev('gl_post', { debit: 'Cash', credit: 'Accounts Receivable', amount_cents: 970000 })).headline)
      .toBe('Dr Cash / Cr Accounts Receivable $9,700.00'))
  it('renders email subject with expandable body', () => {
    const s = summarizeEvent(ev('email_sent', { subject: 'Reminder: INV-1', body: 'Hi' }))
    expect(s.headline).toBe('Reminder: INV-1')
    expect(s.expandable).toBe('Hi')
  })
  it('handles email_received with no subject', () => expect(summarizeEvent(ev('email_received', {})).headline).toBe('(no subject)'))
  it('renders decision with link id, tier and source/component', () => {
    const s = summarizeEvent(ev('decision', { action: 'send_reminder', tier: 0, source: 'agent', component: 'heuristic', decision_id: 3 }))
    expect(s.headline).toBe('send_reminder · tier 0 · agent/heuristic')
    expect(s.decisionId).toBe(3)
  })
  it('does not repeat source when equal to component', () =>
    expect(summarizeEvent(ev('decision', { action: 'a', tier: 1, source: 'playbook', component: 'playbook' })).headline)
      .toBe('a · tier 1 · playbook'))
  it('renders approval verdict and approver', () =>
    expect(summarizeEvent(ev('approval', { verdict: 'approve', approver: 'ar_manager' })).headline).toBe('approve by ar_manager'))
  it('renders memory_write content', () => expect(summarizeEvent(ev('memory_write', { content: 'Needs PO' })).headline).toBe('Needs PO'))
  it('renders profile_updated field old -> new', () =>
    expect(summarizeEvent(ev('profile_updated', { field: 'late_days', old: '[]', new: '[13]' })).headline).toBe('late_days: [] → [13]'))
  it('renders playbook_* reason', () => expect(summarizeEvent(ev('playbook_needs_review', { reason: 'drift' })).headline).toBe('drift'))
  it('falls back to pretty JSON for unknown types', () => {
    const s = summarizeEvent(ev('sim_reset', { seed: 7 }))
    expect(s.json).toBe('{\n  "seed": 7\n}')
    expect(s.headline).toBe('')
  })
})

describe('parseRetrieval', () => {
  it('reads backend, reranker and candidate ids', () =>
    expect(parseRetrieval('{"backend":"moss","reranker":"bitdeer","candidates":[{"id":4},{"id":9}]}'))
      .toEqual({ backend: 'moss', reranker: 'bitdeer', memoryIds: [4, 9] }))
  it('defaults reranker to null', () =>
    expect(parseRetrieval('{"backend":"sqlite-fts","candidates":[],"reranker":null}')).toEqual({ backend: 'sqlite-fts', reranker: null, memoryIds: [] }))
  it.each([undefined, '', 'not json', '42', '{"x":1}'])('returns null for %j', (s) => expect(parseRetrieval(s)).toBeNull())
})

describe('shortHash (fingerprint truncation)', () => {
  it('keeps the first 12 chars', () => expect(shortHash('2b7d776b6f21ff497bb3', 12)).toBe('2b7d776b6f21…'))
  it('leaves short values untouched', () => expect(shortHash('abc', 12)).toBe('abc'))
  it('handles empty', () => expect(shortHash('')).toBe(''))
})

describe('toTraceRef', () => {
  it('maps overdue work items to invoice refs', () => expect(toTraceRef('overdue', 'INV-1')).toBe('invoice:INV-1'))
  it('maps bank_line to bank', () => expect(toTraceRef('bank_line', 'B-1')).toBe('bank:B-1'))
  it('passes unknown kinds through', () => expect(toTraceRef('email', 'E-3')).toBe('email:E-3'))
})
