"use client";

import Link from "next/link";
import { useState } from "react";
import { AnalysisFooter, ErrorBox, Loading, Notice, PageHeader, Section } from "@/components/common";
import { Button } from "@/components/ui/button";
import { apiGet, apiPost, errorText, useApi, type AnalysisCard, type AnalysisHolding, type AnalysisPage, type Statement } from "@/lib/api";
import { formatDate, formatDateTime } from "@/lib/format";

const LABELS: Record<string, string> = {
  valuation_context: "Valuation context (vs. my portfolio and my peers only)", business_quality: "Business quality notes",
  key_risks: "Key risks", macro_sensitivity: "Macro sensitivity", what_would_change_this_view: "What would change this view",
  data_gaps: "Data gaps", cost_and_tracking: "Cost and tracking", concentration: "Concentration", sector_tilts: "Sector tilts",
  overlap: "Overlap", summary: "What the flags show",
};
type Kind = "stock" | "fund" | "portfolio";

export default function AnalysisPageView() {
  const { data, error, loading, reload } = useApi<AnalysisPage>("/analysis");
  const [busy, setBusy] = useState<string | null>(null);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [sent, setSent] = useState<{ title: string; body: unknown } | null>(null);

  async function run(kind: Kind, iid: number | null, card: AnalysisCard | null) {
    const refresh = !!card && !card.stale;
    const path = kind === "stock" ? `/analysis/${iid}` : kind === "fund" ? `/analysis/fund/${iid}` : "/analysis/portfolio";
    setBusy(`${kind}:${iid}`);
    setMsg(null);
    try {
      const r = await apiPost<{ cached: boolean; card: AnalysisCard }>(`${path}${refresh ? "?refresh=true" : ""}`);
      setMsg({ ok: true, text: r.cached ? "Inputs unchanged: showing the cached analysis (use Refresh to regenerate)." :
        r.card.status === "OK" ? "Generated and passed all guardrails." : "The output failed the guardrails; it is flagged and not shown." });
      reload();
    } catch (e) {
      setMsg({ ok: false, text: errorText(e) });
    } finally {
      setBusy(null);
    }
  }
  async function showSent(kind: Kind, iid: number | null, card: AnalysisCard | null, label: string) {
    try {
      const body = card ? await apiGet(`/analysis/sent/${card.id}`)
        : kind === "portfolio" ? await apiGet("/analysis/portfolio/preview") : await apiGet(`/analysis/${iid}/preview?kind=${kind}`);
      setSent({ title: card ? `Exactly what was sent for ${label} (#${card.id})` : `What would be sent for ${label} (nothing sent yet)`, body });
    } catch (e) {
      setMsg({ ok: false, text: errorText(e) });
    }
  }

  const cardProps = { busy, gated: !!data?.gate, run, showSent };
  return (
    <>
      <PageHeader title="AI analysis" subtitle="Context, risks and sensitivities grounded only in what you imported and entered, checked by guardrails before display." />
      {error && <ErrorBox message={error} />}
      {loading && !data && <Loading />}
      {data && (
        <div className="flex flex-col gap-4">
          {data.gate ? <Notice tone="warn">AI analysis is unavailable: {data.gate} <Link className="underline" href="/settings">Settings</Link></Notice> : (
            <Notice>
              Model {data.settings.model} (effort {data.settings.effort}) · refusal fallback {data.settings.refusal_fallback ? "on" : "off"} ·{" "}
              {data.usage.calls_this_month}/{data.usage.cap} calls this month · estimated cost {data.usage.estimated_cost_usd ? `$${data.usage.estimated_cost_usd}` : "N/A"}. {data.usage.pricing_note}
            </Notice>
          )}
          {msg && (msg.ok ? <Notice>{msg.text}</Notice> : <ErrorBox message={msg.text} />)}
          {sent && (
            <Section title={sent.title} aside={<button className="underline" onClick={() => setSent(null)}>Close</button>}>
              <pre className="max-h-[32rem] overflow-auto rounded-md bg-muted/40 p-3 text-xs whitespace-pre-wrap">{JSON.stringify(sent.body, null, 2)}</pre>
            </Section>
          )}
          <p className="text-xs text-muted-foreground">
            Sent: percentages, fundamentals and framework checks with sources, peer medians (peers chosen by you), recent headlines, macro values,
            sector tags, fund disclosures, and — only for holdings you opt in — your thesis and qualitative notes. Never sent: amounts, quantities,
            account details, emergency-fund data.
          </p>
          <Card kind="portfolio" h={{ instrument_id: null, symbol: null, name: "Portfolio", card: data.portfolio.card }} {...cardProps} />
          <h2 className="mt-2 text-sm font-medium text-muted-foreground">Mutual funds</h2>
          {data.funds.map((h) => <Card key={`f${h.instrument_id}`} kind="fund" h={h} {...cardProps} />)}
          <h2 className="mt-2 text-sm font-medium text-muted-foreground">Direct stocks</h2>
          {data.holdings.map((h) => <Card key={`s${h.instrument_id}`} kind="stock" h={h} {...cardProps} />)}
          <AnalysisFooter />
        </div>
      )}
    </>
  );
}

