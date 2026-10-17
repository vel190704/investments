"use client";

import { useState, type ReactNode } from "react";
import { ErrorBox, Loading, Notice, PageHeader, Section } from "@/components/common";
import { Field, Select, numeric, rupeesToPaise } from "@/components/form";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { apiDelete, apiPut, errorText, useApi, type LlmUsage, type Lookthrough, type SectorsPage, type Settings } from "@/lib/api";
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
          <AiSettings s={data} onSaved={reload} />
          <Targets s={data} onSaved={reload} />
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            <Drift s={data} onSaved={reload} />
            <ProjectionRates s={data} onSaved={reload} />
          </div>
          <Concentration s={data} onSaved={reload} />
          <HealthThresholds s={data} onSaved={reload} />
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            <Rubric s={data} onSaved={reload} />
            <SectorRules s={data} onSaved={reload} />
          </div>
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            <SectorRanges s={data} onSaved={reload} />
            <Themes s={data} onSaved={reload} />
          </div>
          <Emergency s={data} onSaved={reload} />
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            <NewsFeeds s={data} onSaved={reload} />
            <AlertRules s={data} onSaved={reload} />
          </div>
          <p className="text-xs text-muted-foreground">
            Asset-class, sector and region overrides per instrument: <a className="underline" href="/classification">Classification</a>.
          </p>
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

const HEALTH_ROWS: { key: string; label: string; unit: "fraction" | "hhi" }[] = [
  { key: "company_lookthrough", label: "Company total exposure, % of portfolio", unit: "fraction" },
  { key: "sector_largest", label: "Largest sector, % of equity exposure", unit: "fraction" },
  { key: "sector_hhi", label: "Sector HHI", unit: "hhi" },
  { key: "overlap", label: "Largest pairwise fund overlap", unit: "fraction" },
];

function HealthThresholds({ s, onSaved }: { s: Settings; onSaved: () => void }) {
  const v = s.sections.health.value;
  const [form, setForm] = useState(() => ({
    ...Object.fromEntries(HEALTH_ROWS.map((r) => [r.key, {
      low: r.unit === "hhi" ? v[r.key].low : toPct(v[r.key].low), high: r.unit === "hhi" ? v[r.key].high : toPct(v[r.key].high),
    }])),
    drift: { high_multiple: v.drift.high_multiple },
    emergency: { moderate_below: toPct(v.emergency.moderate_below), high_below: toPct(v.emergency.high_below) },
  }) as Record<string, Record<string, string>>);
  const { save, reset, busy, feedback } = useSaver("health", onSaved);
  const set = (k: string, f: string, val: string) => setForm({ ...form, [k]: { ...form[k], [f]: numeric(val) } });
  function submit() {
    save({
      ...Object.fromEntries(HEALTH_ROWS.map((r) => [r.key, r.unit === "hhi" ? form[r.key]
        : { low: fromPct(form[r.key].low), high: fromPct(form[r.key].high) }])),
      drift: form.drift,
      emergency: { moderate_below: fromPct(form.emergency.moderate_below), high_below: fromPct(form.emergency.high_below) },
    });
  }
  return (
    <Section title="Portfolio health thresholds" aside={s.sections.health.is_set ? "Custom" : "Defaults (as defined in code)"}>
      <div className="flex flex-col gap-2">
        {HEALTH_ROWS.map((r) => (
          <div key={r.key} className="grid grid-cols-[1fr_6rem_6rem] items-end gap-3">
            <span className="text-sm">{r.label}{r.unit === "fraction" ? " (%)" : ""}</span>
            <Field label="Moderate from"><Input inputMode="decimal" value={form[r.key].low} onChange={(e) => set(r.key, "low", e.target.value)} /></Field>
            <Field label="High from"><Input inputMode="decimal" value={form[r.key].high} onChange={(e) => set(r.key, "high", e.target.value)} /></Field>
          </div>
        ))}
        <div className="grid grid-cols-[1fr_6rem_6rem] items-end gap-3">
          <span className="text-sm">Drift: HIGH beyond this multiple of your tolerance band</span>
          <Field label="× band"><Input inputMode="decimal" value={form.drift.high_multiple} onChange={(e) => set("drift", "high_multiple", e.target.value)} /></Field>
          <span />
        </div>
        <div className="grid grid-cols-[1fr_6rem_6rem] items-end gap-3">
          <span className="text-sm">Emergency-fund coverage (% of target)</span>
          <Field label="Moderate below"><Input inputMode="decimal" value={form.emergency.moderate_below} onChange={(e) => set("emergency", "moderate_below", e.target.value)} /></Field>
          <Field label="High below"><Input inputMode="decimal" value={form.emergency.high_below} onChange={(e) => set("emergency", "high_below", e.target.value)} /></Field>
        </div>
      </div>
      <div className="mt-3 flex flex-wrap items-center gap-3">
        <Button disabled={busy} onClick={submit}>Save thresholds</Button>
        {s.sections.health.is_set && <Button variant="ghost" disabled={busy} onClick={reset}>Reset to defaults</Button>}
        {feedback}
      </div>
    </Section>
  );
}

