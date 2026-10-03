"use client";

import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { ProjectionScenario } from "@/lib/api";
import { formatINR } from "@/lib/format";

// Ordinal blue steps: Conservative < Base < Higher (one hue, light -> dark). Custom = orange slot.
export const SCENARIO_COLOR: Record<string, string> = {
  Conservative: "var(--ord-1)", Base: "var(--ord-2)", Higher: "var(--ord-3)", Custom: "var(--series-2)",
};

function compact(paise: number) {
  const r = paise / 100;
  if (r >= 1e7) return `₹${(r / 1e7).toFixed(1)}Cr`;
  if (r >= 1e5) return `₹${(r / 1e5).toFixed(1)}L`;
  return `₹${(r / 1e3).toFixed(0)}k`;
}

export function ProjectionChart({ scenarios }: { scenarios: ProjectionScenario[] }) {
  const years = scenarios[0].yearly.map((y) => y.year);
  const data = [
    { year: 0, contributed: scenarios[0].start_paise, ...Object.fromEntries(scenarios.map((s) => [s.name, s.start_paise])) },
    ...years.map((year, i) => ({
      year,
      contributed: scenarios[0].start_paise + scenarios[0].yearly[i].contributions_paise,
      ...Object.fromEntries(scenarios.map((s) => [s.name, s.yearly[i].value_paise])),
    })),
  ];
  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-wrap gap-4 text-xs text-muted-foreground">
        {scenarios.map((s) => (
          <span key={s.name} className="inline-flex items-center gap-1.5">
            <span className="h-0.5 w-4" style={{ background: SCENARIO_COLOR[s.name] }} />{s.name} ({s.annual_return_pct}%)
          </span>
        ))}
        <span className="inline-flex items-center gap-1.5">
          <span className="h-0 w-4 border-t-2 border-dashed border-muted-foreground" />Starting value + contributions (no growth)
        </span>
      </div>
      <div className="h-72 w-full" role="img" aria-label="Mathematical scenario values by year; figures in the cards above">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data} margin={{ top: 8, right: 12, bottom: 0, left: 4 }}>
            <CartesianGrid stroke="var(--border)" vertical={false} />
            <XAxis dataKey="year" tickFormatter={(y) => `Y${y}`} stroke="var(--muted-foreground)" tick={{ fontSize: 11 }}
                   tickLine={false} axisLine={{ stroke: "var(--border)" }} />
            <YAxis tickFormatter={compact} stroke="var(--muted-foreground)" tick={{ fontSize: 11 }} width={56}
                   tickLine={false} axisLine={false} />
            <Tooltip
              isAnimationActive={false}
              cursor={{ stroke: "var(--muted-foreground)", strokeDasharray: "3 3" }}
              content={({ active, payload, label }) => {
                if (!active || !payload?.length) return null;
                return (
                  <div className="rounded-md border border-border bg-popover px-2.5 py-1.5 text-xs shadow-sm">
                    <div className="font-medium">Year {label}</div>
                    {payload.map((p) => (
                      <div key={String(p.dataKey)} className="tnum">
                        {p.dataKey === "contributed" ? "Contributed" : String(p.dataKey)}: {formatINR(Number(p.value), { decimals: false })}
                      </div>
                    ))}
                  </div>
                );
              }}
            />
            <Line dataKey="contributed" stroke="var(--muted-foreground)" strokeDasharray="5 4" strokeWidth={2} dot={false} isAnimationActive={false} />
            {scenarios.map((s) => (
              <Line key={s.name} dataKey={s.name} stroke={SCENARIO_COLOR[s.name]} strokeWidth={2} dot={false} isAnimationActive={false} />
            ))}
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
