import { formatHuf } from '../format'
import type { PartnerTotals } from '../types'

interface Props {
  partners: PartnerTotals[]
}

const ROWS = [
  { key: 'incoming_huf', label: 'Össz. bejövő', color: '#2a78d6' },
  { key: 'outgoing_huf', label: 'Össz. kimenő', color: '#eb6834' },
] as const

/** Transzponált tábla: oszlopok = partnerek (forgalom szerint csökkenően, K13), sorok = bejövő / kimenő. */
export default function PartnerTable({ partners }: Props) {
  return (
    <section className="rounded-xl border border-hairline bg-surface p-5 shadow-sm" aria-labelledby="partners-title">
      <h2 id="partners-title" className="text-lg font-semibold">Partnerenkénti összesítő</h2>
      <p className="text-sm text-ink-2">
        Bruttó forintösszegek. Egy partner egy oszlop akkor is, ha a nevét eltérően írják (az azonosítás az adószám
        alapján történik).
      </p>

      {partners.length === 0 ? (
        <p className="py-8 text-center text-ink-2">Még nincs partner.</p>
      ) : (
        <div className="relative mt-4 overflow-x-auto rounded-lg border border-hairline">
          <table className="tabular border-separate border-spacing-0 text-sm">
            <thead>
              <tr>
                <th className="sticky left-0 z-10 border-b border-r border-hairline bg-surface px-3 py-2" />
                {partners.map((p) => (
                  <th
                    key={p.partner_id}
                    scope="col"
                    title={p.name}
                    className="min-w-36 max-w-52 border-b border-hairline px-3 py-2 text-right align-bottom font-medium"
                  >
                    <span className="line-clamp-2">{p.name}</span>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {ROWS.map((row, i) => (
                <tr key={row.key}>
                  <th
                    scope="row"
                    className={`sticky left-0 z-10 whitespace-nowrap border-r border-hairline bg-surface px-3 py-2 text-left font-medium ${i === 0 ? 'border-b' : ''}`}
                  >
                    <span className="mr-2 inline-block h-0.5 w-3 rounded align-middle" style={{ background: row.color }} aria-hidden />
                    {row.label}
                  </th>
                  {partners.map((p) => (
                    <td
                      key={p.partner_id}
                      className={`whitespace-nowrap px-3 py-2 text-right ${i === 0 ? 'border-b border-hairline' : ''} ${p[row.key] === 0 ? 'text-ink-3' : ''}`}
                    >
                      {formatHuf(p[row.key], false)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}
