"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { ErrorBox, Loading, Notice, PageHeader, Section } from "@/components/common";
import { Field, Select, numeric } from "@/components/form";
import { ProjectionChart, SCENARIO_COLOR } from "@/components/projection-chart";
import { Input } from "@/components/ui/input";
import { apiPost, errorText, type Projection } from "@/lib/api";
import { formatINR, formatPct } from "@/lib/format";

export default function ProjectionPage() {
  const [start, setStart] = useState("");
  const [monthly, setMonthly] = useState("");
  const [years, setYears] = useState("");
  const [step, setStep] = useState("");
  const [custom, setCustom] = useState("");
  const [res, setRes] = useState<{ key: string; data?: Projection; error?: string } | null>(null);

  const key = JSON.stringify([start, monthly, years, step, custom]);
  useEffect(() => {
    let cancelled = false;
    const t = setTimeout(() => {
      apiPost<Projection>("/projection", {
        start: start || null, monthly: monthly || null, years: years ? Number(years) : null,
        step_up: step || null, custom_rate: custom || null,
      }).then((data) => { if (!cancelled) setRes({ key, data }); },
              (e) => { if (!cancelled) setRes({ key, error: errorText(e) }); });
    }, 250);
    return () => { cancelled = true; clearTimeout(t); };
  }, [key, start, monthly, years, step, custom]);

  const p = res?.data;
  return (
    <>
      <PageHeader title="Projection" subtitle="Mathematical scenarios, not predictions. Change any input; blanks use the defaults shown." />
      <div className="flex flex-col gap-4">
        <Section title="Inputs">
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
            <Field label="Starting value (₹)" hint={p ? `default ${formatINR(p.defaults.start_paise, { decimals: false })} (current value)` : undefined}>
              <Input inputMode="decimal" placeholder="current" value={start} onChange={(e) => setStart(numeric(e.target.value))} />
            </Field>
            <Field label="Monthly contribution (₹)" hint={p ? `default ${formatINR(p.defaults.monthly_paise, { decimals: false })} (monthly_plan)` : undefined}>
              <Input inputMode="decimal" placeholder="from plan" value={monthly} onChange={(e) => setMonthly(numeric(e.target.value))} />
            </Field>
            <Field label="Years">
              <Select value={years} onChange={(e) => setYears(e.target.value)}>
                <option value="">Default{p ? ` (${p.defaults.years})` : ""}</option>
                {[5, 10, 15, 20, 25, 30].map((y) => <option key={y} value={y}>{y}</option>)}
              </Select>
            </Field>
            <Field label="Annual step-up">
              <Select value={step} onChange={(e) => setStep(e.target.value)}>
                <option value="">Default{p ? ` (${p.defaults.step_up_pct}%)` : ""}</option>
                {["0", "5", "10"].map((s) => <option key={s} value={s}>{s}%</option>)}
              </Select>
            </Field>
            <Field label="Custom rate % (optional)">
              <Input inputMode="decimal" value={custom} onChange={(e) => setCustom(e.target.value.replace(/[^0-9.-]/g, ""))} />
            </Field>
          </div>
        </Section>
        {res?.error && <ErrorBox message={res.error} />}
        {!res && <Loading />}
        {p && (
          <>
            {p.rates_note && (
              <Notice tone="warn">
                {p.rates_note} <Link className="underline" href="/settings">Review rates</Link>.
              </Notice>
            )}
            {p.defaults.start_excludes.length > 0 && !start && (
              <Notice>Default starting value excludes holdings without a price: {p.defaults.start_excludes.join(", ")}.</Notice>
            )}
            <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-4">
              {p.scenarios.map((s) => (
                <Section key={s.name} title={`${s.name} · ${s.annual_return_pct}% a year`}>
                  <div className="flex flex-col gap-2 text-sm">
                    <span aria-hidden className="h-1 w-10 rounded" style={{ background: SCENARIO_COLOR[s.name] }} />
                    <Row k="Starting value" v={formatINR(s.start_paise, { decimals: false })} />
                    <Row k="Total contributions" v={formatINR(s.total_contributions_paise, { decimals: false })} />
                    <Row k="Growth" v={formatINR(s.growth_paise, { decimals: false })} />
                    <Row k="Ending value (approx.)" v={formatINR(s.ending_value_paise, { decimals: false })} strong />
                    <Row k="Growth share of ending value" v={formatPct(s.growth_share_of_end)} />
                    <p className="mt-1 text-xs text-muted-foreground">{s.sentence}</p>
                  </div>
                </Section>
              ))}
            </div>
            <Section title={`Mathematical scenario over ${p.inputs.years} years`}>
              <ProjectionChart scenarios={p.scenarios} />
            </Section>
            <Section title="Formula and assumptions">
              <p className="tnum text-sm">{p.formula}</p>
              <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-muted-foreground">
                {p.assumptions.map((a) => <li key={a}>{a}</li>)}
              </ul>
              {p.closed_form_check_paise !== null && (
                <p className="mt-2 text-xs text-muted-foreground">
                  Cross-check (Base, closed form P(1+r)^n + C((1+r)^n − 1)/r): {formatINR(p.closed_form_check_paise, { decimals: false })}
                </p>
              )}
            </Section>
          </>
        )}
      </div>
    </>
  );
}

function Row({ k, v, strong }: { k: string; v: string; strong?: boolean }) {
  return (
    <div className="flex justify-between gap-2">
      <span className="text-muted-foreground">{k}</span>
      <span className={`tnum ${strong ? "font-semibold" : ""}`}>{v}</span>
    </div>
  );
}
