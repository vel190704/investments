"use client";

import { useState } from "react";
import { ErrorBox, Loading, Notice, PageHeader, Section } from "@/components/common";
import { Button } from "@/components/ui/button";
import { apiPost, useApi, type Candidate, type MappingRow, type Mappings } from "@/lib/api";
import { formatDate } from "@/lib/format";
import { cn } from "@/lib/utils";

export default function MappingsPage() {
  const { data, error, loading, reload } = useApi<Mappings>("/mappings");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

  async function act(path: string) {
    setBusy(true);
    try {
      const r = await apiPost<{ summary?: string }>(path);
      if (r.summary) setMsg(r.summary);
      await reload();
    } catch (e) {
      setMsg(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  const rows = data?.instruments ?? [];
  const pending = rows.filter((r) => r.status !== "CONFIRMED");
  const done = rows.filter((r) => r.status === "CONFIRMED");

  return (
    <>
      <PageHeader
        title="Identifier mappings"
        subtitle="ISINs come from NSE's securities lists (exact symbol match); AMFI scheme codes from NAVAll.txt (same plan & option, ranked by name similarity). Nothing is applied until you confirm it."
        actions={<Button variant="outline" disabled={busy} onClick={() => act("/mappings/resolve")}>Re-run matching</Button>}
      />
      {error && <ErrorBox message={error} />}
      {loading && !data && <Loading />}
      {msg && <Notice>{msg}</Notice>}
      {data && (
        <div className="mt-4 flex flex-col gap-4">
          <Section title={`Awaiting confirmation (${pending.length})`}>
            {pending.length === 0 ? (
              <p className="text-sm text-muted-foreground">All identifiers confirmed.</p>
            ) : (
              <div className="flex flex-col divide-y divide-border">
                {pending.map((r) => <PendingRow key={r.instrument_id} r={r} busy={busy} act={act} />)}
              </div>
            )}
          </Section>
          <Section title={`Confirmed (${done.length})`}>
            <table className="w-full text-sm">
              <tbody>
                {done.map((r) => {
                  const c = r.candidates.find((x) => x.kind === r.needed_kind && x.status === "CONFIRMED")!;
                  return (
                    <tr key={r.instrument_id} className="border-b border-border last:border-0">
                      <td className="py-1.5 pr-2">
                        <div className="font-medium">{r.symbol ?? r.name}</div>
                        <div className="text-xs text-muted-foreground">{c.label}</div>
                      </td>
                      <td className="tnum py-1.5 pr-2 text-right">
                        <div>{c.value}</div>
                        <div className="text-xs text-muted-foreground">
                          {r.asset_type === "MF" && r.isin ? `ISIN ${r.isin} · ` : ""}{c.source}
                        </div>
                      </td>
                      <td className="py-1.5 text-right">
                        <Button size="sm" variant="ghost" disabled={busy}
                                onClick={() => act(`/mappings/candidates/${c.id}/reject`)}>Undo</Button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </Section>
        </div>
      )}
    </>
  );
}

function PendingRow({ r, busy, act }: { r: MappingRow; busy: boolean; act: (p: string) => void }) {
  const cands = r.candidates.filter((c) => c.kind === r.needed_kind && c.status !== "REJECTED");
  return (
    <div className="py-3">
      <div className="mb-2">
        <span className="font-medium">{r.symbol ? `${r.symbol} — ` : ""}{r.name}</span>
        <span className="ml-2 text-xs text-muted-foreground">
          needs {r.needed_kind === "ISIN" ? "ISIN" : "AMFI scheme code"}
        </span>
      </div>
      {cands.length === 0 ? (
        <p className="text-sm text-muted-foreground">No candidates. Run matching, or enter the value in the Excel file.</p>
      ) : (
        <ul className="flex flex-col gap-2">
          {cands.map((c, i) => <CandidateItem key={c.id} c={c} best={i === 0} busy={busy} act={act} />)}
        </ul>
      )}
    </div>
  );
}

function CandidateItem({ c, best, busy, act }: { c: Candidate; best: boolean; busy: boolean; act: (p: string) => void }) {
  const d = c.details;
  return (
    <li className={cn("flex flex-col gap-2 rounded-lg border p-2 sm:flex-row sm:items-center sm:justify-between",
                      best ? "border-foreground/20" : "border-border")}>
      <div className="text-sm">
        <div><span className="tnum font-medium">{c.value}</span> · {c.label}</div>
        <div className="text-xs text-muted-foreground">
          {c.source} · match score {(c.score * 100).toFixed(0)}%
          {d.isin_growth ? ` · ISIN ${d.isin_growth}` : ""}
          {d.nav ? ` · NAV ₹${d.nav} on ${formatDate(String(d.nav_date))}` : ""}
          {d.underlying ? ` · NSE underlying: ${d.underlying}` : ""}
        </div>
      </div>
      <div className="flex gap-2">
        <Button size="sm" disabled={busy} onClick={() => act(`/mappings/candidates/${c.id}/confirm`)}>Confirm</Button>
        <Button size="sm" variant="ghost" disabled={busy} onClick={() => act(`/mappings/candidates/${c.id}/reject`)}>Reject</Button>
      </div>
    </li>
  );
}
