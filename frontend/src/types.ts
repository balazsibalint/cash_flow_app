// A backend sémáinak (app/schemas.py) megfelelő típusok. A pénzösszegek stringek (Decimal), a gross_huf egész.

export type InvoiceStatus = 'ok' | 'review' | 'pending_fx' | 'rejected' | 'error'
export type Direction = 'incoming' | 'outgoing'
export type ExtractionMethod = 'rule' | 'llm'

export interface Message {
  code: string
  level: 'info' | 'warning' | 'error'
  text: string
}

export interface PartnerRef {
  id: number
  tax_key: string
  display_name: string
}

export interface Invoice {
  id: number
  filename: string
  status: InvoiceStatus
  status_reason: string | null
  messages: Message[]
  extraction_method: ExtractionMethod | null
  doc_type: string | null
  invoice_number: string | null
  seller_name: string | null
  seller_tax: string | null
  buyer_name: string | null
  buyer_tax: string | null
  issue_date: string | null
  supply_date: string | null
  due_date: string | null
  supply_date_inferred: boolean
  due_date_inferred: boolean
  currency: string | null
  net_amount: string | null
  vat_amount: string | null
  gross_amount: string | null
  direction: Direction | null
  partner: PartnerRef | null
  fx_rate: string | null
  fx_unit: number | null
  fx_rate_date: string | null
  fx_provisional: boolean
  gross_huf: number | null
  created_at: string
}

export type UploadResultKind = 'created' | 'duplicate' | 'rejected' | 'review' | 'error'

export interface UploadResult {
  result: UploadResultKind
  message: string
  invoice: Invoice | null
}

export interface MonthPoint {
  month: string
  incoming_huf: number
  outgoing_huf: number
}

export interface PartnerTotals {
  partner_id: number
  name: string
  aliases: string[]
  incoming_huf: number
  outgoing_huf: number
}

export interface Report {
  months: MonthPoint[]
  partners: PartnerTotals[]
  totals: { incoming_huf: number; outgoing_huf: number }
  counts: Record<InvoiceStatus | 'total' | 'provisional', number>
}
