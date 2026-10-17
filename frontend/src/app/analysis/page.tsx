"use client";

import Link from "next/link";
import { useState } from "react";
import { AnalysisFooter, ErrorBox, Loading, Notice, PageHeader, Section } from "@/components/common";
import { Button } from "@/components/ui/button";
import { apiGet, apiPost, errorText, useApi, type AnalysisCard, type AnalysisPage, type Statement } from "@/lib/api";
import { formatDate, formatDateTime } from "@/lib/format";

const SECTIONS: [keyof NonNullable<AnalysisCard["analysis"]>, string][] = [
  ["valuation_context", "Valuation context (vs. my portfolio only)"], ["business_quality", "Business quality notes"],
  ["key_risks", "Key risks"], ["macro_sensitivity", "Macro sensitivity"],
  ["what_would_change_this_view", "What would change this view"], ["data_gaps", "Data gaps"],
];

export default function AnalysisPageView() {
  const { data, error, loading, reload } = useApi<AnalysisPage>("/analysis");
  const [busy, setBusy] = useState<number | null>(null);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [sent, setSent] = useState<{ title: string; body: unknown } | null>(null);

  async function run(iid: number, refresh: boolean) {
    setBusy(iid);
    setMsg(null);
    try {
      const r = await apiPost<{ cached: boolean; card: AnalysisCard }>(`/analysis/${iid}${refresh ? "?refresh=true" : ""}`);
      setMsg({ ok: true, text: r.cached ? "Inputs unchanged: showing the cached analysis (use Refresh to regenerate)." :
        r.card.status === "OK" ? "Analysis generated and passed all guardrails." : "The model's output failed the guardrails; it is flagged and not shown as analysis." });
      reload();
    } catch (e) {
      setMsg({ ok: false, text: errorText(e) });
    } finally {
      setBusy(null);
    }
  }
  async function showSent(iid: number, card: AnalysisCard | null, symbol: string) {
    try {
      const body = card ? await apiGet(`/analysis/${iid}/sent/${card.id}`) : await apiGet(`/analysis/${iid}/preview`);
      setSent({ title: card ? `Exactly what was sent for ${symbol} (analysis #${card.id})` : `What would be sent for ${symbol} (nothing sent yet)`, body });
    } catch (e) {
      setMsg({ ok: false, text: errorText(e) });
    }
  }

  return (
    <>
      <PageHeader title="AI scenario analysis" subtitle="Context, risks and scenario sensitivities per stock, grounded only in your stored data and checked by guardrails before display." />
      {error && <ErrorBox message={error} />}
      {loading && !data && <Loading />}
      {data && (
        <div className="flex flex-col gap-4">
          {data.gate ? <Notice tone="warn">AI analysis is unavailable: {data.gate} <Link className="underline" href="/settings">Settings</Link></Notice> : (
            <Notice>Model {data.settings.model} (effort {data.settings.effort}) · {data.usage.calls_this_month}/{data.usage.cap} calls this month · estimated cost ${data.usage.estimated_cost_usd}. {data.usage.pricing_note}</Notice>
          )}
          {msg && (msg.ok ? <Notice>{msg.text}</Notice> : <ErrorBox message={msg.text} />)}
          {sent && (
            <Section title={sent.title} aside={<button className="underline" onClick={() => setSent(null)}>Close</button>}>
              <pre className="max-h-[32rem] overflow-auto rounded-md bg-muted/40 p-3 text-xs whitespace-pre-wrap">{JSON.stringify(sent.body, null, 2)}</pre>
            </Section>
          )}
          <p className="text-xs text-muted-foreground">{data.funds_note} Sent: percentages, fundamentals with sources, recent headlines, macro values, sector tags and (only if you opt in) your thesis. Never sent: amounts, quantities, platform or account details.</p>
          {data.holdings.map((h) => (
            <Section key={h.instrument_id} title={`${h.symbol} — ${h.name}`}
                     aside={<div className="flex gap-2">
                       <Button size="sm" variant="ghost" onClick={() => showSent(h.instrument_id, h.card, h.symbol)}>View exactly what was sent</Button>
                       <Button size="sm" variant="outline" disabled={busy !== null || !!data.gate} onClick={() => run(h.instrument_id, !!h.card && !h.card.stale)}>
                         {busy === h.instrument_id ? "Working…" : !h.card ? "Generate" : h.card.stale ? "Update (inputs changed)" : "Refresh"}
                       </Button>
                     </div>}>
              <CardBody card={h.card} />
            </Section>
          ))}
          <AnalysisFooter />
        </div>
      )}
    </>
  );
}

function Cites({ ids }: { ids: string[] }) {
  return <span className="ml-1 text-[11px] text-muted-foreground">[{ids.join(", ")}]</span>;
}

function CardBody({ card }: { card: AnalysisCard | null }) {
  if (!card) return <p className="text-sm text-muted-foreground">No analysis yet.</p>;
  const meta = (
    <p className="mb-3 text-xs text-muted-foreground">
      Model {card.model} · generated {formatDateTime(card.created_at)} · data as of {card.data_as_of ? formatDate(card.data_as_of) : "—"}
      {card.attempts > 1 ? ` · ${card.attempts} attempts` : ""}{card.stale ? " · inputs have changed since (shown result is from older inputs)" : ""}
    </p>
  );
  if (card.status !== "OK" || !card.analysis) {
    return (
      <>
        {meta}
        <ErrorBox message={`Flagged: the output failed the guardrails and is not shown. ${card.errors.slice(0, 6).join(" · ")}`} />
      </>
    );
  }
  const a = card.analysis;
  return (
    <div className="flex flex-col gap-3 text-sm">
      {meta}
      <div>
        <div className="mb-1 text-xs font-medium text-muted-foreground">Scenarios (direction of pressure, not outcomes)</div>
        <ul className="list-disc space-y-1 pl-5">
          {a.scenarios.map((s, i) => <li key={i}>{s.sentence}<Cites ids={s.citations} /></li>)}
        </ul>
      </div>
      <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
        {SECTIONS.map(([k, label]) => {
          const items = a[k] as Statement[];
          return items.length ? (
            <div key={k}>
              <div className="mb-1 text-xs font-medium text-muted-foreground">{label}</div>
              <ul className="list-disc space-y-1 pl-5">{items.map((x, i) => <li key={i}>{x.text}<Cites ids={x.citations} /></li>)}</ul>
            </div>
          ) : null;
        })}
      </div>
      <p className="text-[11px] text-muted-foreground">Bracketed ids cite the input values each statement relies on (see “View exactly what was sent”).</p>
    </div>
  );
}