function SectorRanges({ s, onSaved }: { s: Settings; onSaved: () => void }) {
  const sectors = useApi<SectorsPage>("/sectors");
  const [rows, setRows] = useState<{ sector: string; min: string; max: string }[]>(
    () => Object.entries(s.sections.sector_ranges.value ?? {}).map(([sector, r]) => ({ sector, ...r })));
  const { save, reset, busy, feedback } = useSaver("sector_ranges", onSaved);
  const names = (sectors.data?.sectors ?? []).map((x) => x.sector);
  return (
    <Section title="Desired sector ranges" aside="% of total portfolio · no defaults">
      <div className="flex flex-col gap-2">
        {rows.map((r, i) => (
          <div key={i} className="grid grid-cols-[1fr_5rem_5rem_auto] items-end gap-2">
            <Select value={r.sector} aria-label="Sector" onChange={(e) => setRows(rows.map((x, j) => j === i ? { ...x, sector: e.target.value } : x))}>
              <option value="">Choose sector…</option>
              {[...new Set([...names, r.sector].filter(Boolean))].map((n) => <option key={n} value={n}>{n}</option>)}
            </Select>
            <Field label="Min %"><Input inputMode="decimal" value={r.min} onChange={(e) => setRows(rows.map((x, j) => j === i ? { ...x, min: numeric(e.target.value) } : x))} /></Field>
            <Field label="Max %"><Input inputMode="decimal" value={r.max} onChange={(e) => setRows(rows.map((x, j) => j === i ? { ...x, max: numeric(e.target.value) } : x))} /></Field>
            <Button variant="ghost" size="sm" onClick={() => setRows(rows.filter((_, j) => j !== i))}>Remove</Button>
          </div>
        ))}
        <div><Button variant="outline" size="sm" onClick={() => setRows([...rows, { sector: "", min: "", max: "" }])}>Add range</Button></div>
      </div>
      <div className="mt-3 flex flex-wrap items-center gap-3">
        <Button disabled={busy || rows.some((r) => !r.sector || r.min === "" || r.max === "")}
                onClick={() => save(Object.fromEntries(rows.map((r) => [r.sector, { min: r.min, max: r.max }])))}>Save ranges</Button>
        {s.sections.sector_ranges.is_set && <Button variant="ghost" disabled={busy} onClick={reset}>Clear all</Button>}
        {feedback}
      </div>
    </Section>
  );
}

function Themes({ s, onSaved }: { s: Settings; onSaved: () => void }) {
  const look = useApi<Lookthrough>("/lookthrough");
  const [rows, setRows] = useState<{ tag: string; isins: string[] }[]>(
    () => Object.entries(s.sections.themes.value ?? {}).map(([tag, isins]) => ({ tag, isins })));
  const { save, reset, busy, feedback } = useSaver("themes", onSaved);
  const companies = look.data?.companies ?? [];
  return (
    <Section title="Themes" aside="Your own tags (e.g. Defence, Power, Banking) · no defaults">
      <p className="mb-2 text-xs text-muted-foreground">Companies are tagged by ISIN, so exposure through funds counts too.</p>
      <div className="flex flex-col gap-3">
        {rows.map((r, i) => (
          <div key={i} className="flex flex-col gap-1 rounded-md border border-border p-2">
            <div className="flex gap-2">
              <Input placeholder="Theme name" value={r.tag} onChange={(e) => setRows(rows.map((x, j) => j === i ? { ...x, tag: e.target.value } : x))} />
              <Button variant="ghost" size="sm" onClick={() => setRows(rows.filter((_, j) => j !== i))}>Remove</Button>
            </div>
            <div className="flex flex-wrap gap-1">
              {companies.slice(0, 60).map((c) => {
                const on = r.isins.includes(c.isin);
                return (
                  <button key={c.isin} type="button" aria-pressed={on}
                          onClick={() => setRows(rows.map((x, j) => j === i ? { ...x, isins: on ? x.isins.filter((y) => y !== c.isin) : [...x.isins, c.isin] } : x))}
                          className={`rounded border px-1.5 py-0.5 text-xs ${on ? "border-foreground bg-muted" : "border-border text-muted-foreground"}`}>
                    {c.name}
                  </button>
                );
              })}
            </div>
          </div>
        ))}
        <div><Button variant="outline" size="sm" onClick={() => setRows([...rows, { tag: "", isins: [] }])}>Add theme</Button></div>
      </div>
      <div className="mt-3 flex flex-wrap items-center gap-3">
        <Button disabled={busy || rows.some((r) => !r.tag.trim())}
                onClick={() => save(Object.fromEntries(rows.map((r) => [r.tag.trim(), r.isins])))}>Save themes</Button>
        {s.sections.themes.is_set && <Button variant="ghost" disabled={busy} onClick={reset}>Clear all</Button>}
        {feedback}
      </div>
    </Section>
  );
}

