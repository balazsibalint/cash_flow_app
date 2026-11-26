import { useEffect, useRef } from 'react'
import type { ReactNode } from 'react'

interface Props {
  open: boolean
  title: string
  children: ReactNode
  confirmLabel: string
  busy?: boolean
  onConfirm: () => void
  onCancel: () => void
}

/** Törlés-megerősítés (K12). Natív <dialog>: fókuszcsapda és Esc-kezelés a böngészőtől. */
export default function ConfirmDialog({ open, title, children, confirmLabel, busy, onConfirm, onCancel }: Props) {
  const ref = useRef<HTMLDialogElement>(null)

  useEffect(() => {
    const dlg = ref.current
    if (!dlg) return
    if (open && !dlg.open) dlg.showModal()
    if (!open && dlg.open) dlg.close()
  }, [open])

  return (
    <dialog
      ref={ref}
      onCancel={(e) => {
        e.preventDefault()
        if (!busy) onCancel()
      }}
      className="m-auto w-[min(28rem,calc(100vw-2rem))] rounded-xl border border-hairline bg-surface p-0 text-ink shadow-xl backdrop:bg-black/30"
    >
      <div className="p-5">
        <h2 className="text-lg font-semibold">{title}</h2>
        <div className="mt-2 text-sm text-ink-2">{children}</div>
        <div className="mt-5 flex justify-end gap-2">
          <button type="button" onClick={onCancel} disabled={busy}
                  className="rounded-md border border-hairline px-3 py-1.5 text-sm hover:bg-page enabled:hover:cursor-pointer disabled:opacity-50">
            Mégse
          </button>
          <button type="button" onClick={onConfirm} disabled={busy}
                  className="rounded-md bg-critical px-3 py-1.5 text-sm font-medium text-white hover:brightness-95 enabled:hover:cursor-pointer disabled:opacity-50">
            {busy ? 'Törlés…' : confirmLabel}
          </button>
        </div>
      </div>
    </dialog>
  )
}
