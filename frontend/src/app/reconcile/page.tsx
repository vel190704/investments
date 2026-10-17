"use client";

import { useState } from "react";
import { ErrorBox, Loading, Notice, PageHeader, Section } from "@/components/common";
import { Field, Select, numeric } from "@/components/form";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { apiPost, errorText, useApi, type ReconcileRow } from "@/lib/api";
import { formatPrice, formatQty } from "@/lib/format";

type Status = { groww_enabled: boolean; api_key_set: boolean; totp_secret_set: boolean; token_valid: boolean; kite_mf: string; read_only: boolean };
type Recon = { ok: boolean; error?: string; broker?: string; compared?: number; broker_holdings?: number;
               differences: ReconcileRow[]; not_compared: string[]; note?: string };
const KIND: Record<string, string> = {
  MISSING_IN_DB: "At broker, not in your records", MISSING_AT_BROKER: "In your records, not at broker",
  QUANTITY: "Quantity differs", AVG_PRICE: "Average price differs (>0.5%)", "QUANTITY+AVG_PRICE": "Quantity and average price differ",
};

export default function ReconcilePage() {
  const status = useApi<Status>("/broker/status");
  const [run, setRun] = useState(0);
  const recon = useApi<Recon>(`/reconcile?run=${run}`);
  const [code, setCode] = useState("");
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [draft, setDraft] = useState<ReconcileRow | null>(null);

  async function login() {
    try {
      const r = await apiPost<{ expiry: string | null }>("/broker/groww/token", { totp: code || null });
      setMsg({ ok: true, text: `Connected (read-only). Token valid until ${r.expiry ?? "today"}; it is kept in memory only.` });
      setCode("");
      status.reload();
      setRun((n) => n + 1);
    } catch (e) {
      setMsg({ ok: false, text: errorText(e) });
    }
  }

  const s = status.data;
  return (
    <>
      <PageHeader title="Broker reconciliation" subtitle="Read-only comparison of Groww holdings with your records, by ISIN. Nothing is ever changed automatically." />
      {status.loading && !s && <Loading />}
      {s && !s.groww_enabled && (
        <Notice>Groww integration is off. To use it, set <code>GROWW_ENABLED=true</code>, <code>GROWW_API_KEY</code> and optionally <code>GROWW_TOTP_SECRET</code> in <code>.env</code> and restart the backend (see README). The rest of the app works the same without it.</Notice>
      )}
      {s?.groww_enabled && (
        <Section title="Connection" aside={`Read-only · ${s.kite_mf} for Zerodha Coin`}>
          <p className="mb-2 text-sm">API key {s.api_key_set ? "set" : "missing"} · TOTP secret {s.totp_secret_set ? "set" : "not set"} · token {s.token_valid ? "valid" : "not active"}</p>
          {!s.token_valid && (
            <div className="flex flex-wrap items-end gap-2">
              {!s.totp_secret_set && <Field label="Current 6-digit TOTP code"><Input inputMode="numeric" maxLength={6} value={code} onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))} /></Field>}
              <Button onClick={login}>Connect (daily)</Button>
            </div>
          )}
        </Section>
      )}
      {msg && (msg.ok ? <Notice>{msg.text}</Notice> : <ErrorBox message={msg.text} />)}
      {recon.data && s?.groww_enabled && (
        <div className="mt-4 flex flex-col gap-4">
          {!recon.data.ok ? <ErrorBox message={recon.data.error ?? "Unavailable"} /> : (
            <Section title={`Differences (${recon.data.differences.length})`} aside={`${recon.data.compared} of your Groww holdings compared with ${recon.data.broker_holdings} at the broker`}>
              <p className="mb-2 text-xs text-muted-foreground">{recon.data.note}</p>
              {!recon.data.differences.length ? <p className="text-sm text-muted-foreground">No differences.</p> : (
                <table className="tnum w-full text-sm">
                  <thead className="text-xs text-muted-foreground"><tr><th className="py-1 text-left font-normal">Holding</th><th className="py-1 text-right font-normal">Qty (yours / broker)</th><th className="py-1 text-right font-normal">Avg (yours / broker)</th><th /></tr></thead>
                  <tbody>
                    {recon.data.differences.map((d) => (
                      <tr key={d.isin} className="border-t border-border">
                        <td className="py-1.5">{d.name}<div className="text-xs text-muted-foreground">{KIND[d.kind] ?? d.kind} · {d.isin}</div></td>
                        <td className="py-1.5 text-right">{formatQty(d.db_quantity)} / {formatQty(d.broker_quantity)}</td>
                        <td className="py-1.5 text-right">{d.db_avg_cost ? formatPrice(d.db_avg_cost) : "—"} / {d.broker_avg_price ? formatPrice(d.broker_avg_price) : "—"}</td>
                        <td className="py-1.5 text-right">{d.suggested && <Button size="sm" variant="outline" onClick={() => setDraft(d)}>Add as transaction…</Button>}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
              {recon.data.not_compared.length > 0 && <p className="mt-2 text-xs text-muted-foreground">Not compared (ISIN not confirmed on Mappings): {recon.data.not_compared.join(", ")}</p>}
            </Section>
          )}
          {draft && <Confirm row={draft} onDone={(t) => { setDraft(null); setMsg(t ? { ok: true, text: t } : null); setRun((n) => n + 1); }} />}
        </div>
      )}
    </>
  );
}

function Confirm({ row, onDone }: { row: ReconcileRow; onDone: (msg: string | null) => void }) {
  const sug = row.suggested!;
  const [type, setType] = useState(sug.type);
  const [qty, setQty] = useState(sug.quantity);
  const [price, setPrice] = useState(sug.price ?? "");
  const [date, setDate] = useState(new Date().toLocaleDateString("en-CA", { timeZone: "Asia/Kolkata" }));
  const [err, setErr] = useState<string | null>(null);
  const amount = qty && price ? (Number(qty) * Number(price)).toFixed(2) : "";
  async function confirm(e: React.FormEvent) {
    e.preventDefault();
    try {
      await apiPost("/transactions", {
        type, date, quantity: qty, price: price || null, amount, platform: "Groww",
        notes: `Added after reconciliation with Groww (${row.isin}); reviewed by me`,
        ...(row.instrument_id ? { instrument_id: row.instrument_id } : { asset_type: "STOCK", name: row.name, symbol: row.name }),
      });
      onDone(`Added an in-app ${type} for ${row.name}. It is labelled as an in-app entry and can be deleted on Transactions.`);
    } catch (x) {
      setErr(errorText(x));
    }
  }
  return (
    <Section title={`Review before adding — ${row.name}`} aside="Nothing is saved until you confirm">
      <form onSubmit={confirm} className="flex flex-col gap-3">
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          <Field label="Type"><Select value={type} onChange={(e) => setType(e.target.value)}><option>BUY</option><option>SELL</option></Select></Field>
          <Field label="Date (enter the real trade date)"><Input type="date" required value={date} onChange={(e) => setDate(e.target.value)} /></Field>
          <Field label="Quantity"><Input required value={qty} onChange={(e) => setQty(numeric(e.target.value))} /></Field>
          <Field label="Price (₹)" hint={amount ? `Amount ₹${amount}` : "Price needed to compute the amount"}><Input required value={price} onChange={(e) => setPrice(numeric(e.target.value))} /></Field>
        </div>
        {err && <ErrorBox message={err} />}
        <div className="flex gap-2"><Button type="submit" disabled={!amount}>Confirm and add</Button><Button type="button" variant="ghost" onClick={() => onDone(null)}>Cancel</Button></div>
      </form>
    </Section>
  );
}
