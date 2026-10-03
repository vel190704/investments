"use client";

import { useState } from "react";
import { ErrorBox, Loading, PageHeader, Section } from "@/components/common";
import { Field, Select } from "@/components/form";
import { apiGet, errorText, useApi, type Change, type Compare, type Snapshot } from "@/lib/api";
import { formatDate, formatDateTime, formatINR, formatPct, formatPrice, formatQty, signClass } from "@/lib/format";
import { cn } from "@/lib/utils";

const KINDS: Record<string, string> = {
  TXN_ADDED: "Transaction added", TXN_REMOVED: "Transaction removed", QTY_CHANGED: "Quantity changed",
  AVG_COST_CHANGED: "Average cost changed", ALLOCATION_CHANGED: "Allocation changed",
};

export default function ChangesPage() {
  const [kind, setKind] = useState("");
  const log = useApi<Change[]>(`/changes?limit=300${kind ? `&kind=${kind}` : ""}`);
  const snaps = useApi<Snapshot[]>("/snapshots");
  const [a, setA] = useState("");
  const [b, setB] = useState("live");
  const [cmp, setCmp] = useState<Compare | null>(null);
  const [err, setErr] = useState<string | null>(null);

  async function run(av: string, bv: string) {
    if (!av) return;
    try {
      setCmp(await apiGet<Compare>(`/compare?a=${av}&b=${bv}`));
      setErr(null);
    } catch (e) {
      setErr(errorText(e));
    }
  }

  const dates = snaps.data?.map((s) => s.snapshot_date) ?? [];
  return (
    <>
      <PageHeader title="Changes" subtitle="What changed, when and why: transactions, positions, and allocation between snapshots." />
      <div className="flex flex-col gap-4">
        <Section title="Compare">
          {!dates.length ? <p className="text-sm text-muted-foreground">No snapshots yet — take one on the History page.</p> : (
            <div className="flex flex-col gap-4">
              <div className="flex flex-wrap items-end gap-3">
                <Field label="From (snapshot A)">
                  <Select value={a} onChange={(e) => { setA(e.target.value); void run(e.target.value, b); }}>
                    <option value="">Choose a date…</option>
                    {dates.map((d) => <option key={d} value={d}>{formatDate(d)}</option>)}
                  </Select>
                </Field>
                <Field label="To (B)">
                  <Select value={b} onChange={(e) => { setB(e.target.value); void run(a, e.target.value); }}>
                    <option value="live">Today (current holdings)</option>
                    {dates.map((d) => <option key={d} value={d}>{formatDate(d)}</option>)}
                  </Select>
                </Field>
              </div>
              {err && <ErrorBox message={err} />}
              {cmp && <CompareView c={cmp} />}
            </div>
          )}
        </Section>

        <Section
          title="Change log"
          aside={
            <Select aria-label="Filter by kind" value={kind} onChange={(e) => setKind(e.target.value)}>
              <option value="">All kinds</option>
              {Object.entries(KINDS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </Select>
          }
        >
          {log.error && <ErrorBox message={log.error} />}
          {log.loading && !log.data && <Loading />}
          {log.data && !log.data.length && <p className="text-sm text-muted-foreground">No changes recorded yet.</p>}
          <ul className="flex flex-col">
            {log.data?.map((e) => (
              <li key={e.id} className="flex flex-col gap-0.5 border-b border-border py-2 last:border-0 sm:flex-row sm:gap-3">
                <span className="tnum shrink-0 text-xs text-muted-foreground sm:w-44">{formatDateTime(e.occurred_at)}</span>
                <span className="shrink-0 text-xs sm:w-40">{KINDS[e.kind] ?? e.kind} <span className="text-muted-foreground">· {e.cause}</span></span>
                <span className="text-sm">{e.summary}</span>
              </li>
            ))}
          </ul>
        </Section>
      </div>
    </>
  );
}

function CompareView({ c }: { c: Compare }) {
  const changed = c.instruments.filter((r) => r.status !== "unchanged" || r.value_change_paise);
  return (
    <div className="flex flex-col gap-4">
      <p className="text-sm">
        {c.label_a} → {c.label_b}: total {formatINR(c.total_a_paise)} → {formatINR(c.total_b_paise)}{" "}
        <span className={signClass(c.total_change_paise)}>({formatINR(c.total_change_paise, { signed: true })})</span>
      </p>
      <div>
        <div className="mb-1 text-xs font-medium text-muted-foreground">By asset class</div>
        <table className="tnum w-full text-sm">
          <tbody>
            {c.asset_classes.map((x) => (
              <tr key={x.asset_class} className="border-t border-border">
                <td className="py-1.5">{x.asset_class}</td>
                <td className="py-1.5 text-right">{formatPct(x.weight_a)} → <b>{formatPct(x.weight_b)}</b></td>
                <td className="py-1.5 text-right text-muted-foreground">{formatINR(x.value_a_paise)} → {formatINR(x.value_b_paise)}</td>
                <td className={`py-1.5 text-right ${signClass(x.value_change_paise)}`}>{formatINR(x.value_change_paise, { signed: true })}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div>
        <div className="mb-1 text-xs font-medium text-muted-foreground">By instrument ({changed.length} with changes)</div>
        <div className="overflow-x-auto">
          <table className="tnum w-full text-sm">
            <thead className="text-xs text-muted-foreground">
              <tr>
                <th className="py-1 text-left font-normal">Instrument</th>
                <th className="py-1 text-right font-normal">Qty</th>
                <th className="py-1 text-right font-normal">Avg cost</th>
                <th className="py-1 text-right font-normal">Weight</th>
                <th className="py-1 text-right font-normal">Value change</th>
              </tr>
            </thead>
            <tbody>
              {changed.map((r) => (
                <tr key={r.instrument_id} className="border-t border-border">
                  <td className="py-1.5">
                    {r.name}{" "}
                    <span className={cn("text-xs", r.status === "unchanged" ? "text-muted-foreground" : "text-foreground")}>
                      {r.status === "unchanged" ? "price move only" : r.status}
                    </span>
                  </td>
                  <td className="py-1.5 text-right">{formatQty(r.quantity_a)} → {formatQty(r.quantity_b)}</td>
                  <td className="py-1.5 text-right whitespace-nowrap">
                    {r.avg_cost_a ? formatPrice(r.avg_cost_a) : "—"} → {r.avg_cost_b ? formatPrice(r.avg_cost_b) : "—"}
                  </td>
                  <td className="py-1.5 text-right whitespace-nowrap">{formatPct(r.weight_a)} → {formatPct(r.weight_b)}</td>
                  <td className={`py-1.5 text-right ${signClass(r.value_change_paise)}`}>
                    {r.value_change_paise === null ? "Data unavailable" : formatINR(r.value_change_paise, { signed: true })}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
