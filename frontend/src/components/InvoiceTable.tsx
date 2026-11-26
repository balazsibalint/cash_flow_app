import { Fragment, useMemo, useState } from 'react'
import type { ReactNode } from 'react'

import { api } from '../api'
import { formatDate, formatDecimal, formatHuf, formatMoney } from '../format'
import { DIRECTION, METHOD, STATUS } from '../labels'
import type { Direction, Invoice, InvoiceStatus } from '../types'

interface Props {
  invoices: Invoice[]
  onDelete: (invoice: Invoice) => void
}

type SortKey = 'status' | 'direction' | 'invoice_number' | 'partner' | 'issue_date' | 'supply_date' | 'due_date' | 'gross_huf' | 'fx_rate_date'

const STATUS_ORDER: InvoiceStatus[] = ['ok', 'review', 'pending_fx', 'rejected', 'error']
// Az elutasított bizonylatok nem kerülnek a listába, így szűrni sem lehet rájuk.
const FILTER_STATUSES = STATUS_ORDER.filter((s) => s !== 'rejected')
const PAGE_SIZES = [10, 25, 50, 100] as const

function sortValue(inv: Invoice, key: SortKey): string | number | null {
  switch (key) {
    case 'status':
      return STATUS_ORDER.indexOf(inv.status)
    case 'partner':
      return inv.partner?.display_name.toLocaleLowerCase('hu') ?? null
    case 'invoice_number':
      return inv.invoice_number?.toLocaleLowerCase('hu') ?? null
    default:
      return inv[key]
  }
}

function compare(a: string | number | null, b: string | number | null): number {
  if (a === null && b === null) return 0
  if (a === null) return 1 // az üres értékek mindig a végére
  if (b === null) return -1
  if (typeof a === 'number' && typeof b === 'number') return a - b
  return String(a).localeCompare(String(b), 'hu')
}

function Party({ name, tax }: { name: string | null; tax: string | null }) {
  return (
    <div className="max-w-48">
      <div className="truncate" title={name ?? undefined}>{name ?? '–'}</div>
      <div className="text-xs text-ink-3">{tax ?? '–'}</div>
    </div>
  )
}

function DateCell({ value, inferred }: { value: string | null; inferred?: boolean }) {
  return (
    <span title={inferred ? 'Nem szerepel a számlán, kikövetkeztetett érték' : undefined}>
      {formatDate(value)}
      {inferred && <span className="text-warning" aria-label="kikövetkeztetett"> *</span>}
    </span>
  )
}

const selectClass = 'rounded-md border border-hairline bg-surface px-2 py-1.5 text-sm'