function AiSettings({ s, onSaved }: { s: Settings; onSaved: () => void }) {
  const v = s.sections.llm.value;
  const [form, setForm] = useState({
    ...v, model: v.model ?? "", price_in_per_mtok: v.price_in_per_mtok ?? "", price_out_per_mtok: v.price_out_per_mtok ?? "",
    monthly_call_cap: String(v.monthly_call_cap),
  });
  const status = useApi<{ gate: string | null; usage: LlmUsage }>("/llm/status");
  const page = useApi<{ settings: { model: string } }>("/analysis");
  const { save, busy, feedback } = useSaver("llm", onSaved);
  const submit = (patch: Partial<typeof form> = {}) => {
    const f = { ...form, ...patch };
    setForm(f);
    save({ ...f, model: f.model.trim() || null, monthly_call_cap: Number(f.monthly_call_cap),
           price_in_per_mtok: f.price_in_per_mtok || null, price_out_per_mtok: f.price_out_per_mtok || null });
  };
  return (
    <Section title="AI analysis (LLM)" aside={v.outbound_enabled ? "Outbound calls allowed" : "Privacy: outbound calls OFF"}>
      <label className="flex items-start gap-2 text-sm">
        <input type="checkbox" className="mt-1" checked={form.outbound_enabled} disabled={busy}
               onChange={(e) => submit({ outbound_enabled: e.target.checked })} />
        <span><b>Allow outbound LLM calls.</b> Off by default. When off, nothing is sent to any AI provider. The API key lives only in
          <code> .env</code> (<code>ANTHROPIC_API_KEY</code>).</span>
      </label>
      <div className="mt-3 grid grid-cols-2 gap-3 lg:grid-cols-5">
        <Field label="Model id" hint={`In use: ${page.data?.settings.model ?? "…"} (blank = CLAUDE_MODEL from .env)`}>
          <Input placeholder="e.g. claude-opus-5-5" value={form.model} onChange={(e) => setForm({ ...form, model: e.target.value.trim() })} />
        </Field>
        <Field label="Effort">
          <Select value={form.effort} onChange={(e) => setForm({ ...form, effort: e.target.value })}>
            {["low", "medium", "high", "xhigh", "max"].map((m) => <option key={m}>{m}</option>)}
          </Select>
        </Field>
        <Field label="Monthly call cap"><Input inputMode="numeric" value={form.monthly_call_cap} onChange={(e) => setForm({ ...form, monthly_call_cap: e.target.value.replace(/\D/g, "") })} /></Field>
        <Field label="$ per M input tokens" hint="no default"><Input inputMode="decimal" placeholder="not set" value={form.price_in_per_mtok} onChange={(e) => setForm({ ...form, price_in_per_mtok: numeric(e.target.value) })} /></Field>
        <Field label="$ per M output tokens" hint="no default"><Input inputMode="decimal" placeholder="not set" value={form.price_out_per_mtok} onChange={(e) => setForm({ ...form, price_out_per_mtok: numeric(e.target.value) })} /></Field>
      </div>
      <p className="mt-1 text-xs text-status-moderate">Prices are only used for the cost estimate. Verify them against the provider&apos;s pricing page for the model you use.</p>
      <label className="mt-3 flex items-start gap-2 text-sm">
        <input type="checkbox" className="mt-1" checked={form.refusal_fallback} onChange={(e) => setForm({ ...form, refusal_fallback: e.target.checked })} />
        <span>Refusal fallback (default off): if the model declines a request, let the provider re-run it on its recommended fallback
          model. When a different model answers, the card says which one.</span>
      </label>
      <label className="mt-2 flex items-center gap-2 text-sm">
        <input type="checkbox" checked={form.weekly_job} onChange={(e) => setForm({ ...form, weekly_job: e.target.checked })} />
        Weekly job (Sundays): refresh stock analyses only for holdings with new events, within the cap
      </label>
      <div className="mt-3 flex flex-wrap items-center gap-3">
        <Button disabled={busy} onClick={() => submit()}>Save AI settings</Button>
        {feedback}
      </div>
      {status.data && (
        <p className="mt-2 text-xs text-muted-foreground">
          {status.data.gate ? `Status: ${status.data.gate}` : "Status: ready."} This month: {status.data.usage.calls_this_month}/{status.data.usage.cap} calls,
          {" "}{status.data.usage.input_tokens.toLocaleString("en-IN")} input + {status.data.usage.output_tokens.toLocaleString("en-IN")} output tokens
          {status.data.usage.estimated_cost_usd ? ` ≈ $${status.data.usage.estimated_cost_usd}` : ""}. {status.data.usage.pricing_note}
        </p>
      )}
    </Section>
  );
}

