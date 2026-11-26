// Magyar számformátum: szóközös ezres tagolás, tizedesvessző. A Decimal-stringeket szövegként formázzuk,
// így a megjelenítés sem veszít pontosságot.

const NBSP = ' '
const ZERO_DECIMAL_CURRENCIES = new Set(['HUF', 'JPY', 'KRW', 'ISK'])

const hufFormat = new Intl.NumberFormat('hu-HU', { maximumFractionDigits: 0 })

function groupThousands(digits: string): string {
  return digits.replace(/\B(?=(\d{3})+(?!\d))/g, NBSP)
}

/** Egész forint: `1 234 567 Ft`. */
export function formatHuf(value: number | null | undefined, withUnit = true): string {
  if (value === null || value === undefined) return '–'
  const s = hufFormat.format(value).replace(/\s/g, NBSP)
  return withUnit ? `${s}${NBSP}Ft` : s
}

/** Rövidített tengelyfelirat: `1,2 M`, `850 E`. */
export function formatShort(value: number): string {
  const abs = Math.abs(value)
  const fmt = (n: number) => new Intl.NumberFormat('hu-HU', { maximumFractionDigits: 1 }).format(n)
  if (abs >= 1e9) return `${fmt(value / 1e9)}${NBSP}Mrd`
  if (abs >= 1e6) return `${fmt(value / 1e6)}${NBSP}M`
  if (abs >= 1e3) return `${fmt(value / 1e3)}${NBSP}E`
  return fmt(value)
}

/** Decimal-string → `1 234,50`. A tizedesjegyeket nem kerekíti, legfeljebb kiegészíti `minDecimals`-ig. */
export function formatDecimal(value: string | null | undefined, minDecimals = 0): string {
  if (value === null || value === undefined || value === '') return '–'
  const negative = value.startsWith('-')
  const [intPart, fracPart = ''] = value.replace(/^[-+]/, '').split('.')
  let frac = fracPart.replace(/0+$/, '')
  if (frac.length < minDecimals) frac = frac.padEnd(minDecimals, '0')
  const body = groupThousands(intPart || '0') + (frac ? `,${frac}` : '')
  return negative ? `−${body}` : body
}

/** Devizaösszeg a pénznem tizedesjegyeivel: `1 153,16 EUR`, `427 736 HUF`. */
export function formatMoney(amount: string | null, currency: string | null): string {
  if (amount === null) return '–'
  const decimals = currency && ZERO_DECIMAL_CURRENCIES.has(currency) ? 0 : 2
  return `${formatDecimal(amount, decimals)}${currency ? NBSP + currency : ''}`
}

/** ISO dátum → `2026.03.15.` */
export function formatDate(iso: string | null | undefined): string {
  if (!iso) return '–'
  const [y, m, d] = iso.slice(0, 10).split('-')
  return `${y}.${m}.${d}.`
}
