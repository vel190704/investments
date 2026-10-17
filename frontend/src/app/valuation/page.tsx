"use client";

import Link from "next/link";
import { useState } from "react";
import { AnalysisFooter, ErrorBox, Loading, Notice, PageHeader, Section } from "@/components/common";
import { Field } from "@/components/form";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { apiPost, apiPut, errorText, useApi, type StockValuation, type ValuationPage } from "@/lib/api";
import { formatDate, groupIndian } from "@/lib/format";
import { cn } from "@/lib/utils";

const PCT = new Set(["roe", "fcf_margin", "fcf_yield", "revenue_growth", "profit_growth"]);
const LABEL: Record<string, string> = {
  pe: "P/E", ps: "P/S", peg: "PEG", roe: "ROE", debt_to_equity: "Debt/equity", revenue_growth: "Revenue growth",
  profit_growth: "Profit growth", fcf_margin: "FCF margin", fcf_yield: "FCF yield", fcf_latest: "FCF (latest FY)",
  interest_coverage: "Interest coverage",
};
function fmt(metric: string, v: string | null | undefined): string {
  if (v === null || v === undefined) return "N/A";
  const n = Number(v);
  if (PCT.has(metric)) return `${(n * 100).toFixed(1)}%`;
  if (metric === "fcf_latest" || metric === "fcf") return `₹${groupIndian(Math.round(n / 1e7).toString().replace("-", ""))}${n < 0 ? " (neg.)" : ""} Cr`;
  if (metric === "debt_to_equity" || metric === "interest_coverage") return `${n.toFixed(2)}x`;
  return n.toFixed(2);
}
const STATUS_CLS: Record<string, string> = {
  MEETS: "border-status-low/50 text-status-low", "DOES NOT MEET": "border-status-high/50 text-status-high",
  "N/A": "border-border text-muted-foreground", "NOT APPLICABLE": "border-border text-muted-foreground", INFO: "border-border text-muted-foreground",
};

