"use client";

import { useEffect, useState } from "react";
import { EmptyState, ErrorBox, Loading, Notice, PageHeader, Section } from "@/components/common";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { apiPost, useApi, type SimOptions, type SimPair, type SimResult, type SimScenario } from "@/lib/api";
import { formatINR, formatPct, formatQty } from "@/lib/format";
import { cn } from "@/lib/utils";

export default function SimulatorPage() {
  const { data: opts, error: optErr, loading } = useApi<SimOptions>("/simulator/options");
  const [amount, setAmount] = useState("1000");
  const [custom, setCustom] = useState("");
  const [userSelected, setUserSelected] = useState<string[] | null>(null);
  const [extra, setExtra] = useState("");
  const [res, setRes] = useState<{ key: string; data?: SimResult; error?: string } | null>(null);

  // Default selection = the server's default scenarios until the user changes it.
  const selected = userSelected ?? opts?.default_scenarios.map((s) => s.key) ?? [];
  const setSelected = (f: (cur: string[]) => string[]) => setUserSelected(f(selected));
  const reqKey = opts && selected.length && Number(amount) > 0 ? JSON.stringify([amount, selected]) : null;

  useEffect(() => {
    if (!reqKey) return;
    let cancelled = false;
    const [amt, keys] = JSON.parse(reqKey) as [string, string[]];
    apiPost<SimResult>("/simulator", { amount: amt, scenario_keys: keys }).then(
      (data) => { if (!cancelled) setRes({ key: reqKey, data }); },
      (e) => { if (!cancelled) setRes({ key: reqKey, error: e instanceof Error ? e.message : String(e) }); },
    );
    return () => { cancelled = true; };
  }, [reqKey]);

  const busy = reqKey !== null && res?.key !== reqKey;
  const result = reqKey ? res?.data ?? null : null;
  const error = res?.key === reqKey ? res?.error ?? null : null;

  const toggle = (key: string) =>
    setSelected((cur) => (cur.includes(key) ? cur.filter((k) => k !== key) : [...cur, key]));

  const equityOptions = opts?.instruments.filter((i) => i.asset_type !== "MF") ?? [];
  const labelFor = (key: string) =>
    opts?.default_scenarios.find((s) => s.key === key)?.label ??
    `Add to ${opts?.instruments.find((i) => `inst:${i.instrument_id}` === key)?.name ?? key}`;

  return (
    <>
      <PageHeader
        title="Next contribution"
        subtitle="How would one contribution change your mix? Compares scenarios side by side, before → after. Descriptive only — it does not tell you what to buy."
      />
      {optErr && <ErrorBox message={optErr} />}
      {loading && !opts && <Loading />}
      {opts && opts.instruments.length === 0 && <EmptyState />}
      {opts && opts.instruments.length > 0 && (
        <div className="flex flex-col gap-4">
          <Section title="1. Amount">
            <div className="flex flex-wrap items-center gap-2">
              {opts.presets_rupees.map((p) => (
                <Button
                  key={p}
                  variant={amount === String(p) && !custom ? "default" : "outline"}
                  onClick={() => { setCustom(""); setAmount(String(p)); }}
                >
                  {formatINR(p * 100, { decimals: false })}
                </Button>
              ))}
              <form
                className="flex items-center gap-2"
                onSubmit={(e) => { e.preventDefault(); if (Number(custom) > 0) setAmount(custom); }}
              >
                <Input
                  inputMode="decimal"
                  placeholder="Custom ₹"
                  aria-label="Custom amount in rupees"
                  className="w-32"
                  value={custom}
                  onChange={(e) => setCustom(e.target.value.replace(/[^0-9.]/g, ""))}
                />
                <Button type="submit" variant="outline" disabled={!(Number(custom) > 0)}>Use</Button>
              </form>
            </div>
          </Section>

          <Section title="2. Scenarios to compare">
            <div className="flex flex-col gap-2">
              {opts.default_scenarios.map((s) => (
                <label key={s.key} className="flex items-center gap-2 text-sm">
                  <input type="checkbox" checked={selected.includes(s.key)} onChange={() => toggle(s.key)} />
                  {s.label}
                </label>
              ))}
              {selected.filter((k) => k.startsWith("inst:")).map((k) => (
                <label key={k} className="flex items-center gap-2 text-sm">
                  <input type="checkbox" checked onChange={() => toggle(k)} />
                  {labelFor(k)}
                </label>
              ))}
              <div className="flex flex-wrap items-center gap-2 pt-1">
                <select
                  aria-label="Add an existing stock or ETF as a scenario"
                  className="h-8 rounded-lg border border-input bg-input/30 px-2 text-sm"
                  value={extra}
                  onChange={(e) => setExtra(e.target.value)}
                >
                  <option value="">Add an existing stock/ETF…</option>
                  {equityOptions.map((i) => (
                    <option key={i.instrument_id} value={`inst:${i.instrument_id}`}>
                      {i.short_name} — {i.name}
                    </option>
                  ))}
                </select>
                <Button
                  variant="outline"
                  disabled={!extra || selected.includes(extra)}
                  onClick={() => { setSelected((c) => [...c, extra]); setExtra(""); }}
                >
                  Add scenario
                </Button>
              </div>
            </div>
          </Section>

          {error && <ErrorBox message={error} />}
          {opts.excluded.length > 0 && (
            <Notice>
              Not included (Data unavailable): {opts.excluded.map((x) => x.name).join("; ")}. Their weights cannot be
              computed until prices are available, so percentages below cover priced holdings only.
            </Notice>
          )}

          {result && (
            <>
              <div className={cn("flex flex-col gap-1", busy && "opacity-60")}>
                <h2 className="text-sm font-medium">
                  3. Compare: adding {formatINR(result.amount_paise, { decimals: false })} to a portfolio of{" "}
                  {formatINR(result.before.total_paise)}
                </h2>
              </div>
              <div className={cn("grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3", busy && "opacity-60")}>
                {result.scenarios.map((s) => <ScenarioCard key={s.key} s={s} />)}
              </div>
              <Section title="Assumptions (mathematical scenario, not a prediction)">
                <ul className="list-disc space-y-1 pl-5 text-sm text-muted-foreground">
                  {result.assumptions.map((a) => <li key={a}>{a}</li>)}
                </ul>
              </Section>
            </>
          )}
        </div>
      )}
    </>
  );
}

