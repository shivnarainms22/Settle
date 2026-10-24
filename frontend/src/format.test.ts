import { describe, expect, it } from 'vitest'
import { formatDate, formatMoney, formatMoneyCompact, formatPercent, shortHash } from './format'

describe('formatMoney', () => {
  it('formats cents as dollars with separators', () => expect(formatMoney(123456)).toBe('$1,234.56'))
  it('formats zero', () => expect(formatMoney(0)).toBe('$0.00'))
  it('formats negatives', () => expect(formatMoney(-123456)).toBe('-$1,234.56'))
  it('pads single-digit cents', () => expect(formatMoney(1205)).toBe('$12.05'))
  it('handles sub-dollar amounts', () => expect(formatMoney(5)).toBe('$0.05'))
})

describe('formatMoneyCompact', () => {
  it('formats thousands', () => expect(formatMoneyCompact(41_000_000)).toBe('$410k'))
  it('formats millions', () => expect(formatMoneyCompact(120_000_000)).toBe('$1.2M'))
  it('formats small amounts', () => expect(formatMoneyCompact(45_000)).toBe('$450'))
  it('formats zero', () => expect(formatMoneyCompact(0)).toBe('$0'))
  it('formats negatives', () => expect(formatMoneyCompact(-41_000_000)).toBe('-$410k'))
})

describe('formatPercent', () => {
  it('formats a ratio', () => expect(formatPercent(0.625)).toBe('63%'))
  it('respects digits', () => expect(formatPercent(0.625, 1)).toBe('62.5%'))
  it('formats zero', () => expect(formatPercent(0)).toBe('0%'))
})

describe('misc', () => {
  it('formats ISO dates', () => expect(formatDate('2026-03-05')).toBe('Mar 5, 2026'))
  it('truncates hashes', () => expect(shortHash('abcdef0123456789')).toBe('abcdef0123…'))
})
