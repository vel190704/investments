"use client";

import { useState } from "react";
import { ErrorBox, Loading, Notice, PageHeader, Section } from "@/components/common";
import { Button } from "@/components/ui/button";
import { apiGet, apiPost, errorText, useApi, type Candidate, type MappingRow, type Mappings } from "@/lib/api";
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
      {data && data.pending > 0 && <ExactMatches onDone={reload} />}
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

type ExactPlan = {
  apply: { candidate_id: number; instrument_id: number; name: string; kind: string; value: string; label: string; score: number; why: string }[];
  manual: { instrument_id: number; name: string; kind: string; reason: string }[];
  rules: { high_score: number; min_margin: number };
};

/** Lists the proposed exact / high-confidence matches first; confirms only those, leaving the rest for review. */
function ExactMatches({ onDone }: { onDone: () => Promise<void> | void }) {
  const [p, setP] = useState<ExactPlan | null>(null);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  async function show() {
    setMsg(null);
    try { setP(await apiGet<ExactPlan>("/mappings/exact-matches")); } catch (e) { setMsg({ ok: false, text: errorText(e) }); }
  }
  async function confirm() {
    if (!p) return;
    setBusy(true);
    try {
      const r = await apiPost<{ confirmed: number[]; skipped: { reason: string }[] }>("/mappings/confirm-exact",
        { candidate_ids: p.apply.map((a) => a.candidate_id) });
      setMsg({ ok: true, text: `Confirmed ${r.confirmed.length}.` + (r.skipped.length ? ` Skipped ${r.skipped.length} that are no longer exact matches.` : "") });
      setP(null);
      await onDone();
    } catch (e) {
      setMsg({ ok: false, text: errorText(e) });
    } finally {
      setBusy(false);
    }
  }
  return (
    <Section title="Confirm all exact matches" aside="nothing changes until you confirm">
      {!p ? (
        <Button variant="outline" onClick={show}>Show exact matches…</Button>
      ) : (
        <div className="flex flex-col gap-3 text-sm">
          <p className="text-xs text-muted-foreground">
            Exact = an ISIN from an exact NSE symbol match, or a scheme code scoring at least {p.rules.high_score.toFixed(2)} and
            ahead of the next candidate by {p.rules.min_margin.toFixed(2)} or more. Everything else stays below for you to review.
          </p>
          {p.apply.length === 0 ? <p>No exact matches to confirm.</p> : (
            <ul className="flex flex-col">
              {p.apply.map((a) => (
                <li key={a.candidate_id} className="border-b border-border py-1 last:border-0">
                  <b>{a.name}</b> → {a.kind === "ISIN" ? "ISIN" : "scheme"} <code>{a.value}</code> {a.label !== a.value && <span className="text-muted-foreground">({a.label})</span>}
                  <span className="text-xs text-muted-foreground"> · {a.why}</span>
                </li>
              ))}
            </ul>
          )}
          {p.manual.length > 0 && (
            <div className="text-xs text-muted-foreground">
              Left for manual review: {p.manual.map((m) => `${m.name} (${m.reason})`).join("; ")}.
            </div>
          )}
          <div className="flex gap-2">
            <Button disabled={busy || p.apply.length === 0} onClick={confirm}>Confirm these {p.apply.length}</Button>
            <Button variant="ghost" onClick={() => setP(null)}>Cancel</Button>
          </div>
        </div>
      )}
      {msg && (msg.ok ? <Notice>{msg.text}</Notice> : <ErrorBox message={msg.text} />)}
    </Section>
  );
}
