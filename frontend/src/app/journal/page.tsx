"use client";

import { useState } from "react";
import { ErrorBox, Loading, Notice, PageHeader, Section } from "@/components/common";
import { Field } from "@/components/form";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { apiGet, apiPost, apiPut, errorText, useApi, type JournalPage, type ThesisEntry } from "@/lib/api";
import { formatDate, formatDateTime } from "@/lib/format";

type Holding = JournalPage["holdings"][number];

export default function JournalPageView() {
  const { data, error, loading, reload } = useApi<JournalPage>("/journal");
  const [open, setOpen] = useState<number | null>(null);
  return (
    <>
      <PageHeader title="Thesis journal" subtitle={data?.note} />
      {error && <ErrorBox message={error} />}
      {loading && !data && <Loading />}
      {data && (
        <div className="flex flex-col gap-4">
          {data.review_due.length > 0 && (
            <Section title={`Review due (${data.review_due.length})`}>
              <ul className="text-sm">
                {data.review_due.map((r) => (
                  <li key={r.id} className="flex justify-between border-b border-border py-1.5 last:border-0">
                    <span>{r.name} — version {r.version}</span><span className="text-xs text-status-high">▲ review date {formatDate(r.review_date)}</span>
                  </li>
                ))}
              </ul>
            </Section>
          )}
          {data.holdings.map((h) => (
            <Section key={h.instrument_id} title={h.symbol ?? h.name}
                     aside={<Button size="sm" variant="ghost" onClick={() => setOpen(open === h.instrument_id ? null : h.instrument_id)}>
                       {open === h.instrument_id ? "Close" : h.latest ? "New version / history" : "Write thesis"}
                     </Button>}>
              {h.latest ? <Entry e={h.latest} /> : <p className="text-sm text-muted-foreground">No thesis yet.</p>}
              {h.asset_type === "STOCK" && <label className="mt-2 flex items-center gap-2 text-xs text-muted-foreground">
                <input type="checkbox" checked={h.send_to_llm}
                       onChange={async (ev) => { await apiPut(`/journal/${h.instrument_id}/optin`, { send_to_llm: ev.target.checked }); reload(); }} />
                Include my latest thesis in AI analysis for this holding (off by default; otherwise journal text never leaves this machine)
              </label>}
              {open === h.instrument_id && <Editor h={h} onSaved={reload} />}
            </Section>
          ))}
        </div>
      )}
    </>
  );
}

function Entry({ e }: { e: ThesisEntry }) {
  return (
    <div className="flex flex-col gap-1 text-sm">
      <p><span className="text-xs text-muted-foreground">Why I hold it: </span>{e.why}</p>
      <p><span className="text-xs text-muted-foreground">What would change my view: </span>{e.change_view}</p>
      <p className="text-xs text-muted-foreground">
        Horizon {e.horizon} · review {e.review_date ? formatDate(e.review_date) : "—"}{e.review_due ? " (due)" : ""} · version {e.version}, {formatDateTime(e.created_at)}
        {e.linked_txn_ids.length ? ` · linked transactions #${e.linked_txn_ids.join(", #")}` : ""}
        {e.linked_change_ids.length ? ` · linked changes #${e.linked_change_ids.join(", #")}` : ""}
      </p>
    </div>
  );
}

function Editor({ h, onSaved }: { h: Holding; onSaved: () => void }) {
  const [why, setWhy] = useState(h.latest?.why ?? "");
  const [change, setChange] = useState(h.latest?.change_view ?? "");
  const [horizon, setHorizon] = useState(h.latest?.horizon ?? "");
  const [review, setReview] = useState("");
  const [txns, setTxns] = useState<number[]>([]);
  const [hist, setHist] = useState<ThesisEntry[] | null>(null);
  const [err, setErr] = useState<string | null>(null);

  async function save(e: React.FormEvent) {
    e.preventDefault();
    try {
      await apiPost(`/journal/${h.instrument_id}`, { why, change_view: change, horizon, review_date: review || null, linked_txn_ids: txns });
      setErr(null);
      onSaved();
    } catch (x) {
      setErr(errorText(x));
    }
  }
  return (
    <div className="mt-3 flex flex-col gap-3 border-t border-border pt-3">
      <form onSubmit={save} className="flex flex-col gap-3">
        <Field label="Why I hold it"><textarea required className="min-h-16 rounded-lg border border-input bg-input/30 p-2 text-sm" value={why} onChange={(e) => setWhy(e.target.value)} /></Field>
        <Field label="What would change my view"><textarea required className="min-h-16 rounded-lg border border-input bg-input/30 p-2 text-sm" value={change} onChange={(e) => setChange(e.target.value)} /></Field>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <Field label="Intended horizon"><Input required placeholder="e.g. 5+ years" value={horizon} onChange={(e) => setHorizon(e.target.value)} /></Field>
          <Field label="Review date"><Input type="date" value={review} onChange={(e) => setReview(e.target.value)} /></Field>
        </div>
        {h.transactions.length > 0 && (
          <div className="flex flex-wrap gap-2 text-xs">
            <span className="text-muted-foreground">Link transactions:</span>
            {h.transactions.map((t) => (
              <label key={t.id} className="flex items-center gap-1">
                <input type="checkbox" checked={txns.includes(t.id)} onChange={() => setTxns(txns.includes(t.id) ? txns.filter((x) => x !== t.id) : [...txns, t.id])} />
                #{t.id} {t.type} {formatDate(t.date)}
              </label>
            ))}
          </div>
        )}
        {err && <ErrorBox message={err} />}
        <div className="flex gap-2">
          <Button type="submit">Save as version {(h.versions || 0) + 1}</Button>
          <Button type="button" variant="ghost" onClick={async () => setHist(await apiGet(`/journal/${h.instrument_id}/history`))}>Show history</Button>
        </div>
      </form>
      {hist && (
        <div className="flex flex-col gap-3">
          {hist.length === 0 && <Notice>No earlier versions.</Notice>}
          {hist.map((e) => <div key={e.id} className="rounded-md border border-border p-2"><Entry e={e} /></div>)}
        </div>
      )}
    </div>
  );
}
