import { useCallback, useRef, useState } from 'react'
import type { DragEvent } from 'react'

import { api } from '../api'
import { UPLOAD_STATE } from '../labels'
import type { UploadState } from '../labels'

const CONCURRENCY = 4 // K10: fájlonkénti kérés, egyszerre 4
const REFRESH_EVERY = 20 // hosszú kötegnél ennyi fájlonként frissül a kimutatás is

interface Item {
  id: number
  name: string
  state: UploadState
  message?: string
}

interface Props {
  /** A kimutatás és a lista újratöltése (köteg közben is, majd a végén). */
  onProcessed: () => void
}

function isPdf(file: File): boolean {
  return file.type === 'application/pdf' || file.name.toLowerCase().endsWith('.pdf')
}

export default function UploadPanel({ onProcessed }: Props) {
  const [items, setItems] = useState<Item[]>([])
  const [dragging, setDragging] = useState(false)
  const [onlyProblems, setOnlyProblems] = useState(false)
  const queue = useRef<{ id: number; file: File }[]>([])
  const active = useRef(0)
  const nextId = useRef(1)
  const sinceRefresh = useRef(0)
  const inputRef = useRef<HTMLInputElement>(null)

  const update = useCallback(
    (id: number, patch: Partial<Item>) =>
      setItems((prev) => prev.map((it) => (it.id === id ? { ...it, ...patch } : it))),
    [],
  )

  // Egy worker addig vesz ki fájlt a sorból, amíg van; egyszerre legfeljebb CONCURRENCY worker fut.
  const worker = useCallback(async () => {
    let job = queue.current.shift()
    while (job) {
      update(job.id, { state: 'uploading' })
      try {
        const res = await api.upload(job.file)
        // A sima „Feldolgozva” üzenetet nem ismételjük; az ideiglenes / árfolyamra váró állapotot igen.
        const plain = res.result === 'created' && res.invoice?.status === 'ok' && !res.invoice.fx_provisional
        update(job.id, { state: res.result, message: plain ? undefined : res.message })
      } catch (err) {
        update(job.id, { state: 'error', message: (err as Error).message })
      }
      sinceRefresh.current += 1
      if (sinceRefresh.current >= REFRESH_EVERY && queue.current.length > 0) {
        sinceRefresh.current = 0
        onProcessed()
      }
      job = queue.current.shift()
    }
    active.current -= 1
    if (active.current === 0) {
      sinceRefresh.current = 0
      onProcessed()
    }
  }, [onProcessed, update])

  const pump = useCallback(() => {
    // A worker szinkronban (az első await előtt) kiveszi az első feladatát, így a sor hossza azonnal csökken.
    while (active.current < CONCURRENCY && queue.current.length > 0) {
      active.current += 1
      void worker()
    }
  }, [worker])

  const addFiles = (files: FileList | File[]) => {
    const list = Array.from(files)
    if (list.length === 0) return
    const fresh: Item[] = []
    for (const file of list) {
      const id = nextId.current++
      if (!isPdf(file)) {
        fresh.push({ id, name: file.name, state: 'error', message: 'Nem PDF-fájl, nem töltöttük fel.' })
        continue
      }
      fresh.push({ id, name: file.name, state: 'waiting' })
      queue.current.push({ id, file })
    }
    setItems((prev) => [...prev, ...fresh])
    pump()
  }

  const onDrop = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault()
    setDragging(false)
    addFiles(e.dataTransfer.files)
  }

  const total = items.length
  const finished = items.filter((it) => it.state !== 'waiting' && it.state !== 'uploading').length
  const running = finished < total
  const counts = items.reduce<Partial<Record<UploadState, number>>>((acc, it) => {
    acc[it.state] = (acc[it.state] ?? 0) + 1
    return acc
  }, {})
  const problems = (counts.review ?? 0) + (counts.rejected ?? 0) + (counts.error ?? 0)
  const shown = onlyProblems ? items.filter((it) => ['review', 'rejected', 'error'].includes(it.state)) : items

  return (
    <section className="rounded-xl border border-hairline bg-surface p-5 shadow-sm" aria-labelledby="upload-title">
      <h2 id="upload-title" className="text-lg font-semibold">Számlák feltöltése</h2>

      <div
        onDragOver={(e) => {
          e.preventDefault()
          setDragging(true)
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
        onClick={() => inputRef.current?.click()}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault()
            inputRef.current?.click()
          }
        }}
        role="button"
        tabIndex={0}
        className={`mt-3 flex cursor-pointer flex-col items-center justify-center rounded-lg border-2 border-dashed px-4 py-8 text-center transition-colors ${
          dragging ? 'border-incoming bg-incoming/5' : 'border-axis hover:border-ink-3 hover:bg-page'
        }`}
      >
        <p className="font-medium">Húzza ide a PDF-számlákat, vagy kattintson a tallózáshoz</p>
        <p className="mt-1 text-sm text-ink-2">Egyszerre több fájl is feltölthető (a már feldolgozott számlák nem duplikálódnak).</p>
        <input
          ref={inputRef}
          type="file"
          accept="application/pdf,.pdf"
          multiple
          className="hidden"
          onChange={(e) => {
            if (e.target.files) addFiles(e.target.files)
            e.target.value = '' // ugyanaz a fájl újra kiválasztható legyen
          }}
        />
      </div>

      {total > 0 && (
        <div className="mt-4">
          <div className="flex flex-wrap items-center justify-between gap-2 text-sm">
            <p className="tabular font-medium" aria-live="polite">
              {running ? `Feldolgozás: ${finished} / ${total}` : `Kész: ${total} fájl feldolgozva`}
            </p>
            <div className="flex flex-wrap gap-x-4 gap-y-1 text-ink-2">
              {(['created', 'duplicate', 'review', 'rejected', 'error'] as const).map((s) =>
                counts[s] ? (
                  <span key={s} className="tabular">
                    <span className={UPLOAD_STATE[s].iconClass} aria-hidden>{UPLOAD_STATE[s].icon}</span>{' '}
                    {UPLOAD_STATE[s].label}: {counts[s]}
                  </span>
                ) : null,
              )}
            </div>
          </div>
          <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-hairline" role="progressbar"
               aria-valuemin={0} aria-valuemax={total} aria-valuenow={finished}>
            <div className="h-full rounded-full bg-incoming transition-[width]" style={{ width: `${(finished / total) * 100}%` }} />
          </div>

          <div className="mt-3 flex items-center justify-between gap-2 text-sm">
            <label className="flex items-center gap-2 text-ink-2">
              <input type="checkbox" checked={onlyProblems} onChange={(e) => setOnlyProblems(e.target.checked)} />
              Csak a problémás fájlok ({problems})
            </label>
            <button
              type="button"
              disabled={running}
              onClick={() => setItems([])}
              className="rounded-md px-2 py-1 text-ink-2 hover:bg-page enabled:hover:cursor-pointer disabled:opacity-40"
            >
              Napló törlése
            </button>
          </div>

          <ul className="mt-2 max-h-72 divide-y divide-hairline overflow-y-auto rounded-lg border border-hairline text-sm">
            {shown.map((it) => {
              const badge = UPLOAD_STATE[it.state]
              return (
                <li key={it.id} className="flex items-start gap-3 px-3 py-2">
                  <span className={`inline-block w-4 shrink-0 text-center ${badge.iconClass}`} aria-hidden>{badge.icon}</span>
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-baseline gap-x-3">
                      <span className="truncate font-medium" title={it.name}>{it.name}</span>
                      <span className="text-xs text-ink-2">{badge.label}</span>
                    </div>
                    {it.message && <p className="mt-0.5 text-ink-2">{it.message}</p>}
                  </div>
                </li>
              )
            })}
            {shown.length === 0 && <li className="px-3 py-2 text-ink-2">Nincs problémás fájl.</li>}
          </ul>
        </div>
      )}
    </section>
  )
}
