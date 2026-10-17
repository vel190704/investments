"use client";

import { useState } from "react";
import { DriftSection } from "@/components/drift";
import { ErrorBox, Loading, Notice, PageHeader, Section } from "@/components/common";
import { Field } from "@/components/form";
import { Input } from "@/components/ui/input";
import { useApi, type Compare, type Drift } from "@/lib/api";
import { formatDate, formatDateTime, formatINR, formatPct, signClass } from "@/lib/format";

type Strategy = {
  since: string; note: string | null;
  stated: { drift: Drift; theses: { name: string; version: number; why: string; change_view: string; horizon: string; created_at: string }[] };
  actual: { comparison_from_snapshot: string | null; compare: Compare | null;
            transactions: { id: number; date: string; type: string; name: string; amount_paise: number; source: string }[];
            changes: { id: number; occurred_at: string; kind: string; summary: string }[] };
};

export default function StrategyPage() {
  const [since, setSince] = useState(() => new Date(Date.now() - 90 * 864e5).toISOString().slice(0, 10));
  const { data, error, loading } = useApi<Strategy>(`/strategy?since=${since}`);
  return (
    <>
      <PageHeader title="Strategy vs actual" subtitle="What you said (targets, theses) next to what happened since a date. Facts only; no judgement." />
      <Section title="Since">
        <Field label="Compare from"><Input type="date" value={since} onChange={(e) => e.target.value && setSince(e.target.value)} /></Field>
      </Section>
      {error && <ErrorBox message={error} />}
      {loading && !data && <Loading />}
      {data && (
        <div className="mt-4 grid grid-cols-1 gap-4 xl:grid-cols-2">
          <div className="flex flex-col gap-4">
            <Section title="Stated: target allocation now"><DriftSection drift={data.stated.drift} /></Section>
            <Section title="Stated: latest theses">
              {!data.stated.theses.length ? <p className="text-sm text-muted-foreground">No theses written yet.</p> : (
                <ul className="flex flex-col gap-2 text-sm">
                  {data.stated.theses.map((t) => (
                    <li key={t.name}><span className="font-medium">{t.name}</span> (v{t.version}, {formatDate(t.created_at)}): {t.why}
                      <div className="text-xs text-muted-foreground">Would change view if: {t.change_view} · horizon {t.horizon}</div></li>
                  ))}
                </ul>
              )}
            </Section>
          </div>
          <div className="flex flex-col gap-4">
            <Section title="Actual: allocation since">
              {data.note && <Notice>{data.note}</Notice>}
              {data.actual.compare && (
                <table className="tnum w-full text-sm">
                  <thead className="text-xs text-muted-foreground"><tr><th className="py-1 text-left font-normal">Asset class</th><th className="py-1 text-right font-normal">{formatDate(data.actual.comparison_from_snapshot)} → today</th><th className="py-1 text-right font-normal">Value change</th></tr></thead>
                  <tbody>
                    {data.actual.compare.asset_classes.map((c) => (
                      <tr key={c.asset_class} className="border-t border-border">
                        <td className="py-1.5">{c.asset_class}</td>
                        <td className="py-1.5 text-right">{formatPct(c.weight_a)} → {formatPct(c.weight_b)}</td>
                        <td className={`py-1.5 text-right ${signClass(c.value_change_paise)}`}>{formatINR(c.value_change_paise, { signed: true })}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </Section>
            <Section title={`Actual: transactions since (${data.actual.transactions.length})`}>
              <ul className="tnum text-sm">
                {data.actual.transactions.map((t) => (
                  <li key={t.id} className="flex justify-between border-b border-border py-1 last:border-0">
                    <span>{formatDate(t.date)} {t.type} {t.name} <span className="text-xs text-muted-foreground">({t.source})</span></span><span>{formatINR(t.amount_paise)}</span>
                  </li>
                ))}
              </ul>
            </Section>
            <Section title={`Actual: change log since (${data.actual.changes.length})`}>
              <ul className="text-sm">
                {data.actual.changes.map((c) => <li key={c.id} className="border-b border-border py-1 last:border-0"><span className="text-xs text-muted-foreground">{formatDateTime(c.occurred_at)} · {c.kind}</span><div>{c.summary}</div></li>)}
              </ul>
            </Section>
          </div>
        </div>
      )}
    </>
  );
}