const RULE_METRICS = ["debt_to_equity", "interest_coverage", "peg", "roe", "pe_vs_peers", "fcf_positive", "fcf_not_declining"];

function Rubric({ s, onSaved }: { s: Settings; onSaved: () => void }) {
  const [r, setR] = useState(s.sections.rubric.value);
  const { save, reset, busy, feedback } = useSaver("rubric", onSaved);
  const num = (k: "pe_vs_peer_tolerance_pct" | "peg_max" | "roe_min_pct" | "de_max", label: string) => (
    <Field label={label}><Input inputMode="decimal" value={r[k]} onChange={(e) => setR({ ...r, [k]: numeric(e.target.value) })} /></Field>
  );
  return (
    <Section title="Valuation framework rubric" aside={s.sections.rubric.is_set ? "Custom" : "Defaults"}>
      <p className="mb-3 text-xs text-muted-foreground">Each check is shown as meets / does not meet / N/A. There is no overall score or verdict.</p>
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        {num("pe_vs_peer_tolerance_pct", "P/E ≤ peer median + tolerance (%)")}
        {num("peg_max", "PEG below")}
        {num("roe_min_pct", "ROE above (%)")}
        {num("de_max", "Debt/equity below")}
      </div>
      <div className="mt-3 flex flex-wrap gap-4 text-sm">
        <label className="flex items-center gap-2"><input type="checkbox" checked={r.fcf_positive} onChange={(e) => setR({ ...r, fcf_positive: e.target.checked })} />FCF positive</label>
        <label className="flex items-center gap-2"><input type="checkbox" checked={r.fcf_not_declining} onChange={(e) => setR({ ...r, fcf_not_declining: e.target.checked })} />FCF not declining (latest ≥ previous year)</label>
      </div>
      <div className="mt-3 flex flex-wrap items-center gap-3">
        <Button disabled={busy} onClick={() => save(r)}>Save rubric</Button>
        {s.sections.rubric.is_set && <Button variant="ghost" disabled={busy} onClick={reset}>Reset to defaults</Button>}
        {feedback}
      </div>
    </Section>
  );
}

function SectorRules({ s, onSaved }: { s: Settings; onSaved: () => void }) {
  const [rows, setRows] = useState(() => Object.entries(s.sections.sector_rules.value).map(([sector, m]) => ({ sector, metrics: m })));
  const { save, reset, busy, feedback } = useSaver("sector_rules", onSaved);
  return (
    <Section title="Sector rules" aside="Checks shown as “not applicable for this sector”">
      <div className="flex flex-col gap-2">
        {rows.map((row, i) => (
          <div key={i} className="flex flex-col gap-1 rounded-md border border-border p-2">
            <div className="flex gap-2">
              <Input value={row.sector} placeholder="Sector (as shown on Sectors)" onChange={(e) => setRows(rows.map((x, j) => j === i ? { ...x, sector: e.target.value } : x))} />
              <Button variant="ghost" size="sm" onClick={() => setRows(rows.filter((_, j) => j !== i))}>Remove</Button>
            </div>
            <div className="flex flex-wrap gap-3 text-xs">
              {RULE_METRICS.map((m) => (
                <label key={m} className="flex items-center gap-1">
                  <input type="checkbox" checked={row.metrics.includes(m)}
                         onChange={() => setRows(rows.map((x, j) => j === i ? { ...x, metrics: x.metrics.includes(m) ? x.metrics.filter((y) => y !== m) : [...x.metrics, m] } : x))} />{m}
                </label>
              ))}
            </div>
          </div>
        ))}
        <div><Button variant="outline" size="sm" onClick={() => setRows([...rows, { sector: "", metrics: [] }])}>Add sector</Button></div>
      </div>
      <div className="mt-3 flex flex-wrap items-center gap-3">
        <Button disabled={busy || rows.some((x) => !x.sector.trim())} onClick={() => save(Object.fromEntries(rows.map((x) => [x.sector.trim(), x.metrics])))}>Save sector rules</Button>
        {s.sections.sector_rules.is_set && <Button variant="ghost" disabled={busy} onClick={reset}>Reset to defaults</Button>}
        {feedback}
      </div>
    </Section>
  );
}

