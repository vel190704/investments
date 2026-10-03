"use client";

import { useState } from "react";
import { ErrorBox, Loading, Notice, PageHeader, Section } from "@/components/common";
import { Field, Select, numeric } from "@/components/form";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { apiDelete, apiPost, errorText, useApi, type InstrumentRef, type Txn } from "@/lib/api";
import { formatDate, formatINR, formatPrice, formatQty } from "@/lib/format";
import { cn } from "@/lib/utils";

const TYPES = ["BUY", "SIP", "SELL", "DIVIDEND"] as const;
const today = () => new Date().toLocaleDateString("en-CA", { timeZone: "Asia/Kolkata" });

export default function TransactionsPage() {
  const txns = useApi<Txn[]>("/transactions");
  const instruments = useApi<InstrumentRef[]>("/instruments");
  const [filter, setFilter] = useState<"all" | "ui" | "excel">("all");
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  async function remove(t: Txn) {
    if (!window.confirm(`Delete this in-app entry?\n${t.type} ${t.symbol ?? t.name} on ${t.date}`)) return;
    try {
      await apiDelete(`/transactions/${t.id}`);
      setMsg("Entry deleted (recorded in the change log).");
      setErr(null);
      txns.reload();
    } catch (e) {
      setErr(errorText(e));
    }
  }

  const rows = (txns.data ?? []).filter((t) => filter === "all" || t.source === filter);
  return (
    <>
      <PageHeader
        title="Transactions"
        subtitle="Workbook rows (excel) are managed in your Excel file. In-app entries (ui) are added here and are never removed by a re-import."
        actions={<a href="/api/export.xlsx" className="inline-flex h-8 items-center rounded-lg border border-border px-2.5 text-sm hover:bg-muted">Export to Excel</a>}
      />
      <div className="flex flex-col gap-4">
        <AddForm instruments={instruments.data ?? []} onAdded={(m) => { setMsg(m); setErr(null); txns.reload(); instruments.reload(); }} />
        {msg && <Notice>{msg}</Notice>}
        {err && <ErrorBox message={err} />}
        <Section
          title={`All transactions (${txns.data?.length ?? 0})`}
          aside={
            <Select aria-label="Filter by source" value={filter} onChange={(e) => setFilter(e.target.value as typeof filter)}>
              <option value="all">All sources</option>
              <option value="ui">In-app (ui)</option>
              <option value="excel">Workbook (excel)</option>
            </Select>
          }
        >
          {txns.error && <ErrorBox message={txns.error} />}
          {txns.loading && !txns.data && <Loading />}
          {txns.data && (
            <Table className="tnum">
              <TableHeader>
                <TableRow>
                  <TableHead>Date</TableHead><TableHead>Type</TableHead><TableHead>Instrument</TableHead>
                  <TableHead className="text-right">Qty / units</TableHead><TableHead className="text-right">Price / NAV</TableHead>
                  <TableHead className="text-right">Amount</TableHead><TableHead>Source</TableHead><TableHead />
                </TableRow>
              </TableHeader>
              <TableBody>
                {rows.map((t) => (
                  <TableRow key={t.id}>
                    <TableCell className="whitespace-nowrap">{formatDate(t.date)}</TableCell>
                    <TableCell>{t.type}</TableCell>
                    <TableCell className="max-w-64 whitespace-normal">
                      <div className="font-medium">{t.symbol ?? t.name}</div>
                      {t.notes && <div className="text-xs text-muted-foreground">{t.notes}</div>}
                    </TableCell>
                    <TableCell className="text-right">{t.quantity ? formatQty(t.quantity) : "—"}</TableCell>
                    <TableCell className="text-right">{t.price ? formatPrice(t.price, t.asset_type === "MF" ? 4 : 2) : "—"}</TableCell>
                    <TableCell className="text-right">{formatINR(t.amount_paise)}</TableCell>
                    <TableCell>
                      <span className={cn("rounded border px-1.5 py-0.5 text-xs",
                        t.source === "ui" ? "border-series-1/50 text-series-1" : "border-border text-muted-foreground")}>
                        {t.source === "ui" ? "in-app" : `excel · row ${t.source_row}`}
                      </span>
                    </TableCell>
                    <TableCell className="text-right">
                      {t.source === "ui" && <Button size="sm" variant="ghost" onClick={() => remove(t)}>Delete</Button>}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </Section>
      </div>
    </>
  );
}

function AddForm({ instruments, onAdded }: { instruments: InstrumentRef[]; onAdded: (msg: string) => void }) {
  const [type, setType] = useState<(typeof TYPES)[number]>("SIP");
  const [instrumentId, setInstrumentId] = useState("");
  const [isNew, setIsNew] = useState(false);
  const [assetType, setAssetType] = useState("STOCK");
  const [name, setName] = useState("");
  const [symbol, setSymbol] = useState("");
  const [date, setDate] = useState(today());
  const [qty, setQty] = useState("");
  const [price, setPrice] = useState("");
  const [amount, setAmount] = useState("");
  const [charges, setCharges] = useState("");
  const [notes, setNotes] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const inst = instruments.find((i) => String(i.instrument_id) === instrumentId);
  const effAsset = isNew ? assetType : inst?.asset_type;
  const isMF = effAsset === "MF";
  const isDiv = type === "DIVIDEND";
  const implied = qty && price ? (Number(qty) * Number(price)).toFixed(2) : null;

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const body = {
        date, type, notes: notes || null, charges: charges || null,
        quantity: isDiv ? null : qty, price: isDiv ? null : price || null, amount,
        platform: isNew ? (assetType === "MF" ? "Zerodha Coin" : "Groww") : inst?.platform,
        ...(isNew ? { asset_type: assetType, name, symbol: assetType === "MF" ? null : symbol } : { instrument_id: Number(instrumentId) }),
      };
      const r = await apiPost<{ id: number; warnings: string[] }>("/transactions", body);
      onAdded(`Added ${type} for ${isNew ? name : inst?.symbol ?? inst?.name}.` +
        (r.warnings.length ? ` Warnings: ${r.warnings.join("; ")}` : ""));
      setQty(""); setPrice(""); setAmount(""); setCharges(""); setNotes("");
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Section title="Add transaction" aside="Same validation as the Excel import. Amount is authoritative.">
      <form onSubmit={submit} className="flex flex-col gap-3">
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <Field label="Type">
            <Select value={type} onChange={(e) => setType(e.target.value as typeof type)}>
              {TYPES.map((t) => <option key={t}>{t}</option>)}
            </Select>
          </Field>
          <Field label="Instrument">
            <Select value={isNew ? "__new" : instrumentId} required
                    onChange={(e) => { const v = e.target.value; setIsNew(v === "__new"); setInstrumentId(v === "__new" ? "" : v); }}>
              <option value="">Choose…</option>
              {instruments.map((i) => <option key={i.instrument_id} value={i.instrument_id}>{i.symbol ?? i.name}</option>)}
              <option value="__new">+ New instrument…</option>
            </Select>
          </Field>
          <Field label="Date"><Input type="date" required value={date} onChange={(e) => setDate(e.target.value)} /></Field>
          <Field label="Amount (₹, total)" hint={!isDiv && implied ? `units × price = ₹${implied}` : undefined}>
            <Input inputMode="decimal" required value={amount} onChange={(e) => setAmount(numeric(e.target.value))} />
          </Field>
        </div>
        {isNew && (
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            <Field label="Asset type">
              <Select value={assetType} onChange={(e) => setAssetType(e.target.value)}>
                <option>STOCK</option><option>ETF</option><option>MF</option>
              </Select>
            </Field>
            <Field label={assetType === "MF" ? "Fund name (as in Coin)" : "Company / ETF name"}>
              <Input required value={name} onChange={(e) => setName(e.target.value)} />
            </Field>
            {assetType !== "MF" && (
              <Field label="NSE symbol"><Input required value={symbol} onChange={(e) => setSymbol(e.target.value.toUpperCase())} /></Field>
            )}
          </div>
        )}
        {!isDiv && (
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            <Field label={isMF ? "Units (from Coin)" : "Quantity (shares)"}>
              <Input inputMode="decimal" required value={qty} onChange={(e) => setQty(numeric(e.target.value))} />
            </Field>
            <Field label={isMF ? "NAV (from Coin)" : "Price per share"}>
              <Input inputMode="decimal" value={price} onChange={(e) => setPrice(numeric(e.target.value))} />
            </Field>
            <Field label="Charges (₹, optional)">
              <Input inputMode="decimal" value={charges} onChange={(e) => setCharges(numeric(e.target.value))} />
            </Field>
          </div>
        )}
        <Field label="Notes (optional)"><Input value={notes} onChange={(e) => setNotes(e.target.value)} /></Field>
        {isNew && isMF && (
          <p className="text-xs text-muted-foreground">A new fund needs its AMFI scheme code confirmed on Mappings before it can be priced.</p>
        )}
        {error && <ErrorBox message={error} />}
        <div><Button type="submit" disabled={busy}>{busy ? "Saving…" : "Add transaction"}</Button></div>
      </form>
    </Section>
  );
}
