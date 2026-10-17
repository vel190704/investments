"use client";

import { CartesianGrid, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { SeriesPoint } from "@/lib/api";
import { formatDate, formatINR } from "@/lib/format";

const VALUE = "var(--series-1)";
const INVESTED = "var(--series-2)";

function compact(paise: number) {
  const r = paise / 100;
  if (r >= 1e7) return `₹${(r / 1e7).toFixed(1)}Cr`;
  if (r >= 1e5) return `₹${(r / 1e5).toFixed(1)}L`;
  if (r >= 1e3) return `₹${(r / 1e3).toFixed(1)}k`;
  return `₹${r.toFixed(0)}`;
}

export function GrowthChart({ points }: { points: SeriesPoint[] }) {
  const real = points.filter((p) => !p.gap);
  const last = real[real.length - 1];
  const gaps = points.filter((p) => p.gap);
  return (
    <div className="flex flex-col gap-2">
      {/* legend (2 series) — identity never by colour alone: solid vs dashed too */}
      <div className="flex flex-wrap gap-4 text-xs text-muted-foreground">
        <span className="inline-flex items-center gap-1.5"><span className="h-0.5 w-4" style={{ background: VALUE }} />Market value {last && <b className="tnum text-foreground">{formatINR(last.value_paise)}</b>}</span>
        <span className="inline-flex items-center gap-1.5"><span className="h-0 w-4 border-t-2 border-dashed" style={{ borderColor: INVESTED }} />Invested {last && <b className="tnum text-foreground">{formatINR(last.invested_paise)}</b>}</span>
        <span>○ = partial snapshot (some holdings had no price)</span>
        {gaps.length > 0 && <span>┆ = no snapshot that day ({gaps.length}); the line breaks, nothing is filled in</span>}
      </div>
      <div className="h-64 w-full" role="img" aria-label="Portfolio value and invested amount by snapshot date; values in the table below">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={points} margin={{ top: 8, right: 12, bottom: 0, left: 4 }}>
            <CartesianGrid stroke="var(--border)" vertical={false} />
            <XAxis dataKey="date" tickFormatter={(d) => formatDate(d).slice(0, 6)} stroke="var(--muted-foreground)"
                   tick={{ fontSize: 11 }} tickLine={false} axisLine={{ stroke: "var(--border)" }} />
            <YAxis tickFormatter={compact} stroke="var(--muted-foreground)" tick={{ fontSize: 11 }} width={56}
                   tickLine={false} axisLine={false} domain={["auto", "auto"]} />
            <Tooltip
              isAnimationActive={false}
              cursor={{ stroke: "var(--muted-foreground)", strokeDasharray: "3 3" }}
              content={({ active, payload }) => {
                if (!active || !payload?.length) return null;
                const p = payload[0].payload as SeriesPoint;
                return (
                  <div className="rounded-md border border-border bg-popover px-2.5 py-1.5 text-xs shadow-sm">
                    <div className="font-medium">{formatDate(p.date)}{p.partial ? " · partial" : ""}</div>
                    {p.gap && <div className="text-muted-foreground">No snapshot{p.reason ? ` — ${p.reason}` : ""}</div>}
                    {!p.gap && <div className="tnum">Value {formatINR(p.value_paise)}</div>}
                    {!p.gap && <div className="tnum text-muted-foreground">Invested {formatINR(p.invested_paise)}</div>}
                    {p.partial && <div className="text-muted-foreground">Unpriced: {p.unpriced.length} holding(s)</div>}
                  </div>
                );
              }}
            />
            {gaps.map((g) => <ReferenceLine key={g.date} x={g.date} stroke="var(--muted-foreground)" strokeDasharray="1 3" />)}
            <Line type="linear" connectNulls={false} dataKey="invested_paise" stroke={INVESTED} strokeWidth={2} strokeDasharray="5 4"
                  dot={gaps.length ? { r: 2.5, fill: INVESTED, stroke: INVESTED } : false} isAnimationActive={false} />
            <Line type="linear" connectNulls={false} dataKey="value_paise" stroke={VALUE} strokeWidth={2} isAnimationActive={false}
                  dot={(props) => {
                    const { cx, cy, payload, index } = props as { cx: number; cy: number; payload: SeriesPoint; index: number };
                    if (payload.gap || payload.value_paise === null) return <g key={index} />;
                    return <circle key={index} cx={cx} cy={cy} r={4} stroke={VALUE} strokeWidth={2}
                                   fill={payload.partial ? "var(--card)" : VALUE} />;
                  }} />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
