"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { ErrorBox, Loading, Notice, PageHeader, Section } from "@/components/common";
import { numeric } from "@/components/form";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { apiPost, errorText, type Planner, type PlannerMode } from "@/lib/api";
import { formatINR, formatPct, formatQty } from "@/lib/format";
import { cn } from "@/lib/utils";

export default function PlannerPage() {
  const [budget, setBudget] = useState<string | null>(null); // null = monthly_plan total
  const [custom, setCustom] = useState("");
  const [picks, setPicks] = useState<number[]>([]);
  const [res, setRes] = useState<{ key: string; data?: Planner; error?: string } | null>(null);

  const key = JSON.stringify([budget, picks]);
  useEffect(() => {
    let cancelled = false;
    apiPost<Planner>("/planner", { budget, picks }).then(
      (data) => { if (!cancelled) setRes({ key, data }); },
      (e) => { if (!cancelled) setRes({ key, error: errorText(e) }); });
    return () => { cancelled = true; };
  }, [key, budget, picks]);

  const p = res?.data;
  const busy = res?.key !== key;
  return (
    <>
      <PageHeader
        title="Monthly contribution planner"
        subtitle="How a monthly budget would be distributed and what your allocation would become. Descriptive only — nothing is executed or suggested as an order."
      />
      {res?.error && <ErrorBox message={res.error} />}
      {!p && !res?.error && <Loading />}
      {p && (
        <div className={cn("flex flex-col gap-4", busy && "opacity-60")}>
          <Section title="Budget" aside={`Source: ${p.budget_source}`}>
            <div className="flex flex-wrap items-center gap-2">
              <Button variant={budget === null ? "default" : "outline"} onClick={() => { setBudget(null); setCustom(""); }}>
                Plan default {formatINR(p.default_budget_paise, { decimals: false })}
              </Button>
              {p.presets_rupees.map((r) => (
                <Button key={r} variant={budget === String(r) ? "default" : "outline"} onClick={() => { setBudget(String(r)); setCustom(""); }}>
                  {formatINR(r * 100, { decimals: false })}
                </Button>
              ))}
              <form className="flex items-center gap-2" onSubmit={(e) => { e.preventDefault(); if (Number(custom) > 0) setBudget(custom); }}>
                <Input inputMode="decimal" placeholder="Custom ₹" aria-label="Custom budget" className="w-32" value={custom}
                       onChange={(e) => setCustom(numeric(e.target.value))} />
                <Button type="submit" variant="outline" disabled={!(Number(custom) > 0)}>Use</Button>
              </form>
            </div>
            <p className="mt-2 text-xs text-muted-foreground">Overrides here are temporary; your workbook&apos;s monthly_plan is not changed.</p>
          </Section>

          <Section title="Stocks/ETFs bucket (optional)" aside="Whole units only">
            <p className="mb-2 text-sm text-muted-foreground">
              The plan&apos;s stocks/ETFs share has no per-instrument split. Pick holdings to see whole-unit detail (equal split);
              with none picked it stays at asset-class level.
            </p>
            <div className="flex flex-wrap gap-2">
              {p.pickable.map((h) => {
                const on = picks.includes(h.instrument_id);
                return (
                  <button key={h.instrument_id} type="button" aria-pressed={on}
                          onClick={() => setPicks(on ? picks.filter((x) => x !== h.instrument_id) : [...picks, h.instrument_id])}
                          className={cn("rounded-md border px-2 py-1 text-xs", on ? "border-foreground bg-muted" : "border-border text-muted-foreground")}>
                    {h.short_name}
                  </button>
                );
              })}
            </div>
          </Section>

          {p.excluded.length > 0 && <Notice>Not included (no price): {p.excluded.map((x) => x.name).join("; ")}.</Notice>}

          <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
            {p.modes.map((m) => <ModeCard key={m.mode} m={m} />)}
          </div>

          <Section title="Assumptions">
            <ul className="list-disc space-y-1 pl-5 text-sm text-muted-foreground">
              {p.assumptions.map((a) => <li key={a}>{a}</li>)}
            </ul>
          </Section>
        </div>
      )}
    </>
  );
}

