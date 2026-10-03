"use client";

import Link from "next/link";
import { ASSET_CLASS_COLOR } from "@/components/asset-donut";
import type { Drift, DriftRow } from "@/lib/api";
import { formatINR, formatPct } from "@/lib/format";
import { cn } from "@/lib/utils";

// Drift status is a state, so it uses the reserved status colours — always with an icon and the word.
const STATUS: Record<DriftRow["status"], { cls: string; icon: string; bar: string }> = {
  "WITHIN BAND": { cls: "border-status-low/50 text-status-low", icon: "●", bar: "var(--status-low)" },
  OVERWEIGHT: { cls: "border-status-high/50 text-status-high", icon: "▲", bar: "var(--status-high)" },
  UNDERWEIGHT: { cls: "border-status-high/50 text-status-high", icon: "▼", bar: "var(--status-high)" },
};

export function DriftBadge({ status }: { status: DriftRow["status"] }) {
  const s = STATUS[status];
  return (
    <span className={cn("inline-flex items-center gap-1 rounded border px-1.5 py-0.5 text-xs font-semibold whitespace-nowrap", s.cls)}>
      <span aria-hidden>{s.icon}</span>{status}
    </span>
  );
}

function StackedBar({ label, rows, field }: { label: string; rows: DriftRow[]; field: "current" | "target" }) {
  return (
    <div className="grid grid-cols-[4.5rem_1fr] items-center gap-2">
      <span className="text-xs text-muted-foreground">{label}</span>
      <div className="flex h-6 w-full gap-[2px] overflow-hidden rounded">
        {rows.filter((r) => Number(r[field]) > 0).map((r) => (
          <div key={r.asset_class} className="h-full" title={`${r.asset_class}: ${formatPct(r[field])}`}
               style={{ width: `${Number(r[field]) * 100}%`, background: ASSET_CLASS_COLOR[r.asset_class] }} />
        ))}
      </div>
    </div>
  );
}

function DivergingChart({ rows, tol }: { rows: DriftRow[]; tol: number }) {
  const maxAbs = Math.max(tol * 2, ...rows.map((r) => Math.abs(Number(r.deviation_pp)))) * 1.1;
  const pos = (v: number) => 50 + (v / maxAbs) * 50; // percent across the track
  return (
    <div className="flex flex-col gap-1.5">
      {rows.map((r) => {
        const d = Number(r.deviation_pp);
        const left = Math.min(pos(0), pos(d));
        const width = Math.abs(pos(d) - pos(0));
        return (
          <div key={r.asset_class} className="grid grid-cols-[7.5rem_1fr_4.5rem] items-center gap-2 text-sm"
               title={`${r.asset_class}: ${d > 0 ? "+" : ""}${d.toFixed(1)} pp vs target`}>
            <span className="truncate text-xs">{r.asset_class}</span>
            <div className="relative h-5">
              {/* tolerance band */}
              <div className="absolute inset-y-0 bg-muted/60" style={{ left: `${pos(-tol)}%`, width: `${pos(tol) - pos(-tol)}%` }} />
              <div className="absolute inset-y-0 w-px bg-muted-foreground/60" style={{ left: `${pos(0)}%` }} />
              <div className="absolute top-1 bottom-1 rounded-sm" style={{ left: `${left}%`, width: `${Math.max(width, 0.4)}%`, background: STATUS[r.status].bar }} />
            </div>
            <span className="tnum text-right text-xs">{d > 0 ? "+" : ""}{d.toFixed(1)} pp</span>
          </div>
        );
      })}
      <div className="grid grid-cols-[7.5rem_1fr_4.5rem] gap-2 text-[11px] text-muted-foreground">
        <span />
        <div className="flex justify-between"><span>underweight</span><span>shaded = ±{tol} pp band</span><span>overweight</span></div>
        <span />
      </div>
    </div>
  );
}

export function DriftSection({ drift }: { drift: Drift }) {
  if (!drift.targets_set) {
    return (
      <p className="text-sm text-muted-foreground">
        Set your targets — {drift.message?.replace("Set your targets in Settings to see drift.", "")}
        <Link className="underline" href="/settings">open Settings</Link> to enter a target % for each asset class.
      </p>
    );
  }
  const tol = Number(drift.tolerance_pp);
  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-col gap-2">
        <StackedBar label="Current" rows={drift.rows} field="current" />
        <StackedBar label="Target" rows={drift.rows} field="target" />
        <div className="flex flex-wrap gap-3 pl-[5rem] text-xs text-muted-foreground">
          {drift.rows.map((r) => (
            <span key={r.asset_class} className="inline-flex items-center gap-1.5">
              <span aria-hidden className="size-2.5 rounded-sm" style={{ background: ASSET_CLASS_COLOR[r.asset_class] }} />{r.asset_class}
            </span>
          ))}
        </div>
      </div>
      <DivergingChart rows={drift.rows} tol={tol} />
      <div className="overflow-x-auto">
        <table className="tnum w-full text-sm">
          <thead className="text-xs text-muted-foreground">
            <tr>
              <th className="py-1 text-left font-normal">Asset class</th>
              <th className="py-1 text-right font-normal">Current</th>
              <th className="py-1 text-right font-normal">Target</th>
              <th className="py-1 text-right font-normal">Deviation</th>
              <th className="py-1 text-right font-normal">Value vs target</th>
              <th className="py-1 pl-3 text-left font-normal">Status</th>
            </tr>
          </thead>
          <tbody>
            {drift.rows.map((r) => (
              <tr key={r.asset_class} className="border-t border-border align-top">
                <td className="py-1.5">
                  {r.asset_class}{!r.held && <span className="text-xs text-muted-foreground"> · not held</span>}
                  <div className="text-xs text-muted-foreground">Reason: {r.reason}</div>
                  <div className="text-xs text-muted-foreground">Calculation: {r.calculation}</div>
                </td>
                <td className="py-1.5 text-right">{formatPct(r.current)}</td>
                <td className="py-1.5 text-right">{formatPct(r.target)}</td>
                <td className="py-1.5 text-right whitespace-nowrap">{Number(r.deviation_pp) > 0 ? "+" : ""}{Number(r.deviation_pp).toFixed(1)} pp</td>
                <td className="py-1.5 text-right whitespace-nowrap">{formatINR(r.value_vs_target_paise, { signed: true, decimals: false })}</td>
                <td className="py-1.5 pl-3"><DriftBadge status={r.status} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="text-xs text-muted-foreground">
        Tolerance band ±{drift.tolerance_pp} pp (change it in Settings). {drift.basis} “Value vs target” = current value − target % × total.
      </p>
    </div>
  );
}
