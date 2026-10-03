"use client";

import { useState, type ReactNode } from "react";
import { ErrorBox, Loading, Notice, PageHeader, Section } from "@/components/common";
import { Field, Select, numeric, rupeesToPaise } from "@/components/form";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { apiDelete, apiPut, errorText, useApi, type Settings } from "@/lib/api";
import { formatINR } from "@/lib/format";

const CONC_LABELS: Record<string, { label: string; unit: "fraction" | "hhi" }> = {
  largest_company_of_direct_equity: { label: "Largest company, % of direct equity", unit: "fraction" },
  top3_of_direct_equity: { label: "Top 3 companies, % of direct equity", unit: "fraction" },
  hhi_direct_equity: { label: "HHI of direct-equity weights", unit: "hhi" },
  largest_company_of_portfolio: { label: "Largest company, % of total portfolio", unit: "fraction" },
};
const toPct = (f: string) => String(Number((Number(f) * 100).toFixed(4)));
const fromPct = (p: string) => String(Number(p) / 100);

export default function SettingsPage() {
  const { data, error, loading, reload } = useApi<Settings>("/settings");
  return (
    <>
      <PageHeader title="Settings" subtitle="Stored locally in your database. The monthly budget and split always come from the monthly_plan sheet of your workbook." />
      {error && <ErrorBox message={error} />}
      {loading && !data && <Loading />}
      {data && (
        <div className="flex flex-col gap-4">
          <Targets s={data} onSaved={reload} />
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            <Drift s={data} onSaved={reload} />
            <ProjectionRates s={data} onSaved={reload} />
          </div>
          <Concentration s={data} onSaved={reload} />
          <Emergency s={data} onSaved={reload} />
        </div>
      )}
    </>
  );
}

function useSaver(section: string, onSaved: () => void) {
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  async function save(value: unknown) {
    setBusy(true);
    try {
      await apiPut(`/settings/${section}`, value);
      setMsg({ ok: true, text: "Saved." });
      onSaved();
    } catch (e) {
      setMsg({ ok: false, text: errorText(e) });
    } finally {
      setBusy(false);
    }
  }
  async function reset() {
    setBusy(true);
    try {
      await apiDelete(`/settings/${section}`);
      setMsg({ ok: true, text: "Reset." });
      onSaved();
    } catch (e) {
      setMsg({ ok: false, text: errorText(e) });
    } finally {
      setBusy(false);
    }
  }
  const feedback: ReactNode = msg && (msg.ok
    ? <span className="text-xs text-muted-foreground">{msg.text}</span>
    : <ErrorBox message={msg.text} />);
  return { save, reset, busy, feedback };
}

function Targets({ s, onSaved }: { s: Settings; onSaved: () => void }) {
  const sec = s.sections.targets;
  const [vals, setVals] = useState<Record<string, string>>(
    () => Object.fromEntries(s.target_classes.map((c) => [c, sec.value?.[c] ?? ""])));
  const { save, reset, busy, feedback } = useSaver("targets", onSaved);
  const total = s.target_classes.reduce((a, c) => a + (Number(vals[c]) || 0), 0);
  const ok = Math.abs(total - 100) < 1e-9 && s.target_classes.every((c) => vals[c] !== "");
  return (
    <Section title="Target allocation" aside={sec.is_set ? "Set" : "Not set — drift and planner targets stay empty"}>
      <p className="mb-3 text-sm text-muted-foreground">
        Your own targets per asset class, in %. There are no defaults; they must total exactly 100%.
      </p>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-5">
        {s.target_classes.map((c) => (
          <Field key={c} label={`${c} %`}>
            <Input inputMode="decimal" value={vals[c]} onChange={(e) => setVals({ ...vals, [c]: numeric(e.target.value) })} />
          </Field>
        ))}
      </div>
      <div className="mt-3 flex flex-wrap items-center gap-3">
        <span className={`tnum text-sm ${ok ? "text-muted-foreground" : "text-status-high"}`}>
          Total {Number(total.toFixed(4))}%{ok ? "" : " (must be 100%)"}
        </span>
        <Button disabled={!ok || busy} onClick={() => save(vals)}>Save targets</Button>
        {sec.is_set && <Button variant="ghost" disabled={busy} onClick={reset}>Clear targets</Button>}
        {feedback}
      </div>
    </Section>
  );
}

function Drift({ s, onSaved }: { s: Settings; onSaved: () => void }) {
  const [tol, setTol] = useState(s.sections.drift.value.tolerance_pp);
  const { save, reset, busy, feedback } = useSaver("drift", onSaved);
  return (
    <Section title="Drift tolerance band" aside={s.sections.drift.is_set ? "Custom" : "Default"}>
      <div className="flex flex-wrap items-end gap-3">
        <Field label="± percentage points" hint={`Default ±${s.sections.drift.default.tolerance_pp} pp`}>
          <Input inputMode="decimal" className="w-28" value={tol} onChange={(e) => setTol(numeric(e.target.value))} />
        </Field>
        <Button disabled={busy || !tol} onClick={() => save({ tolerance_pp: tol })}>Save</Button>
        {s.sections.drift.is_set && <Button variant="ghost" disabled={busy} onClick={reset}>Reset</Button>}
      </div>
      <div className="mt-2">{feedback}</div>
    </Section>
  );
}