function NewsFeeds({ s, onSaved }: { s: Settings; onSaved: () => void }) {
  const [feeds, setFeeds] = useState(s.sections.news.value.feeds);
  const { save, reset, busy, feedback } = useSaver("news", onSaved);
  return (
    <Section title="News feeds" aside="robots.txt is checked before every fetch">
      <div className="flex flex-col gap-2">
        {feeds.map((f, i) => (
          <div key={i} className="grid grid-cols-[8rem_1fr_auto] gap-2">
            <Input value={f.name} aria-label="Feed name" onChange={(e) => setFeeds(feeds.map((x, j) => j === i ? { ...x, name: e.target.value } : x))} />
            <Input value={f.url} aria-label="Feed URL" onChange={(e) => setFeeds(feeds.map((x, j) => j === i ? { ...x, url: e.target.value } : x))} />
            <Button variant="ghost" size="sm" onClick={() => setFeeds(feeds.filter((_, j) => j !== i))}>Remove</Button>
          </div>
        ))}
        <div><Button variant="outline" size="sm" onClick={() => setFeeds([...feeds, { name: "", url: "https://" }])}>Add feed</Button></div>
      </div>
      <p className="mt-2 text-xs text-muted-foreground">NSE&apos;s official announcement feeds are always used. Google News RSS is attempted but its robots.txt disallows automated access, so it shows as unavailable.</p>
      <div className="mt-3 flex flex-wrap items-center gap-3">
        <Button disabled={busy} onClick={() => save({ feeds })}>Save feeds</Button>
        {s.sections.news.is_set && <Button variant="ghost" disabled={busy} onClick={reset}>Reset to defaults</Button>}
        {feedback}
      </div>
    </Section>
  );
}

const CATS = ["results", "order win / contract", "dividend", "board meeting", "acquisition / merger", "regulatory / legal",
              "management change", "rating action", "other"];

function AlertRules({ s, onSaved }: { s: Settings; onSaved: () => void }) {
  const [r, setR] = useState(s.sections.alerts.value);
  const { save, busy, feedback } = useSaver("alerts", onSaved);
  const toggle = (k: "announcement" | "concentration_change" | "disclosure_stale" | "review_due") => setR({ ...r, [k]: !r[k] });
  return (
    <Section title="Alert rules" aside="In-app only">
      <div className="flex flex-col gap-2 text-sm">
        <label className="flex items-center gap-2"><input type="checkbox" checked={r.announcement} onChange={() => toggle("announcement")} />New announcement for a holding I own, in these categories:</label>
        <div className="flex flex-wrap gap-2 pl-6">
          {CATS.map((c) => (
            <label key={c} className="flex items-center gap-1 text-xs">
              <input type="checkbox" checked={r.announcement_categories.includes(c)}
                     onChange={() => setR({ ...r, announcement_categories: r.announcement_categories.includes(c) ? r.announcement_categories.filter((x) => x !== c) : [...r.announcement_categories, c] })} />{c}
            </label>
          ))}
        </div>
        <label className="flex items-center gap-2"><input type="checkbox" checked={r.concentration_change} onChange={() => toggle("concentration_change")} />Company / sector / overlap concentration level changed</label>
        <label className="flex items-center gap-2"><input type="checkbox" checked={r.disclosure_stale} onChange={() => toggle("disclosure_stale")} />A fund disclosure in use became stale</label>
        <label className="flex items-center gap-2"><input type="checkbox" checked={r.review_due} onChange={() => toggle("review_due")} />A thesis review date was reached</label>
      </div>
      <div className="mt-3 flex flex-wrap items-center gap-3"><Button disabled={busy} onClick={() => save(r)}>Save rules</Button>{feedback}</div>
    </Section>
  );
}
