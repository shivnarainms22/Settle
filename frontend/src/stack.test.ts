import { describe, expect, it } from 'vitest'
import { csvPreview, parseCsvRows } from './csv'
import { bestKey, bestKeys, checkLabel, componentDeltas, formatDelta } from './stack'

const stat = (r: number) => ({ recall_at_5: r, mrr: 0, median_latency_ms: 0, queries: 1 })

describe('componentDeltas', () => {
  it('computes each delta from the summary', () => {
    const d = componentDeltas({
      moss: stat(0.657), fused: stat(0.736), 'sqlite_fts+rerank': stat(0.796), 'fused+rerank': stat(0.875),
    })
    expect(d.map((x) => x.delta)).toEqual([0.079, 0.139, 0.079])
    expect(formatDelta(d[0].delta)).toBe('+0.08 recall@5')
  })
  it('returns null deltas when a system is missing', () => {
    const d = componentDeltas({ fused: stat(0.7) })
    expect(d.map((x) => x.delta)).toEqual([null, null, null])
    expect(formatDelta(null)).toBe('n/a')
  })
  it('formats negative deltas', () => expect(formatDelta(-0.05)).toBe('-0.05 recall@5'))
})

describe('best selection', () => {
  it('picks the highest, first on ties', () => expect(bestKey({ a: 1, b: 2, c: 2 }, ['a', 'b', 'c'])).toBe('b'))
  it('returns null when nothing is present', () => expect(bestKey({}, ['a'])).toBeNull())
  it('returns all tied keys', () => expect([...bestKeys({ a: 1, b: 1, c: 0.5 }, ['a', 'b', 'c'])]).toEqual(['a', 'b']))
})

describe('checkLabel', () => {
  it('maps known names', () => expect(checkLabel('chain')).toBe('Hash chain intact'))
  it('falls back for unknown names', () => expect(checkLabel('new_check')).toBe('New check'))
  it('handles empty', () => expect(checkLabel('')).toBe('Unnamed check'))
})

describe('csv preview', () => {
  it('keeps quoted commas in one cell', () => {
    expect(parseCsvRows('a,b\n1,"$1,234.00"\n', 10)).toEqual([['a', 'b'], ['1', '$1,234.00']])
  })
  it('handles doubled quotes, CRLF and trailing row without newline', () => {
    expect(parseCsvRows('a,b\r\n"x ""y""",z', 10)).toEqual([['a', 'b'], ['x "y"', 'z']])
  })
  it('keeps empty cells and skips blank lines', () => {
    expect(parseCsvRows('a,b,c\n\n1,,3\n', 10)).toEqual([['a', 'b', 'c'], ['1', '', '3']])
  })
  it('returns header plus first n rows', () => {
    const p = csvPreview('h\n1\n2\n3', 2)
    expect(p.header).toEqual(['h'])
    expect(p.rows).toEqual([['1'], ['2']])
  })
  it('is empty for empty input', () => expect(csvPreview('')).toEqual({ header: [], rows: [] }))
})
