"use client";

import { useState } from "react";
import { ErrorBox, Loading, Notice, PageHeader, Section } from "@/components/common";
import { Field } from "@/components/form";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { apiDelete, apiPost, apiPut, errorText, useApi, type FactCell, type Fundamentals } from "@/lib/api";
import { formatDate, formatPrice, groupIndian } from "@/lib/format";

function fmt(c: FactCell, v: string | null | undefined): string {
  if (v === null || v === undefined) return "—";
  const n = Number(v);
  if (c.unit === "inr") return `₹${groupIndian(Math.round(n / 1e7).toString())} Cr`;
  if (c.unit === "fraction") return `${(n * 100).toFixed(c.metric === "expense_ratio" ? 2 : 1)}%`;
  if (c.metric === "debt_to_equity") return `${n.toFixed(2)}×`;
  return n.toFixed(2);
}

export default function FundamentalsPage() {
  const { data, error, loading, reload } = useApi<Fundamentals>("/fundamentals");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [editing, setEditing] = useState<{ iid: number; cell: FactCell; name: string } | null>(null);

  async function refresh() {
    setBusy(true);
    try {
      const r = await apiPost<{ summary: string; errors: string[] }>("/fundamentals/refresh");
      setMsg(r.summary + (r.errors.length ? ` — ${r.errors.join("; ")}` : ""));
      reload();
    } catch (e) {
      setMsg(errorText(e));
    } finally {
      setBusy(false);
    }
  }

  function Cell({ iid, name, c }: { iid: number; name: string; c: FactCell }) {
    const title = c.source ? `${c.source}${c.as_of ? ` · as of ${c.as_of}` : ""}${c.fetched_at ? ` · fetched ${c.fetched_at.slice(0, 10)}` : ""}${c.note ? ` · ${c.note}` : ""}` : undefined;
    return (
      <td className="py-1.5 pr-3 text-right align-top" title={title}>
        {c.display_na ? (
          <span className="block text-xs text-muted-foreground">{c.display_na}</span>
        ) : (
          <>
            <div>{c.text ?? fmt(c, c.value)}{c.manual && <span className="ml-1 rounded border border-series-1/50 px-1 text-[10px] text-series-1">manual</span>}</div>
            <div className="text-[11px] text-muted-foreground">{c.as_of ? formatDate(c.as_of) : ""}</div>
          </>
        )}
        {c.portfolio_sector_median && (
          <div className="text-[11px] text-muted-foreground">within my portfolio: {fmt(c, c.portfolio_sector_median)}</div>
        )}
        {c.manual_allowed && (
          <button type="button" className="mt-0.5 block w-full text-right text-[11px] text-muted-foreground underline" onClick={() => setEditing({ iid, cell: c, name })}>
            {c.manual ? "edit" : "enter"}
          </button>
        )}
      </td>
    );
  }

  return (
    <>
      <PageHeader
        title="Fundamentals"
        subtitle="Shown only when the source provides a plausible value; otherwise N/A with the reason. Hover a value for its source and date."
        actions={<Button variant="outline" disabled={busy} onClick={refresh}>{busy ? "Fetching…" : "Refresh from Yahoo Finance"}</Button>}
      />
      {msg && <Notice>{msg}</Notice>}
      {error && <ErrorBox message={error} />}
      {loading && !data && <Loading />}
      {editing && <ManualForm e={editing} onClose={() => setEditing(null)} onSaved={() => { setEditing(null); reload(); }} />}
      {data && (
        <div className="mt-4 flex flex-col gap-4">
          <Section title="Direct stocks">
            <div className="overflow-x-auto">
              <table className="tnum w-full text-sm">
                <thead className="text-xs text-muted-foreground">
                  <tr>
                    <th className="py-1 pr-3 text-left font-normal">Stock</th>
                    <th className="py-1 pr-3 text-right font-normal">Price</th>
                    {data.stocks[0]?.metrics.map((m) => <th key={m.metric} className="py-1 pr-3 text-right font-normal">{m.label}</th>)}
                  </tr>
                </thead>
                <tbody>
                  {data.stocks.map((s) => (
                    <tr key={s.instrument_id} className="border-t border-border">
                      <td className="py-1.5 pr-3 align-top">
                        <div className="font-medium">{s.symbol}</div>
                        <div className="text-xs text-muted-foreground">{s.sector}</div>
                      </td>
                      <td className="py-1.5 pr-3 text-right align-top" title={s.price_source ?? undefined}>
                        {s.price ? formatPrice(s.price) : <span className="text-xs text-muted-foreground">Data unavailable</span>}
                        <div className="text-[11px] text-muted-foreground">{s.price_date ? formatDate(s.price_date) : ""}</div>
                      </td>
                      {s.metrics.map((c) => <Cell key={c.metric} iid={s.instrument_id} name={s.symbol} c={c} />)}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Section>
          <Section title="Mutual funds">
            <div className="overflow-x-auto">
              <table className="tnum w-full text-sm">
                <thead className="text-xs text-muted-foreground">
                  <tr>
                    <th className="py-1 pr-3 text-left font-normal">Fund</th>
                    {data.funds[0]?.metrics.map((m) => <th key={m.metric} className="py-1 pr-3 text-right font-normal">{m.label}</th>)}
                  </tr>
                </thead>
                <tbody>
                  {data.funds.map((f) => (
                    <tr key={f.instrument_id} className="border-t border-border">
                      <td className="max-w-64 py-1.5 pr-3 align-top">{f.name}</td>
                      {f.metrics.map((c) => <Cell key={c.metric} iid={f.instrument_id} name={f.name} c={c} />)}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Section>
          <Section title="Notes">
            <ul className="list-disc space-y-1 pl-5 text-sm text-muted-foreground">
              {data.notes.map((n) => <li key={n}>{n}</li>)}
              <li>Debt/equity: Yahoo reports a percentage (97.6); it is shown as a ratio (0.98×).</li>
            </ul>
          </Section>
        </div>
      )}
    </>
  );
}

function ManualForm({ e, onClose, onSaved }: { e: { iid: number; cell: FactCell; name: string }; onClose: () => void; onSaved: () => void }) {
  const c = e.cell;
  const [value, setValue] = useState(c.manual ? (c.text ?? (c.unit === "fraction" ? String(Number(c.value) * 100) : c.value ?? "")) : "");
  const [source, setSource] = useState(c.manual && c.source ? c.source.replace(/^manual: /, "") : "");
  const [asOf, setAsOf] = useState(c.manual && c.as_of ? c.as_of : "");
  const [err, setErr] = useState<string | null>(null);

  async function save(ev: React.FormEvent) {
    ev.preventDefault();
    try {
      await apiPut(`/facts/${e.iid}/${c.metric}`, { value, source_note: source, as_of: asOf });
      onSaved();
    } catch (x) {
      setErr(errorText(x));
    }
  }
  async function remove() {
    await apiDelete(`/facts/${e.iid}/${c.metric}`);
    onSaved();
  }
  return (
    <Section title={`Manual ${c.label} — ${e.name}`}>
      <form onSubmit={save} className="flex flex-col gap-3">
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          <Field label={c.unit === "fraction" ? `${c.label} (%)` : c.label}>
            <Input required value={value} onChange={(x) => setValue(x.target.value)} />
          </Field>
          <Field label="Source note (required)" hint="e.g. Annual report FY2026 p.112; BSE shareholding pattern Jun 2026">
            <Input required value={source} onChange={(x) => setSource(x.target.value)} />
          </Field>
          <Field label="As of (required)"><Input type="date" required value={asOf} onChange={(x) => setAsOf(x.target.value)} /></Field>
        </div>
        {err && <ErrorBox message={err} />}
        <div className="flex gap-2">
          <Button type="submit">Save</Button>
          {c.manual && <Button type="button" variant="ghost" onClick={remove}>Delete manual value</Button>}
          <Button type="button" variant="ghost" onClick={onClose}>Cancel</Button>
        </div>
      </form>
    </Section>
  );
}