type CardH = AnalysisHolding | { instrument_id: null; symbol: null; name: string; card: AnalysisCard | null };

function Card({ kind, h, busy, gated, run, showSent }: {
  kind: Kind; h: CardH; busy: string | null; gated: boolean;
  run: (kind: Kind, iid: number | null, card: AnalysisCard | null) => void;
  showSent: (kind: Kind, iid: number | null, card: AnalysisCard | null, label: string) => void;
}) {
  const label = h.symbol ?? h.name;
  return (
    <Section title={kind === "portfolio" ? "Portfolio summary (what the flags show)" : kind === "fund" ? h.name : `${h.symbol} — ${h.name}`}
             aside={<div className="flex gap-2">
               <Button size="sm" variant="ghost" onClick={() => showSent(kind, h.instrument_id, h.card, label)}>
                 {h.card ? "View exactly what was sent" : "Preview what would be sent"}
               </Button>
               <Button size="sm" variant="outline" disabled={busy !== null || gated} onClick={() => run(kind, h.instrument_id, h.card)}>
                 {busy === `${kind}:${h.instrument_id}` ? "Working…" : !h.card ? "Generate" : h.card.stale ? "Update (inputs changed)" : "Refresh"}
               </Button>
             </div>}>
      <CardBody card={h.card} />
    </Section>
  );
}

function Cites({ ids }: { ids: string[] }) {
  return <span className="ml-1 text-[11px] text-muted-foreground">[{ids.join(", ")}]</span>;
}

function CardBody({ card }: { card: AnalysisCard | null }) {
  if (!card) return <p className="text-sm text-muted-foreground">No analysis yet.</p>;
  const meta = (
    <p className="mb-3 text-xs text-muted-foreground">
      Answered by <b className="text-foreground">{card.model}</b>
      {card.fallback_used && <> (fallback — you requested {card.requested_model})</>} · generated {formatDateTime(card.created_at)} ·
      data as of {card.data_as_of ? formatDate(card.data_as_of) : "—"}{card.attempts > 1 ? ` · ${card.attempts} attempts` : ""}
      {card.stale ? " · inputs have changed since" : ""}
    </p>
  );
  if (card.status !== "OK" || !card.analysis) {
    return <>{meta}<ErrorBox message={`Flagged: the output failed the guardrails and is not shown. ${card.errors.slice(0, 6).join(" · ")}`} /></>;
  }
  const a = card.analysis;
  const sections = Object.keys(a).filter((k) => k !== "scenarios");
  return (
    <div className="flex flex-col gap-3 text-sm">
      {meta}
      {a.scenarios && a.scenarios.length > 0 && (
        <div>
          <div className="mb-1 text-xs font-medium text-muted-foreground">Scenarios (direction of pressure, not outcomes)</div>
          <ul className="list-disc space-y-1 pl-5">{a.scenarios.map((s, i) => <li key={i}>{s.sentence}<Cites ids={s.citations} /></li>)}</ul>
        </div>
      )}
      <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
        {sections.map((k) => {
          const items = a[k] as Statement[];
          return items.length ? (
            <div key={k}>
              <div className="mb-1 text-xs font-medium text-muted-foreground">{LABELS[k] ?? k}</div>
              <ul className="list-disc space-y-1 pl-5">{items.map((x, i) => <li key={i}>{x.text}<Cites ids={x.citations} /></li>)}</ul>
            </div>
          ) : null;
        })}
      </div>
      <p className="text-[11px] text-muted-foreground">Bracketed ids cite the input values each statement relies on (see “View exactly what was sent”).</p>
    </div>
  );
}