export default function ValuationPageView() {
  const { data, error, loading, reload } = useApi<ValuationPage>("/valuation");
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  async function refresh() {
    setBusy(true);
    try {
      const a = await apiPost<{ summary: string; errors: string[] }>("/fundamentals/refresh");
      const b = await apiPost<{ peers: string[]; errors: string[] }>("/peers/refresh");
      setMsg({ ok: true, text: `${a.summary}; peers fetched: ${b.peers.length}.` + ([...a.errors, ...b.errors].length ? ` Problems: ${[...a.errors, ...b.errors].slice(0, 4).join("; ")}` : "") });
      reload();
    } catch (e) {
      setMsg({ ok: false, text: errorText(e) });
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <PageHeader title="Valuation & peers"
                  subtitle="Your rubric applied to each stock, next to peers you chose and the company's own history. No overall score, ranking or verdict."
                  actions={<Button variant="outline" disabled={busy} onClick={refresh}>{busy ? "Fetching (rate-limited)…" : "Refresh fundamentals & peers"}</Button>} />
      {msg && (msg.ok ? <Notice>{msg.text}</Notice> : <ErrorBox message={msg.text} />)}
      {error && <ErrorBox message={error} />}
      {loading && !data && <Loading />}
      {data && (
        <div className="flex flex-col gap-4">
          <p className="text-xs text-muted-foreground">Rubric thresholds and sector rules: <Link className="underline" href="/settings">Settings</Link>. Values come from Yahoo Finance annual statements and Ticker.info; hover a value for its source.</p>
          {data.stocks.map((v) => <StockCard key={v.instrument_id} v={v} onSaved={reload} />)}
          <AnalysisFooter />
        </div>
      )}
    </>
  );
}

function StockCard({ v, onSaved }: { v: StockValuation; onSaved: () => void }) {
  const [open, setOpen] = useState(false);
  const [peers, setPeers] = useState(v.peers.symbols.join(", "));
  const [note, setNote] = useState(v.peers.note ?? "");
  const [err, setErr] = useState<string | null>(null);
  const peg = v.metrics.peg;
  async function savePeers(e: React.FormEvent) {
    e.preventDefault();
    try {
      await apiPut(`/peers/${v.instrument_id}`, { symbols: peers.split(/[,\s]+/).filter(Boolean), note });
      setErr(null);
      onSaved();
    } catch (x) {
      setErr(errorText(x));
    }
  }
  const counts = v.framework.reduce<Record<string, number>>((a, c) => ({ ...a, [c.status]: (a[c.status] ?? 0) + 1 }), {});
  return (
    <Section title={`${v.symbol} — ${v.name}`} aside={<button className="underline" onClick={() => setOpen(!open)}>{open ? "Close" : "Details"}</button>}>
      <div className="flex flex-wrap gap-x-5 gap-y-1 text-sm">
        {["pe", "ps", "peg", "roe", "debt_to_equity", "fcf_latest", "fcf_margin", "fcf_yield", "interest_coverage"].map((k) => {
          const m = v.metrics[k];
          return (
            <span key={k} title={m ? `${m.source ?? ""}${m.as_of ? ` · as of ${m.as_of}` : ""}${m.note ? ` · ${m.note}` : ""}${m.reason ? ` · ${m.reason}` : ""}` : "not fetched yet"}>
              <span className="text-xs text-muted-foreground">{LABEL[k]} </span>
              <span className={cn("tnum", !m?.value && "text-muted-foreground")}>{m?.value ? fmt(k, m.value) : "N/A"}</span>
            </span>
          );
        })}
      </div>
      <p className="mt-1 text-xs text-muted-foreground">
        {v.sector} · checks: {Object.entries(counts).map(([k, n]) => `${n} ${k.toLowerCase()}`).join(" · ")}
        {peg?.note && <> · PEG: {peg.note}</>}{!peg?.value && peg?.reason && <> · PEG N/A: {peg.reason}</>}
      </p>
      {open && (
        <div className="mt-4 flex flex-col gap-5">
          <div>
            <div className="mb-1 text-xs font-medium text-muted-foreground">Framework check (my rubric)</div>
            <table className="w-full text-sm">
              <tbody>
                {v.framework.map((c) => (
                  <tr key={c.key} className="border-t border-border align-top">
                    <td className="py-1.5 pr-2">{c.title}<div className="text-xs text-muted-foreground">{c.rule}</div></td>
                    <td className="tnum py-1.5 pr-2 text-xs">{c.value ?? "—"}</td>
                    <td className="py-1.5 pr-2"><span className={cn("rounded border px-1.5 py-0.5 text-xs font-semibold whitespace-nowrap", STATUS_CLS[c.status])}>{c.status}</span></td>
                    <td className="py-1.5 text-xs text-muted-foreground">{c.reason}{c.sources.filter(Boolean).length ? ` · ${c.sources.filter(Boolean).join("; ")}` : ""}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div>
            <div className="mb-1 text-xs font-medium text-muted-foreground">Peers chosen by me (max 8; nothing is suggested)</div>
            <form onSubmit={savePeers} className="grid grid-cols-1 gap-2 sm:grid-cols-[1fr_2fr_auto] sm:items-end">
              <Field label="NSE symbols, comma separated"><Input value={peers} placeholder="e.g. SIEMENS, ABB" onChange={(e) => setPeers(e.target.value.toUpperCase())} /></Field>
              <Field label="Why these peers"><Input value={note} onChange={(e) => setNote(e.target.value)} /></Field>
              <Button type="submit" variant="outline">Save peers</Button>
            </form>
            {err && <ErrorBox message={err} />}
            {v.peers.symbols.length > 0 && (
              <div className="mt-2 overflow-x-auto">
                <table className="tnum w-full text-xs">
                  <thead className="text-muted-foreground">
                    <tr><th className="py-1 text-left font-normal">Metric</th><th className="py-1 text-right font-normal">{v.symbol}</th>
                      <th className="py-1 text-right font-normal">Peer median</th>
                      {v.peers.symbols.map((p) => <th key={p} className="py-1 pl-2 text-right font-normal">{p}</th>)}</tr>
                  </thead>
                  <tbody>
                    {v.peers.comparisons.map((c) => (
                      <tr key={c.metric} className="border-t border-border">
                        <td className="py-1">{LABEL[c.metric] ?? c.metric}</td>
                        <td className="py-1 text-right font-medium">{fmt(c.metric, c.mine)}</td>
                        <td className="py-1 text-right" title={c.median_note ?? undefined}>{c.peer_median ? fmt(c.metric, c.peer_median) : "N/A"}</td>
                        {c.peers.map((p) => <td key={p.symbol} className="py-1 pl-2 text-right text-muted-foreground" title={p.note ?? undefined}>{p.value ? fmt(c.metric, p.value) : p.status === "NOT FETCHED" ? "…" : "N/A"}</td>)}
                      </tr>
                    ))}
                  </tbody>
                </table>
                <p className="mt-1 text-[11px] text-muted-foreground">A median needs at least 3 peers with a value; otherwise N/A. “…” = not fetched yet (Refresh).</p>
              </div>
            )}
          </div>

          <div>
            <div className="mb-1 text-xs font-medium text-muted-foreground">Own history (annual statements available)</div>
            {!v.history.length ? <p className="text-xs text-muted-foreground">No annual statements stored yet (Refresh).</p> : (
              <table className="tnum w-full text-xs">
                <thead className="text-muted-foreground">
                  <tr><th className="py-1 text-left font-normal">Fiscal year end</th><th className="py-1 text-right font-normal">ROE</th><th className="py-1 text-right font-normal">Net margin</th>
                    <th className="py-1 text-right font-normal">FCF</th><th className="py-1 text-right font-normal">FCF margin</th><th className="py-1 text-right font-normal">EPS</th><th className="py-1 text-right font-normal">P/E</th></tr>
                </thead>
                <tbody>
                  {v.history.map((h) => (
                    <tr key={h.fiscal_year_end} className="border-t border-border">
                      <td className="py-1">{formatDate(h.fiscal_year_end)}</td>
                      <td className="py-1 text-right">{fmt("roe", h.roe)}</td>
                      <td className="py-1 text-right">{fmt("fcf_margin", h.net_margin)}</td>
                      <td className="py-1 text-right">{fmt("fcf", h.fcf)}</td>
                      <td className="py-1 text-right">{fmt("fcf_margin", h.fcf_margin)}</td>
                      <td className="py-1 text-right">{h.eps ? Number(h.eps).toFixed(2) : "N/A"}</td>
                      <td className="py-1 text-right" title={h.pe.reason ?? `price ₹${h.pe.price} on ${h.pe.price_date} ÷ EPS ${h.pe.eps}`}>{h.pe.value ? Number(h.pe.value).toFixed(2) : "N/A"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
            <p className="mt-1 text-[11px] text-muted-foreground">{v.notes.join(" ")}</p>
          </div>
        </div>
      )}
    </Section>
  );
}