function ModeCard({ m }: { m: PlannerMode }) {
  if (!m.available) {
    return (
      <Section title={m.label}>
        <Notice>{m.reason} {m.mode === "targets" && <Link className="underline" href="/settings">Set your targets</Link>}</Notice>
      </Section>
    );
  }
  return (
    <Section title={m.label}>
      <div className="flex flex-col gap-4">
        <div>
          <div className="mb-1 text-xs font-medium text-muted-foreground">Where the {formatINR(m.budget_paise!, { decimals: false })} would go</div>
          <table className="tnum w-full text-sm">
            <tbody>
              {m.lines!.map((l, i) => (
                <tr key={i} className="border-t border-border align-top">
                  <td className="py-1.5 pr-2">
                    {l.label}
                    {l.note && <div className="text-xs text-muted-foreground">{l.note}</div>}
                    {l.units && (
                      <div className="text-xs text-muted-foreground">
                        {formatQty(l.units)} {l.whole_units_only ? "whole unit(s)" : "units"} @ ₹{l.unit_price}
                        {l.uninvested_paise > 0 && ` · ${formatINR(l.uninvested_paise)} uninvested`}
                      </div>
                    )}
                  </td>
                  <td className="py-1.5 text-right whitespace-nowrap">{formatINR(l.amount_paise)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {m.uninvested_paise! > 0 && <p className="mt-1 text-xs text-muted-foreground">Uninvested (whole-unit remainder): {formatINR(m.uninvested_paise!)}</p>}
        </div>

        <div>
          <div className="mb-1 text-xs font-medium text-muted-foreground">Current portfolio + contribution = projected allocation</div>
          <table className="tnum w-full text-sm">
            <thead className="text-xs text-muted-foreground">
              <tr>
                <th className="py-1 text-left font-normal">Asset class</th>
                <th className="py-1 text-right font-normal">Current</th>
                <th className="py-1 text-right font-normal">+ Add</th>
                <th className="py-1 text-right font-normal">Projected</th>
                <th className="py-1 text-right font-normal">Target</th>
              </tr>
            </thead>
            <tbody>
              {m.asset_classes!.map((c) => (
                <tr key={c.asset_class} className="border-t border-border">
                  <td className="py-1.5">{c.asset_class}{!c.held && <span className="text-xs text-muted-foreground"> · not held</span>}</td>
                  <td className="py-1.5 text-right">{formatPct(c.current)}</td>
                  <td className="py-1.5 text-right text-muted-foreground">{formatINR(c.add_paise, { decimals: false })}</td>
                  <td className="py-1.5 text-right font-medium">{formatPct(c.projected)}</td>
                  <td className="py-1.5 text-right text-muted-foreground">{c.target ? formatPct(c.target) : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {m.mutual_funds!.length > 0 && (
          <div>
            <div className="mb-1 text-xs font-medium text-muted-foreground">Mutual-fund split (% of MF total)</div>
            <table className="tnum w-full text-sm">
              <tbody>
                {m.mutual_funds!.map((f) => (
                  <tr key={f.instrument_id} className="border-t border-border">
                    <td className="py-1.5">{f.category}</td>
                    <td className="py-1.5 text-right text-muted-foreground">+{formatINR(f.add_paise, { decimals: false })}</td>
                    <td className="py-1.5 text-right">{formatPct(f.current)} → <b>{formatPct(f.projected)}</b></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {m.considerations!.length > 0 && (
          <div className="flex flex-col gap-2">
            <div className="text-xs font-medium text-muted-foreground">Allocation considerations</div>
            {m.considerations!.map((c, i) => (
              <div key={i} className="rounded-md border border-border p-2">
                <p className="text-sm">{c.text}</p>
                <p className="tnum mt-1 text-xs text-muted-foreground">Calculation: {c.calculation}</p>
              </div>
            ))}
          </div>
        )}
      </div>
    </Section>
  );
}
