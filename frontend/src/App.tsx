import { useCallback, useEffect, useState } from 'react'

import { api } from './api'
import CashflowChart from './components/CashflowChart'
import ConfirmDialog from './components/ConfirmDialog'
import InvoiceTable from './components/InvoiceTable'
import PartnerTable from './components/PartnerTable'
import UploadPanel from './components/UploadPanel'
import { formatHuf } from './format'
import type { Invoice, Report } from './types'

type DeleteTarget = Invoice | 'all' | null

function StatTile({ label, value, sub, swatch }: { label: string; value: string; sub?: string; swatch?: string }) {
  return (
    <div className="rounded-xl border border-hairline bg-surface px-4 py-3 shadow-sm">
      <p className="flex items-center gap-2 text-sm text-ink-2">
        {swatch && <span className="inline-block h-0.5 w-3 rounded" style={{ background: swatch }} aria-hidden />}
        {label}
      </p>
      <p className="tabular mt-1 text-2xl font-semibold">{value}</p>
      {sub && <p className="mt-0.5 text-xs text-ink-2">{sub}</p>}
    </div>
  )
}

export default function App() {
  const [report, setReport] = useState<Report | null>(null)
  const [invoices, setInvoices] = useState<Invoice[]>([])
  const [loadError, setLoadError] = useState<string | null>(null)
  const [deleteTarget, setDeleteTarget] = useState<DeleteTarget>(null)
  const [deleting, setDeleting] = useState(false)
  const [actionError, setActionError] = useState<string | null>(null)

  const reload = useCallback(() => {
    Promise.all([api.report(), api.invoices()])
      .then(([r, list]) => {
        setReport(r)
        setInvoices(list)
        setLoadError(null)
      })
      .catch((err: Error) => setLoadError(err.message))
  }, [])

  useEffect(() => {
    reload()
  }, [reload])

  const confirmDelete = async () => {
    if (!deleteTarget) return
    setDeleting(true)
    setActionError(null)
    try {
      if (deleteTarget === 'all') await api.deleteAll()
      else await api.deleteInvoice(deleteTarget.id)
      setDeleteTarget(null)
      reload()
    } catch (err) {
      setActionError((err as Error).message)
    } finally {
      setDeleting(false)
    }
  }

  const counts = report?.counts
  // Az elutasított bizonylatok sehol nem jelennek meg (csak a feltöltési naplóban); az „Összes törlése” őket is törli.
  const attention = counts ? counts.review + counts.pending_fx + counts.error : 0
  const listed = invoices.filter((inv) => inv.status !== 'rejected')
  const storedTotal = counts?.total ?? invoices.length

  return (
    <div className="min-h-screen">
      <header className="border-b border-hairline bg-surface">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-3 px-4 py-4 sm:px-6">
          <div>
            <h1 className="text-xl font-semibold">Számlafeldolgozó és cash flow kimutatás</h1>
            <p className="text-sm text-ink-2">Bejövő és kimenő számlák forintban, az MNB hivatalos árfolyamával.</p>
          </div>
          <div className="flex items-center gap-3 text-sm">
            <button
              type="button"
              disabled={storedTotal === 0}
              onClick={() => setDeleteTarget('all')}
              className="rounded-md border border-hairline px-3 py-1.5 text-critical hover:bg-critical/10 enabled:hover:cursor-pointer disabled:opacity-40"
            >
              Összes törlése
            </button>
          </div>
        </div>
      </header>

      <main className="mx-auto flex max-w-7xl flex-col gap-6 px-4 py-6 sm:px-6">
        {loadError && (
          <div role="alert" className="rounded-lg border border-critical/40 bg-critical/5 px-4 py-3 text-sm">
            <span className="text-critical" aria-hidden>✗</span> Az adatok nem tölthetők be: {loadError}{' '}
            <button type="button" onClick={reload} className="ml-2 underline hover:cursor-pointer">Újra</button>
          </div>
        )}

        <UploadPanel onProcessed={reload} />

        {report && (
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            <StatTile label="Összes bejövő" swatch="#2a78d6" value={formatHuf(report.totals.incoming_huf)} sub="kapott számlák, bruttó" />
            <StatTile label="Összes kimenő" swatch="#eb6834" value={formatHuf(report.totals.outgoing_huf)} sub="kiállított számlák, bruttó" />
            <StatTile
              label="Kimutatásban"
              value={`${report.counts.ok} számla`}
              sub={report.counts.provisional ? `ebből ${report.counts.provisional} ideiglenes árfolyammal` : undefined}
            />
            <StatTile label="Figyelmet igényel" value={`${attention} számla`} />
          </div>
        )}

        <CashflowChart months={report?.months ?? []} />
        <PartnerTable partners={report?.partners ?? []} />
        <InvoiceTable invoices={listed} onDelete={setDeleteTarget} />
      </main>

      <ConfirmDialog
        open={deleteTarget !== null}
        title={deleteTarget === 'all' ? 'Összes számla törlése' : 'Számla törlése'}
        confirmLabel="Törlés"
        busy={deleting}
        onConfirm={confirmDelete}
        onCancel={() => {
          setDeleteTarget(null)
          setActionError(null)
        }}
      >
        {deleteTarget === 'all' ? (
          <p>Mind a(z) {storedTotal} feltöltött számla (az elutasítottakat is beleértve) és a hozzájuk tartozó PDF-ek véglegesen törlődnek. Az MNB-árfolyamok gyorsítótára megmarad.</p>
        ) : deleteTarget ? (
          <p>
            A(z) <strong className="text-ink">{deleteTarget.invoice_number ?? deleteTarget.filename}</strong> számla és a PDF-je
            véglegesen törlődik.
          </p>
        ) : null}
        {actionError && <p className="mt-2 text-critical">{actionError}</p>}
      </ConfirmDialog>
    </div>
  )
}