function Delta({ before, after }: { before: string; after: string }) {
  const d = (Number(after) - Number(before)) * 100;
  const shown = Math.abs(d) < 0.05 ? "±0.0" : `${d > 0 ? "+" : "−"}${Math.abs(d).toFixed(1)}`;
  return <span className="text-xs text-muted-foreground">{shown} pp</span>;
}

function PairTable({ title, rows, name }: { title: string; rows: SimPair[]; name?: (r: SimPair) => string }) {
  if (!rows.length) return null;
  return (
    <div>
      <div className="mb-1 text-xs font-medium text-muted-foreground">{title}</div>
      <table className="tnum w-full text-sm">
        <tbody>
          {rows.map((r) => (
            <tr key={r.name} className="border-t border-border">
              <td className="py-1 pr-2">{name ? name(r) : r.name}</td>
              <td className="py-1 text-right whitespace-nowrap">
                {formatPct(r.before)} → <span className="font-medium">{formatPct(r.after)}</span>
              </td>
              <td className="w-16 py-1 text-right"><Delta before={r.before} after={r.after} /></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ScenarioCard({ s }: { s: SimScenario }) {
  return (
    <Section title={s.label}>
      <div className="flex flex-col gap-4">
        <div className="text-xs text-muted-foreground">
          {s.legs.map((l) => (
            <div key={l.instrument_id}>
              {formatINR(l.amount_paise)} → {formatQty(l.units)} {l.whole_units_only ? "whole unit(s)" : "units"} @{" "}
              ₹{l.unit_price}
              {l.uninvested_paise > 0 && ` · ${formatINR(l.uninvested_paise)} uninvested`}
            </div>
          ))}
        </div>
        <ul className="space-y-1 text-sm">
          {s.sentences.map((t) => <li key={t}>{t}</li>)}
        </ul>
        <PairTable title="Asset classes (% of portfolio)" rows={s.asset_classes} />
        <PairTable
          title="Mutual-fund split (% of MF total)"
          rows={s.mf_split}
          name={(r) => (r as SimScenario["mf_split"][number]).category}
        />
        <PairTable title="Top company weights (% of portfolio)" rows={s.top_companies} />
      </div>
    </Section>
  );
}
