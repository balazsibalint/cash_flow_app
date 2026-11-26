import { CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'

import { formatHuf, formatShort } from '../format'
import type { MonthPoint } from '../types'

const INK_2 = '#52514e'
const HAIRLINE = '#e1e0d9'
const AXIS = '#c3c2b7'
const SURFACE = '#fcfcfb'

const SERIES = [
  { key: 'incoming_huf', name: 'Bejövő', color: '#2a78d6' },
  { key: 'outgoing_huf', name: 'Kimenő', color: '#eb6834' },
] as const

interface Props {
  months: MonthPoint[]
}

function ChartTooltip({ active, point }: { active?: boolean; point?: MonthPoint }) {
  if (!active || !point) return null
  return (
    <div className="rounded-lg border border-hairline bg-surface px-3 py-2 text-sm shadow-md">
      <p className="font-medium">{point.month}</p>
      {SERIES.map((s) => (
        <p key={s.key} className="tabular mt-1 flex items-center gap-2">
          <span className="inline-block h-0.5 w-3 rounded" style={{ background: s.color }} aria-hidden />
          <span className="text-ink-2">{s.name}:</span>
          <span className="ml-auto pl-3 font-medium">{formatHuf(point[s.key])}</span>
        </p>
      ))}
    </div>
  )
}

/** Közvetlen felirat a vonal végén (a jelmagyarázat mellett): a sorozat neve, szövegszínnel. */
function endLabel(name: string, lastIndex: number) {
  return (props: { x?: number | string; y?: number | string; index?: number }) => {
    if (props.index !== lastIndex) return <g />
    return (
      <text x={Number(props.x) + 8} y={Number(props.y)} dy={4} fontSize={12} fill={INK_2}>
        {name}
      </text>
    )
  }
}

export default function CashflowChart({ months }: Props) {
  const last = months.length - 1
  // Összetartó végpontoknál a feliratok egymásra csúsznának – ilyenkor a jelmagyarázat azonosít.
  const max = Math.max(1, ...months.flatMap((m) => [m.incoming_huf, m.outgoing_huf]))
  const end = months[last]
  const endLabels = !!end && Math.abs(end.incoming_huf - end.outgoing_huf) / max >= 0.08

  return (
    <section className="rounded-xl border border-hairline bg-surface p-5 shadow-sm" aria-labelledby="chart-title">
      <h2 id="chart-title" className="text-lg font-semibold">Pénzforgalom fizetési határidő szerint</h2>
      <p className="text-sm text-ink-2">Bruttó összegek forintban, havonta (csak a „Rendben” státuszú számlák).</p>

      {months.length === 0 ? (
        <p className="py-16 text-center text-ink-2">Még nincs feldolgozott számla. Töltsön fel PDF-eket a fenti panelen.</p>
      ) : (
        <div className="mt-4 h-80 w-full">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={months} margin={{ top: 8, right: 64, bottom: 24, left: 16 }}>
              <CartesianGrid vertical={false} stroke={HAIRLINE} />
              <XAxis
                dataKey="month"
                stroke={AXIS}
                tick={{ fill: INK_2, fontSize: 12 }}
                tickMargin={8}
                label={{ value: 'Fizetési határidő (hónap)', position: 'bottom', offset: 8, fill: INK_2, fontSize: 12 }}
              />
              <YAxis
                stroke={AXIS}
                tick={{ fill: INK_2, fontSize: 12 }}
                tickFormatter={(v: number) => formatShort(v)}
                width={64}
                label={{ value: 'Bruttó összeg (Ft)', angle: -90, position: 'insideLeft', offset: -4, fill: INK_2, fontSize: 12, style: { textAnchor: 'middle' } }}
              />
              <Tooltip
                cursor={{ stroke: AXIS, strokeWidth: 1 }}
                content={({ active, payload }) => (
                  <ChartTooltip active={active} point={payload?.[0]?.payload as MonthPoint | undefined} />
                )}
              />
              <Legend verticalAlign="top" align="right" height={32} iconType="plainline"
                      formatter={(value: string) => <span style={{ color: INK_2 }}>{value}</span>} />
              {SERIES.map((s) => (
                <Line
                  key={s.key}
                  type="linear"
                  dataKey={s.key}
                  name={s.name}
                  stroke={s.color}
                  strokeWidth={2}
                  strokeLinejoin="round"
                  strokeLinecap="round"
                  dot={{ r: 4, fill: s.color, stroke: SURFACE, strokeWidth: 2 }}
                  activeDot={{ r: 5, fill: s.color, stroke: SURFACE, strokeWidth: 2 }}
                  label={endLabels ? endLabel(s.name, last) : false}
                  isAnimationActive={false}
                />
              ))}
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}
    </section>
  )
}
