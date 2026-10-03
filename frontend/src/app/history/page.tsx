"use client";

import Link from "next/link";
import { useState } from "react";
import { ErrorBox, Loading, Notice, PageHeader, Section } from "@/components/common";
import { GrowthChart } from "@/components/growth-chart";
import { Button } from "@/components/ui/button";
import { apiPost, errorText, useApi, type Series, type Snapshot } from "@/lib/api";
import { formatDate, formatDateTime, formatINR, signClass } from "@/lib/format";

export default function HistoryPage() {
  const series = useApi<Series>("/snapshots/series");
  const snaps = useApi<Snapshot[]>("/snapshots");
  const [msg, setMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function take() {
    setBusy(true);
    try {
      const r = await apiPost<{ snapshot_date: string; partial: boolean; unpriced: string[] }>("/snapshots");
      setMsg(`Snapshot stored for ${formatDate(r.snapshot_date)} (one per day; a later snapshot the same day replaces it)` +
        (r.partial ? `. Partial: ${r.unpriced.length} holding(s) had no price.` : "."));
      series.reload();
      snaps.reload();
    } catch (e) {
      setMsg(errorText(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <PageHeader
        title="History"
        subtitle="One snapshot per day is stored after each price refresh (manual, start-up or the daily scheduled job). Nothing before the first snapshot is estimated."
        actions={<Button variant="outline" onClick={take} disabled={busy}>{busy ? "Saving…" : "Take snapshot"}</Button>}
      />
      <div className="flex flex-col gap-4">
        {msg && <Notice>{msg}</Notice>}
        <Section title="Value vs invested">
          {series.error && <ErrorBox message={series.error} />}
          {series.loading && !series.data && <Loading />}
          {series.data && !series.data.enough_history && (
            <div className="flex flex-col items-start gap-2 py-6">
              <p className="text-sm font-medium">History builds from today.</p>
              <p className="max-w-xl text-sm text-muted-foreground">
                {series.data.points.length === 1
                  ? `First snapshot: ${formatDate(series.data.points[0].date)} — value ${formatINR(series.data.points[0].value_paise)}, invested ${formatINR(series.data.points[0].invested_paise)}. `
                  : "No snapshots yet. "}
                The growth chart appears once there are at least two daily snapshots.
              </p>
            </div>
          )}
          {series.data?.enough_history && <GrowthChart points={series.data.points} />}
        </Section>
        <Section title={`Snapshots (${snaps.data?.length ?? 0})`} aside={<Link className="underline" href="/changes">Compare snapshots</Link>}>
          {snaps.data?.length ? (
            <table className="tnum w-full text-sm">
              <thead className="text-xs text-muted-foreground">
                <tr>
                  <th className="py-1 text-left font-normal">Date</th>
                  <th className="py-1 text-right font-normal">Value</th>
                  <th className="py-1 text-right font-normal">Invested</th>
                  <th className="py-1 text-right font-normal">Unrealised P&L</th>
                  <th className="py-1 pl-3 text-left font-normal">Notes</th>
                </tr>
              </thead>
              <tbody>
                {snaps.data.map((p) => {
                  const pnl = p.total_value_paise - p.invested_priced_paise;
                  return (
                    <tr key={p.snapshot_date} className="border-t border-border align-top">
                      <td className="py-1.5 whitespace-nowrap">{formatDate(p.snapshot_date)}</td>
                      <td className="py-1.5 text-right">{formatINR(p.total_value_paise)}</td>
                      <td className="py-1.5 text-right">{formatINR(p.total_invested_paise)}</td>
                      <td className={`py-1.5 text-right ${signClass(pnl)}`}>{formatINR(pnl, { signed: true })}</td>
                      <td className="py-1.5 pl-3 text-xs text-muted-foreground">
                        {p.trigger} · saved {formatDateTime(p.updated_at)}
                        {p.partial && ` · partial: no price for ${p.unpriced.join(", ")}`}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          ) : <p className="text-sm text-muted-foreground">No snapshots yet.</p>}
          <p className="mt-2 text-xs text-muted-foreground">P&L here is value minus the invested amount of priced holdings on that date.</p>
        </Section>
      </div>
    </>
  );
}