function ProjectionRates({ s, onSaved }: { s: Settings; onSaved: () => void }) {
  const v = s.sections.projection.value;
  const [form, setForm] = useState({ ...v, default_years: String(v.default_years) });
  const { save, reset, busy, feedback } = useSaver("projection", onSaved);
  const set = (k: string, val: string) => setForm({ ...form, [k]: val });
  return (
    <Section title="Projection scenarios" aside={v.reviewed ? "Reviewed" : "Placeholders"}>
      {!v.reviewed && (
        <Notice tone="warn">
          These annual rates are placeholders shipped with the app (6% / 9% / 12%). They are not forecasts.
          Review them and save your own; the projection page flags them until you do.
        </Notice>
      )}
      <div className="mt-3 grid grid-cols-3 gap-3">
        {(["conservative", "base", "higher"] as const).map((k) => (
          <Field key={k} label={`${k[0].toUpperCase()}${k.slice(1)} % / yr`}>
            <Input inputMode="decimal" value={form[k]} onChange={(e) => set(k, e.target.value.replace(/[^0-9.-]/g, ""))} />
          </Field>
        ))}
        <Field label="Default years">
          <Select value={form.default_years} onChange={(e) => set("default_years", e.target.value)}>
            {[5, 10, 15, 20, 25, 30].map((y) => <option key={y} value={y}>{y}</option>)}
          </Select>
        </Field>
        <Field label="Default annual step-up">
          <Select value={form.default_step_up} onChange={(e) => set("default_step_up", e.target.value)}>
            {["0", "5", "10"].map((p) => <option key={p} value={p}>{p}%</option>)}
          </Select>
        </Field>
      </div>
      <div className="mt-3 flex flex-wrap items-center gap-3">
        <Button disabled={busy} onClick={() => save({ ...form, default_years: Number(form.default_years), reviewed: true })}>
          Save as reviewed
        </Button>
        {s.sections.projection.is_set && <Button variant="ghost" disabled={busy} onClick={reset}>Back to placeholders</Button>}
        {feedback}
      </div>
    </Section>
  );
}

function Concentration({ s, onSaved }: { s: Settings; onSaved: () => void }) {
  const v = s.sections.concentration.value;
  const [form, setForm] = useState(() => Object.fromEntries(Object.entries(v).map(([k, t]) => [k, {
    low: CONC_LABELS[k]?.unit === "hhi" ? t.low : toPct(t.low), high: CONC_LABELS[k]?.unit === "hhi" ? t.high : toPct(t.high),
  }])));
  const { save, reset, busy, feedback } = useSaver("concentration", onSaved);
  function submit() {
    save(Object.fromEntries(Object.entries(form).map(([k, t]) => [k, CONC_LABELS[k]?.unit === "hhi" ? t
      : { low: fromPct(t.low), high: fromPct(t.high) }])));
  }
  return (
    <Section title="Concentration thresholds" aside={s.sections.concentration.is_set ? "Custom" : "Defaults"}>
      <p className="mb-3 text-sm text-muted-foreground">LOW below the first value, MODERATE from the first up to the second, HIGH at or above the second.</p>
      <div className="flex flex-col gap-2">
        {Object.entries(form).map(([k, t]) => (
          <div key={k} className="grid grid-cols-[1fr_6rem_6rem] items-end gap-3">
            <span className="text-sm">{CONC_LABELS[k]?.label ?? k}{CONC_LABELS[k]?.unit === "fraction" ? " (%)" : ""}</span>
            <Field label="Moderate from">
              <Input inputMode="decimal" value={t.low} onChange={(e) => setForm({ ...form, [k]: { ...t, low: numeric(e.target.value) } })} />
            </Field>
            <Field label="High from">
              <Input inputMode="decimal" value={t.high} onChange={(e) => setForm({ ...form, [k]: { ...t, high: numeric(e.target.value) } })} />
            </Field>
          </div>
        ))}
      </div>
      <div className="mt-3 flex flex-wrap items-center gap-3">
        <Button disabled={busy} onClick={submit}>Save thresholds</Button>
        {s.sections.concentration.is_set && <Button variant="ghost" disabled={busy} onClick={reset}>Reset to defaults</Button>}
        {feedback}
      </div>
    </Section>
  );
}

function Emergency({ s, onSaved }: { s: Settings; onSaved: () => void }) {
  const v = s.sections.emergency_fund.value;
  const [exp, setExp] = useState(v ? String(v.monthly_expenses_paise / 100) : "");
  const [bal, setBal] = useState(v ? String(v.balance_paise / 100) : "");
  const [months, setMonths] = useState(v ? String(v.target_months) : "");
  const { save, reset, busy, feedback } = useSaver("emergency_fund", onSaved);
  const e = rupeesToPaise(exp), b = rupeesToPaise(bal);
  const ok = e !== null && e > 0 && b !== null && months !== "";
  return (
    <Section title="Emergency fund" aside="Kept separate from the portfolio">
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <Field label="Monthly essential expenses (₹)"><Input inputMode="decimal" value={exp} onChange={(x) => setExp(numeric(x.target.value))} /></Field>
        <Field label="Current emergency balance (₹)"><Input inputMode="decimal" value={bal} onChange={(x) => setBal(numeric(x.target.value))} /></Field>
        <Field label="Target months of expenses">
          <Select value={months} onChange={(x) => setMonths(x.target.value)}>
            <option value="">Choose 3–6…</option>
            {[3, 4, 5, 6].map((m) => <option key={m} value={m}>{m} months</option>)}
          </Select>
        </Field>
      </div>
      <div className="mt-3 flex flex-wrap items-center gap-3">
        <Button disabled={!ok || busy} onClick={() => save({ monthly_expenses_paise: e, balance_paise: b, target_months: Number(months) })}>Save</Button>
        {s.sections.emergency_fund.is_set && <Button variant="ghost" disabled={busy} onClick={reset}>Clear</Button>}
        {ok && <span className="tnum text-xs text-muted-foreground">Target would be {formatINR((e as number) * Number(months))}</span>}
        {feedback}
      </div>
    </Section>
  );
}
