"use client";

import { useState } from "react";
import { AnalysisFooter, ErrorBox, Loading, Notice, PageHeader, Section } from "@/components/common";
import { Field } from "@/components/form";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { apiDelete, apiPost, apiPut, errorText, useApi, type MacroPage, type MacroRow } from "@/lib/api";
import { formatDate, formatDateTime, formatPct } from "@/lib/format";
import { cn } from "@/lib/utils";

export default function MacroPageView() {
  const { data, error, loading, reload } = useApi<MacroPage>("/macro");
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [editing, setEditing] = useState<MacroRow | null>(null);

  async function refresh() {
    try {
      const r = await apiPost<Record<string, string>>("/macro/refresh");
      setMsg({ ok: true, text: Object.entries(r).map(([k, v]) => `${k}: ${v}`).join(" · ") });
      reload();
    } catch (e) {
      setMsg({ ok: false, text: errorText(e) });
    }
  }
  async function toggleTag(sector: string, tags: string[], tag: string) {
    const next = tags.includes(tag) ? tags.filter((t) => t !== tag) : [...tags, tag];
    try {
      await apiPut(`/sensitivities/${encodeURIComponent(sector)}`, { tags: next });
      reload();
    } catch (e) {
      setMsg({ ok: false, text: errorText(e) });
    }
  }

  return (
    <>
      <PageHeader title="Macro & scenarios" subtitle="Context data with sources, and which parts of your portfolio carry each sensitivity tag."
                  actions={<Button variant="outline" onClick={refresh}>Refresh automated values</Button>} />
      {msg && (msg.ok ? <Notice>{msg.text}</Notice> : <ErrorBox message={msg.text} />)}
      {error && <ErrorBox message={error} />}
      {loading && !data && <Loading />}
      {editing && <ManualForm row={editing} onDone={() => { setEditing(null); reload(); }} />}
      {data && (
        <div className="mt-4 flex flex-col gap-4">
          <Section title="Macro snapshot" aside="Automated where a reliable feed exists; otherwise entered by you">
            <table className="tnum w-full text-sm">
              <tbody>
                {data.snapshot.map((m) => (
                  <tr key={m.key} className="border-b border-border align-top last:border-0">
                    <td className="py-2 pr-2">{m.label}<div className="text-xs text-muted-foreground">{m.unit}</div></td>
                    <td className={cn("py-2 pr-2 text-right", m.value ? "font-medium" : "text-xs text-muted-foreground")}>{m.display}</td>
                    <td className="py-2 text-xs text-muted-foreground">
                      {m.source ?? "—"}{m.as_of ? ` · as of ${formatDate(m.as_of)}` : ""}{m.fetched_at && !m.manual ? ` · fetched ${formatDateTime(m.fetched_at)}` : ""}
                      {m.note && <div>{m.note}</div>}
                    </td>
                    <td className="py-2 text-right">
                      {m.manual && <Button size="sm" variant="ghost" onClick={() => setEditing(m)}>{m.value ? "Edit" : "Enter"}</Button>}
                      {m.manual && m.value && <Button size="sm" variant="ghost" onClick={async () => { await apiDelete(`/macro/${m.key}`); reload(); }}>Clear</Button>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="mt-2 text-xs text-muted-foreground">Values are never filled in from memory: no source means N/A.</p>
          </Section>

          <Section title="Exposure by sensitivity tag" aside="Not a forecast">
            <p className="mb-3 text-xs text-muted-foreground">{data.basis}</p>
            <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
              {data.scenarios.map((s) => (
                <div key={s.scenario} className="rounded-lg border border-border p-3">
                  <div className="mb-1 text-sm font-medium">{s.label}</div>
                  {s.tags.map((t) => (
                    <div key={t.tag} className="mb-2 last:mb-0">
                      <div className="flex justify-between text-xs"><span className="text-muted-foreground">{t.tag}</span><span className="tnum font-medium">{t.weight_text}</span></div>
                      <div className="text-xs text-muted-foreground">
                        {t.sectors.length ? t.sectors.map((x) => `${x.sector} ${formatPct(x.pct)}`).join("; ") : "No held sector carries this tag."}
                        {t.holdings.length > 0 && <div>Direct holdings: {t.holdings.join(", ")}</div>}
                      </div>
                    </div>
                  ))}
                </div>
              ))}
            </div>
          </Section>

          <Section title="Sector sensitivity tags" aside="Editable">
            <Notice tone="warn">{data.starter_label}</Notice>
            <div className="mt-3 overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="text-xs text-muted-foreground">
                  <tr><th className="py-1 text-left font-normal">Sector (% of portfolio)</th>
                    {data.tags.map((t) => <th key={t} className="px-1 py-1 text-center font-normal">{t}</th>)}</tr>
                </thead>
                <tbody>
                  {data.table.map((r) => (
                    <tr key={r.sector} className="border-t border-border">
                      <td className="py-1.5 pr-2">
                        {r.sector} <span className="tnum text-xs text-muted-foreground">{formatPct(r.held_pct)}</span>
                        <div className="text-[11px] text-muted-foreground">{r.origin === "USER" ? "edited by you" : r.origin === "STARTER" ? "starter — review" : "no tags"}</div>
                      </td>
                      {data.tags.map((t) => (
                        <td key={t} className="px-1 py-1.5 text-center">
                          <input type="checkbox" aria-label={`${r.sector}: ${t}`} checked={r.tags.includes(t)} onChange={() => toggleTag(r.sector, r.tags, t)} />
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Section>
          <AnalysisFooter />
        </div>
      )}
    </>
  );
}

function ManualForm({ row, onDone }: { row: MacroRow; onDone: () => void }) {
  const [value, setValue] = useState(row.value ?? "");
  const [source, setSource] = useState(row.source?.replace(/^manual: /, "") ?? "");
  const [asOf, setAsOf] = useState(row.as_of ?? "");
  const [err, setErr] = useState<string | null>(null);
  async function save(e: React.FormEvent) {
    e.preventDefault();
    try {
      await apiPut(`/macro/${row.key}`, { value, source_note: source, as_of: asOf });
      onDone();
    } catch (x) {
      setErr(errorText(x));
    }
  }
  return (
    <Section title={`Enter ${row.label}`}>
      <form onSubmit={save} className="flex flex-col gap-3">
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          <Field label={`Value (${row.unit})`}><Input required value={value} onChange={(e) => setValue(e.target.value)} /></Field>
          <Field label="Source note (required)" hint="e.g. RBI MPC statement 1 Oct 2026; MoSPI CPI release"><Input required value={source} onChange={(e) => setSource(e.target.value)} /></Field>
          <Field label="As of (required)"><Input type="date" required value={asOf} onChange={(e) => setAsOf(e.target.value)} /></Field>
        </div>
        {err && <ErrorBox message={err} />}
        <div className="flex gap-2"><Button type="submit">Save</Button><Button type="button" variant="ghost" onClick={onDone}>Cancel</Button></div>
      </form>
    </Section>
  );
}
