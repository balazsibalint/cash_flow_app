import type { Direction, ExtractionMethod, InvoiceStatus, UploadResultKind } from './types'

export interface Badge {
  label: string
  icon: string
  /** Az ikon színe (a felirat mindig szövegszínű – a szín soha nem egyedül hordozza a jelentést). */
  iconClass: string
}

export const STATUS: Record<InvoiceStatus, Badge & { hint: string }> = {
  ok: { label: 'Rendben', icon: '✓', iconClass: 'text-good', hint: 'Beleszámít a kimutatásba.' },
  review: { label: 'Ellenőrzendő', icon: '⚠', iconClass: 'text-warning', hint: 'Bizonytalan adatok – nem számít bele.' },
  pending_fx: { label: 'Árfolyamra vár', icon: '⏳', iconClass: 'text-serious', hint: 'Az MNB nem volt elérhető – a következő feltöltéskor újrapróbáljuk.' },
  rejected: { label: 'Elutasítva', icon: '⛔', iconClass: 'text-critical', hint: 'Különleges bizonylat vagy idegen számla – nem számít bele.' },
  error: { label: 'Hiba', icon: '✗', iconClass: 'text-critical', hint: 'A fájl nem dolgozható fel.' },
}

export type UploadState = 'waiting' | 'uploading' | UploadResultKind

export const UPLOAD_STATE: Record<UploadState, Badge> = {
  waiting: { label: 'Várakozik', icon: '•', iconClass: 'text-ink-3' },
  uploading: { label: 'Feldolgozás…', icon: '↻', iconClass: 'text-incoming animate-spin' },
  created: { label: 'Új', icon: '✓', iconClass: 'text-good' },
  duplicate: { label: 'Már feldolgozva', icon: '↺', iconClass: 'text-ink-2' },
  review: { label: 'Ellenőrzendő', icon: '⚠', iconClass: 'text-warning' },
  rejected: { label: 'Elutasítva', icon: '⛔', iconClass: 'text-critical' },
  error: { label: 'Hiba', icon: '✗', iconClass: 'text-critical' },
}

export const DIRECTION: Record<Direction, string> = {
  incoming: 'Bejövő',
  outgoing: 'Kimenő',
}

export const METHOD: Record<ExtractionMethod, string> = {
  rule: 'Szabály',
  llm: 'LLM',
}

