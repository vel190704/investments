"use client";

import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip } from "recharts";
import type { AssetClass } from "@/lib/api";
import { formatINR, pctLabel } from "@/lib/format";

// Colour follows the entity (asset class), never its rank or position.
export const ASSET_CLASS_COLOR: Record<string, string> = {
  "Mutual funds": "var(--series-1)",
  "Indian stocks": "var(--series-2)",
  "International ETFs": "var(--series-3)",
  "Indian ETFs": "var(--series-4)",
  Gold: "var(--series-4)",
  "Debt/Cash": "var(--series-5)",
};

export function AssetDonut({ data }: { data: AssetClass[] }) {
  if (!data.length) return <p className="text-sm text-muted-foreground">Data unavailable</p>;
  const rows = data.map((d) => ({ ...d, value: d.value_paise }));
  return (
    <div className="flex flex-col items-center gap-4 sm:flex-row">
      <div className="h-48 w-48 shrink-0" role="img" aria-label="Asset-class allocation donut chart; values listed alongside">
        <ResponsiveContainer width="100%" height="100%">
          <PieChart>
            <Pie
              data={rows}
              dataKey="value"
              nameKey="name"
              innerRadius="62%"
              outerRadius="100%"
              stroke="var(--card)"
              strokeWidth={2}
              isAnimationActive={false}
              startAngle={90}
              endAngle={-270}
            >
              {rows.map((r) => (
                <Cell key={r.name} fill={ASSET_CLASS_COLOR[r.name] ?? "var(--muted-foreground)"} />
              ))}
            </Pie>
            <Tooltip
              isAnimationActive={false}
              content={({ active, payload }) => {
                if (!active || !payload?.length) return null;
                const p = payload[0].payload as AssetClass;
                return (
                  <div className="rounded-md border border-border bg-popover px-2.5 py-1.5 text-xs shadow-sm">
                    <div className="font-medium">{p.name}</div>
                    <div className="tnum text-muted-foreground">
                      {formatINR(p.value_paise)} · {pctLabel(p.display_pct)}
                    </div>
                  </div>
                );
              }}
            />
          </PieChart>
        </ResponsiveContainer>
      </div>
      {/* Legend doubles as the table view and the direct labels. */}
      <table className="w-full text-sm">
        <tbody>
          {data.map((d) => (
            <tr key={d.name} className="border-b border-border last:border-0">
              <td className="py-1.5 pr-2">
                <span className="inline-flex items-center gap-2">
                  <span aria-hidden className="inline-block size-2.5 rounded-sm" style={{ background: ASSET_CLASS_COLOR[d.name] }} />
                  {d.name}
                </span>
              </td>
              <td className="tnum py-1.5 pr-2 text-right font-medium">{pctLabel(d.display_pct)}</td>
              <td className="tnum py-1.5 text-right text-muted-foreground">{formatINR(d.value_paise)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