export default function InvoiceTable({ invoices, onDelete }: Props) {
  const [status, setStatus] = useState<InvoiceStatus | ''>('')
  const [direction, setDirection] = useState<Direction | ''>('')
  const [partnerId, setPartnerId] = useState<number | ''>('')
  const [search, setSearch] = useState('')
  const [sort, setSort] = useState<{ key: SortKey; desc: boolean } | null>(null)
  const [expanded, setExpanded] = useState<Set<number>>(new Set())
  const [pageSize, setPageSize] = useState<number>(PAGE_SIZES[0])
  const [page, setPage] = useState(0)

  const partners = useMemo(() => {
    const map = new Map<number, string>()
    for (const inv of invoices) if (inv.partner) map.set(inv.partner.id, inv.partner.display_name)
    return [...map.entries()].sort((a, b) => a[1].localeCompare(b[1], 'hu'))
  }, [invoices])

  const rows = useMemo(() => {
    const q = search.trim().toLocaleLowerCase('hu')
    let list = invoices.filter(
      (inv) =>
        (!status || inv.status === status) &&
        (!direction || inv.direction === direction) &&
        (partnerId === '' || inv.partner?.id === partnerId) &&
        (!q ||
          [inv.invoice_number, inv.filename, inv.seller_name, inv.buyer_name, inv.seller_tax, inv.buyer_tax]
            .some((v) => v?.toLocaleLowerCase('hu').includes(q))),
    )
    if (sort) {
      list = [...list].sort((a, b) => {
        const c = compare(sortValue(a, sort.key), sortValue(b, sort.key))
        return sort.desc ? -c : c
      })
    }
    return list
  }, [invoices, status, direction, partnerId, search, sort])

  const pageCount = Math.max(1, Math.ceil(rows.length / pageSize))
  // Törlés vagy szűrés után az oldalszám túlfuthat a végén – ilyenkor az utolsó oldal látszik.
  const current = Math.min(page, pageCount - 1)
  const pageRows = rows.slice(current * pageSize, (current + 1) * pageSize)

  const goTo = (next: number) => setPage(next)

  const toggleSort = (key: SortKey) => {
    setSort((prev) => (prev?.key !== key ? { key, desc: false } : prev.desc ? null : { key, desc: true }))
    goTo(0)
  }

  const toggleRow = (id: number) =>
    setExpanded((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })

  const th = (label: ReactNode, sortKey?: SortKey, right = false) => {
    const active = sortKey && sort?.key === sortKey
    return (
      <th
        scope="col"
        aria-sort={active ? (sort!.desc ? 'descending' : 'ascending') : undefined}
        className={`whitespace-nowrap border-b border-axis px-2 py-2 font-medium text-ink-2 ${right ? 'text-right' : 'text-left'}`}
      >
        {sortKey ? (
          <button type="button" onClick={() => toggleSort(sortKey)} className="inline-flex items-center gap-1 hover:cursor-pointer hover:text-ink">
            {label}
            <span className={active ? 'text-ink' : 'text-axis'} aria-hidden>
              {active ? (sort!.desc ? '▼' : '▲') : '↕'}
            </span>
          </button>
        ) : (
          label
        )}
      </th>
    )
  }

  const filtered = status || direction || partnerId !== '' || search

  return (
    <section className="rounded-xl border border-hairline bg-surface p-5 shadow-sm" aria-labelledby="invoices-title">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <div>
          <h2 id="invoices-title" className="text-lg font-semibold">Számlák</h2>
          <p className="text-sm text-ink-2">A kinyert adatok, a felhasznált MNB árfolyam és a forintösszeg.</p>
        </div>
        <p className="tabular text-sm text-ink-2">{filtered ? `${rows.length} / ${invoices.length} számla` : `${invoices.length} számla`}</p>
      </div>

      <div className="mt-4 flex flex-wrap gap-2">
        <input
          type="search"
          value={search}
          onChange={(e) => { setSearch(e.target.value); goTo(0) }}
          placeholder="Keresés: számlaszám, név, adószám, fájl… alapján"
          aria-label="Keresés"
          className={`${selectClass} min-w-64 flex-1`}
        />
        <select value={status} onChange={(e) => { setStatus(e.target.value as InvoiceStatus | ''); goTo(0) }} aria-label="Státusz" className={selectClass}>
          <option value="">Minden státusz</option>
          {FILTER_STATUSES.map((s) => <option key={s} value={s}>{STATUS[s].label}</option>)}
        </select>
        <select value={direction} onChange={(e) => { setDirection(e.target.value as Direction | ''); goTo(0) }} aria-label="Irány" className={selectClass}>
          <option value="">Minden irány</option>
          <option value="incoming">{DIRECTION.incoming}</option>
          <option value="outgoing">{DIRECTION.outgoing}</option>
        </select>
        <select value={partnerId} onChange={(e) => { setPartnerId(e.target.value ? Number(e.target.value) : ''); goTo(0) }} aria-label="Partner" className={`${selectClass} max-w-64`}>
          <option value="">Minden partner</option>
          {partners.map(([id, name]) => <option key={id} value={id}>{name}</option>)}
        </select>
        {filtered && (
          <button type="button" className="rounded-md px-2 py-1.5 text-sm text-ink-2 hover:cursor-pointer hover:bg-page"
                  onClick={() => { setStatus(''); setDirection(''); setPartnerId(''); setSearch(''); goTo(0) }}>
            Szűrők törlése
          </button>
        )}
      </div>

      {invoices.length === 0 ? (
        <p className="py-8 text-center text-ink-2">Még nincs feltöltött számla.</p>
      ) : (
        <>
        <div className="relative mt-3 overflow-x-auto rounded-lg border border-hairline">
          <table className="tabular w-full text-sm">
            <thead>
              <tr>
                {th(<span className="sr-only">Részletek</span>)}
                {th('Státusz', 'status')}
                {th('Irány', 'direction')}
                {th('Számlaszám', 'invoice_number')}
                {th('Partner', 'partner')}
                {th('Kiállító')}
                {th('Vevő')}
                {th('Kiállítás', 'issue_date')}
                {th('Teljesítés', 'supply_date')}
                {th('Határidő', 'due_date')}
                {th('Eredeti összeg', undefined, true)}
                {th('Árfolyam', undefined, true)}
                {th('Árfolyam napja', 'fx_rate_date')}
                {th('Összeg (Ft)', 'gross_huf', true)}
                {th('Mód')}
                {th(<span className="sr-only">Műveletek</span>)}
              </tr>
            </thead>
            <tbody>
              {pageRows.map((inv) => {
                const st = STATUS[inv.status]
                const open = expanded.has(inv.id)
                const warnings = inv.messages.filter((m) => m.level !== 'info').length
                return (
                  <Fragment key={inv.id}>
                    <tr
                      onClick={(e) => {
                        // A sor gombjai/linkjei a saját dolgukat végzik; szövegkijelöléskor sem nyílik le a sor.
                        if ((e.target as HTMLElement).closest('a, button') || window.getSelection()?.toString()) return
                        toggleRow(inv.id)
                      }}
                      className={`cursor-pointer border-b border-hairline align-top hover:bg-page ${inv.status === 'ok' ? '' : 'text-ink-2'}`}
                    >
                      <td className="px-2 py-2">
                        <button
                          type="button"
                          onClick={() => toggleRow(inv.id)}
                          aria-expanded={open}
                          aria-label={open ? 'Részletek elrejtése' : 'Részletek megjelenítése'}
                          className="inline-flex items-center gap-1 rounded px-1 text-ink-2 hover:cursor-pointer hover:bg-hairline"
                        >
                          <span aria-hidden>{open ? '▾' : '▸'}</span>
                          {warnings > 0 && <span className="text-xs text-warning" title={`${warnings} figyelmeztetés / hiba`}>⚠{warnings}</span>}
                        </button>
                      </td>
                      <td className="whitespace-nowrap px-2 py-2" title={inv.status_reason ?? st.hint}>
                        <span className={st.iconClass} aria-hidden>{st.icon}</span> <span className="text-ink">{st.label}</span>
                      </td>
                      <td className="whitespace-nowrap px-2 py-2">{inv.direction ? DIRECTION[inv.direction] : '–'}</td>
                      <td className="whitespace-nowrap px-2 py-2 font-medium text-ink">{inv.invoice_number ?? '–'}</td>
                      <td className="px-2 py-2">
                        <div className="max-w-48 truncate" title={inv.partner?.display_name}>{inv.partner?.display_name ?? '–'}</div>
                      </td>
                      <td className="px-2 py-2"><Party name={inv.seller_name} tax={inv.seller_tax} /></td>
                      <td className="px-2 py-2"><Party name={inv.buyer_name} tax={inv.buyer_tax} /></td>
                      <td className="whitespace-nowrap px-2 py-2"><DateCell value={inv.issue_date} /></td>
                      <td className="whitespace-nowrap px-2 py-2"><DateCell value={inv.supply_date} inferred={inv.supply_date_inferred} /></td>
                      <td className="whitespace-nowrap px-2 py-2"><DateCell value={inv.due_date} inferred={inv.due_date_inferred} /></td>
                      <td className="whitespace-nowrap px-2 py-2 text-right">{formatMoney(inv.gross_amount, inv.currency)}</td>
                      <td className="whitespace-nowrap px-2 py-2 text-right">
                        {inv.fx_rate === null ? '–' : (
                          <>
                            {formatDecimal(inv.fx_rate)}
                            {inv.fx_unit !== null && inv.fx_unit !== 1 && <span className="text-ink-3"> / {inv.fx_unit} {inv.currency}</span>}
                          </>
                        )}
                      </td>
                      <td className="whitespace-nowrap px-2 py-2">
                        {formatDate(inv.fx_rate_date)}
                        {inv.fx_provisional && (
                          <span className="ml-1 rounded bg-warning/20 px-1.5 py-0.5 text-xs text-ink"
                                title="A teljesítés napjára még nincs MNB-jegyzés; a legutolsó ismert árfolyamot használtuk.">
                            ideiglenes
                          </span>
                        )}
                      </td>
                      <td className="whitespace-nowrap px-2 py-2 text-right font-medium text-ink">{formatHuf(inv.gross_huf, false)}</td>
                      <td className="whitespace-nowrap px-2 py-2">{inv.extraction_method ? METHOD[inv.extraction_method] : '–'}</td>
                      <td className="whitespace-nowrap px-2 py-2 text-right">
                        <a href={api.pdfUrl(inv.id)} target="_blank" rel="noreferrer"
                           className="rounded px-1.5 py-0.5 text-incoming hover:bg-incoming/10">PDF</a>
                        <button type="button" onClick={() => onDelete(inv)}
                                className="ml-1 rounded px-1.5 py-0.5 text-critical hover:cursor-pointer hover:bg-critical/10"
                                aria-label={`${inv.invoice_number ?? inv.filename} törlése`}>
                          Törlés
                        </button>
                      </td>
                    </tr>
                    {open && (
                      <tr className="border-b border-hairline bg-page">
                        <td />
                        <td colSpan={15} className="px-2 py-3 text-sm">
                          <dl className="grid grid-cols-[max-content_1fr] gap-x-4 gap-y-1">
                            <dt className="text-ink-2">Fájl</dt><dd>{inv.filename}</dd>
                            <dt className="text-ink-2">Nettó / ÁFA</dt>
                            <dd>{formatMoney(inv.net_amount, inv.currency)} / {formatMoney(inv.vat_amount, inv.currency)}</dd>
                            {inv.status_reason && (<><dt className="text-ink-2">Státusz oka</dt><dd>{inv.status_reason}</dd></>)}
                          </dl>
                          {inv.messages.length > 0 && (
                            <ul className="mt-2 space-y-1">
                              {inv.messages.map((m, i) => (
                                <li key={i} className="flex gap-2">
                                  <span className={m.level === 'error' ? 'text-critical' : m.level === 'warning' ? 'text-warning' : 'text-ink-3'} aria-hidden>
                                    {m.level === 'error' ? '✗' : m.level === 'warning' ? '⚠' : 'ℹ'}
                                  </span>
                                  <span>{m.text}</span>
                                </li>
                              ))}
                            </ul>
                          )}
                        </td>
                      </tr>
                    )}
                  </Fragment>
                )
              })}
              {rows.length === 0 && (
                <tr><td colSpan={16} className="py-6 text-center text-ink-2">Nincs a szűrésnek megfelelő számla.</td></tr>
              )}
            </tbody>
          </table>
        </div>

        <nav className="mt-3 flex flex-wrap items-center justify-between gap-3 text-sm text-ink-2" aria-label="Lapozás">
          <label className="flex items-center gap-2">
            Sorok oldalanként:
            <select
              value={pageSize}
              onChange={(e) => { setPageSize(Number(e.target.value)); goTo(0) }}
              className={selectClass}
            >
              {PAGE_SIZES.map((n) => <option key={n} value={n}>{n}</option>)}
            </select>
          </label>
          <div className="flex items-center gap-1">
            <span className="tabular mr-2">
              {rows.length === 0 ? '0 számla' : `${current * pageSize + 1}–${Math.min((current + 1) * pageSize, rows.length)} / ${rows.length}`}
            </span>
            {[
              { label: '«', title: 'Első oldal', to: 0, disabled: current === 0 },
              { label: '‹', title: 'Előző oldal', to: current - 1, disabled: current === 0 },
              { label: '›', title: 'Következő oldal', to: current + 1, disabled: current >= pageCount - 1 },
              { label: '»', title: 'Utolsó oldal', to: pageCount - 1, disabled: current >= pageCount - 1 },
            ].map((b, i) => (
              <Fragment key={b.title}>
                {i === 2 && <span className="tabular px-2 text-ink">{current + 1}. oldal / {pageCount}</span>}
                <button
                  type="button"
                  onClick={() => goTo(b.to)}
                  disabled={b.disabled}
                  title={b.title}
                  aria-label={b.title}
                  className="min-w-8 rounded-md border border-hairline px-2 py-1 hover:bg-page enabled:hover:cursor-pointer disabled:opacity-40 disabled:hover:bg-transparent"
                >
                  {b.label}
                </button>
              </Fragment>
            ))}
          </div>
        </nav>
        </>
      )}
    </section>
  )
}
