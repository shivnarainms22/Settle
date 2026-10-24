/**
 * Minimal CSV reader for the import preview: handles quoted cells containing commas,
 * doubled quotes ("") and newlines inside quotes. Stops after `maxRows` non-empty rows.
 */
export function parseCsvRows(text: string, maxRows: number): string[][] {
  const rows: string[][] = []
  let row: string[] = []
  let cell = ''
  let quoted = false
  const endRow = () => {
    row.push(cell)
    cell = ''
    if (row.some((c) => c.trim() !== '')) rows.push(row)
    row = []
  }
  for (let i = 0; i < text.length && rows.length < maxRows; i++) {
    const ch = text[i]
    if (quoted) {
      if (ch === '"' && text[i + 1] === '"') { cell += '"'; i++ }
      else if (ch === '"') quoted = false
      else cell += ch
    } else if (ch === '"') quoted = true
    else if (ch === ',') { row.push(cell); cell = '' }
    else if (ch === '\n') endRow()
    else if (ch !== '\r') cell += ch
  }
  if (rows.length < maxRows && (cell !== '' || row.length > 0)) endRow()
  return rows
}

/** Header plus the first `n` data rows. */
export function csvPreview(text: string, n = 5): { header: string[]; rows: string[][] } {
  const [header = [], ...rows] = parseCsvRows(text, n + 1)
  return { header, rows }
}
