"use client";

import Link from "next/link";
import { useState } from "react";
import { ErrorBox, LevelBadge, Loading, Notice, PageHeader, Section } from "@/components/common";
import { Field, Select } from "@/components/form";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  apiDelete, errorText, useApi, type DisclosureItem, type InstrumentRef, type Lookthrough, type Overlap,
} from "@/lib/api";
import { formatDate, formatDateTime, formatINR, formatPct } from "@/lib/format";
import { cn } from "@/lib/utils";

export default function OverlapPage() {
  const look = useApi<Lookthrough>("/lookthrough");
  const ov = useApi<Overlap>("/overlap");
  const disc = useApi<{ disclosures: DisclosureItem[]; parsers: { key: string; label: string }[] }>("/disclosures");
  const insts = useApi<InstrumentRef[]>("/instruments");
  const reloadAll = () => { look.reload(); ov.reload(); disc.reload(); };

  async function remove(d: DisclosureItem) {
    if (!window.confirm(`Delete ${d.label} for ${d.fund}?`)) return;
    await apiDelete(`/disclosures/${d.id}`);
    reloadAll();
  }

  const funds = (insts.data ?? []).filter((i) => i.asset_type === "MF");
  return (
    <>
      <PageHeader title="Fund look-through" subtitle="What your funds hold, combined with your direct stocks. Companies are matched by ISIN only." />
      <div className="flex flex-col gap-4">
        <UploadForm funds={funds} parsers={disc.data?.parsers ?? []} onDone={reloadAll} />

        <Section title="Uploaded disclosures" aside="Earlier months are kept; the newest per fund is used">
          {!disc.data?.disclosures.length ? <p className="text-sm text-muted-foreground">Nothing uploaded yet.</p> : (
            <table className="tnum w-full text-sm">
              <tbody>
                {disc.data.disclosures.map((d) => (
                  <tr key={d.id} className="border-b border-border align-top last:border-0">
                    <td className="py-1.5 pr-2">
                      <div className="font-medium">{d.fund}</div>
                      <div className="text-xs text-muted-foreground">{d.label} · {d.parser} · {d.rows} rows · equity {formatPct(d.equity_weight)} of NAV</div>
                      <div className="text-xs text-muted-foreground">{d.source_file} · uploaded {formatDateTime(d.uploaded_at)}</div>
                    </td>
                    <td className="py-1.5 pr-2 text-xs whitespace-nowrap">
                      {d.in_use ? <span className="rounded border border-border px-1.5 py-0.5">in use</span> : "older"}
                      {d.stale && <span className="ml-1 rounded border border-status-moderate/50 px-1.5 py-0.5 text-status-moderate">▲ stale</span>}
                    </td>
                    <td className="py-1.5 text-right"><Button size="sm" variant="ghost" onClick={() => remove(d)}>Delete</Button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Section>

        {look.error && <ErrorBox message={look.error} />}
        {look.loading && !look.data && <Loading />}
        {look.data && <LookthroughView l={look.data} />}
        {ov.data && <OverlapView o={ov.data} />}
      </div>
    </>
  );
}

function UploadForm({ funds, parsers, onDone }: {
  funds: InstrumentRef[]; parsers: { key: string; label: string }[]; onDone: () => void;
}) {
  const [fund, setFund] = useState("");
  const [kind, setKind] = useState("AMC_DISCLOSURE");
  const [amc, setAmc] = useState("");
  const [asOf, setAsOf] = useState("");
  const [indexName, setIndexName] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!file || !fund) return;
    setBusy(true);
    setMsg(null);
    const q = new URLSearchParams({ instrument_id: fund, kind });
    if (amc) q.set("amc", amc);
    if (asOf) q.set("as_of", asOf);
    if (indexName) q.set("index_name", indexName);
    const fd = new FormData();
    fd.append("file", file);
    try {
      const res = await fetch(`/api/disclosures?${q}`, { method: "POST", body: fd });
      const body = await res.json();
      if (!res.ok) throw new Error(typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail));
      setMsg({ ok: true, text: `Stored ${body.rows} rows for ${body.fund} as of ${formatDate(body.as_of)} (${body.parser}${body.sheet ? `, sheet ${body.sheet}` : ""}); equity ${formatPct(body.equity_weight)} of NAV.` +
        (body.replaced_same_month ? " Replaced the earlier upload for that month." : "") +
        (body.warnings.length ? ` Warnings: ${body.warnings.join(" ")}` : "") });
      onDone();
    } catch (err) {
      setMsg({ ok: false, text: errorText(err) });
    } finally {
      setBusy(false);
    }
  }

  return (
    <Section title="Upload a fund's holdings" aside={<Link className="underline" href="/fundamentals">Tracking difference lives on Fundamentals</Link>}>
      <form onSubmit={submit} className="flex flex-col gap-3">
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <Field label="Fund">
            <Select required value={fund} onChange={(e) => setFund(e.target.value)}>
              <option value="">Choose…</option>
              {funds.map((f) => <option key={f.instrument_id} value={f.instrument_id}>{f.name}</option>)}
            </Select>
          </Field>
          <Field label="File type">
            <Select value={kind} onChange={(e) => setKind(e.target.value)}>
              <option value="AMC_DISCLOSURE">AMC monthly portfolio disclosure (.xlsx)</option>
              <option value="INDEX_WEIGHTS">Index constituent weights (.csv) — approximation</option>
            </Select>
          </Field>
          {kind === "AMC_DISCLOSURE" ? (
            <Field label="AMC layout">
              <Select value={amc} onChange={(e) => setAmc(e.target.value)}>
                <option value="">Detect from file</option>
                {parsers.map((p) => <option key={p.key} value={p.key}>{p.label}</option>)}
              </Select>
            </Field>
          ) : (
            <Field label="Index name"><Input required value={indexName} placeholder="Nifty 50" onChange={(e) => setIndexName(e.target.value)} /></Field>
          )}
          <Field label={kind === "INDEX_WEIGHTS" ? "Weights as of (required)" : "As of (optional — read from file)"}>
            <Input type="date" required={kind === "INDEX_WEIGHTS"} value={asOf} onChange={(e) => setAsOf(e.target.value)} />
          </Field>
        </div>
        <input type="file" accept=".xlsx,.csv" aria-label="Disclosure file" onChange={(e) => setFile(e.target.files?.[0] ?? null)}
               className="text-sm file:mr-3 file:rounded-md file:border file:border-border file:bg-muted file:px-3 file:py-1.5 file:text-sm file:text-foreground" />
        <p className="text-xs text-muted-foreground">
          Index-weights CSV columns: <code>ISIN, Company Name, Weightage %</code> (optional <code>Industry</code>). Weights are an
          approximation of an index fund&apos;s holdings and are labelled as such.
        </p>
        {msg && (msg.ok ? <Notice>{msg.text}</Notice> : <ErrorBox message={msg.text} />)}
        <div><Button type="submit" disabled={busy || !file || !fund}>{busy ? "Parsing…" : "Upload"}</Button></div>
      </form>
    </Section>
  );
}

function LookthroughView({ l }: { l: Lookthrough }) {
  const fundCols = l.coverage.map((c) => c.name);
  const [showAll, setShowAll] = useState(false);
  const rows = showAll ? l.companies : l.companies.slice(0, 20);
  return (
    <>
      {l.stale.map((s) => <Notice key={s.fund} tone="warn">▲ {s.warning}</Notice>)}
      {(l.not_looked_through.length > 0 || l.unmatched_direct.length > 0) && (
        <Notice>
          {l.not_looked_through.length > 0 && <>Not looked through (no disclosure): {l.not_looked_through.map((f) => f.name).join("; ")}. </>}
          {l.unmatched_direct.length > 0 && <>Not combined: {l.unmatched_direct.map((u) => `${u.name} (${u.reason})`).join("; ")}. Confirm ISINs on <Link className="underline" href="/mappings">Mappings</Link>.</>}
        </Notice>
      )}
      <Section title="Total company exposure (direct + through funds)" aside={l.thresholds.rule}>
        {!l.companies.length ? <p className="text-sm text-muted-foreground">No priced company exposure yet.</p> : (
          <div className="overflow-x-auto">
            <table className="tnum w-full text-sm">
              <thead className="text-xs text-muted-foreground">
                <tr>
                  <th className="py-1 text-left font-normal">Company</th>
                  <th className="py-1 pl-4 text-right font-normal">Direct</th>
                  {fundCols.map((f) => <th key={f} className="max-w-36 py-1 pl-4 text-right font-normal">via {f.split(" - ")[0]}</th>)}
                  <th className="py-1 pl-4 text-right font-normal">Total</th>
                  <th className="py-1 pl-3 text-left font-normal">Level</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((c) => (
                  <tr key={c.isin} className="border-t border-border align-top" title={c.calculation ?? undefined}>
                    <td className="py-1.5 pr-2">
                      <div>{c.name}</div>
                      <div className="text-xs text-muted-foreground">{c.isin}</div>
                      {c.reason && <div className="text-xs text-muted-foreground">Reason: {c.reason}</div>}
                    </td>
                    <td className="py-1.5 pl-4 text-right">{c.direct_paise ? formatPct(c.direct_pct, 2) : "—"}</td>
                    {fundCols.map((f) => {
                      const v = c.via.find((x) => x.fund === f);
                      return <td key={f} className="py-1.5 pl-4 text-right text-muted-foreground">{v ? formatPct(v.pct, 2) : "—"}</td>;
                    })}
                    <td className="py-1.5 pl-4 text-right font-medium">{formatPct(c.total_pct, 2)}</td>
                    <td className="py-1.5 pl-3">{c.level && <LevelBadge level={c.level} />}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {l.companies.length > 20 && (
              <Button variant="ghost" size="sm" className="mt-2" onClick={() => setShowAll(!showAll)}>
                {showAll ? "Show top 20" : `Show all ${l.companies.length}`}
              </Button>
            )}
          </div>
        )}
        <p className="mt-2 text-xs text-muted-foreground">{l.basis} Total portfolio {formatINR(l.total_value_paise)}.</p>
        {l.coverage.length > 0 && (
          <p className="mt-1 text-xs text-muted-foreground">
            Sources: {l.coverage.map((c) => `${c.name.split(" - ")[0]} — ${c.label} (equity ${formatPct(c.equity_weight)} of NAV)`).join("; ")}.
          </p>
        )}
      </Section>
    </>
  );
}

function OverlapView({ o }: { o: Overlap }) {
  const [open, setOpen] = useState<number | null>(null);
  return (
    <Section title="Overlap between funds" aside={o.basis}>
      {!o.pairs.length ? (
        <p className="text-sm text-muted-foreground">Needs holdings for at least two funds{o.not_looked_through.length ? ` (missing: ${o.not_looked_through.join("; ")})` : ""}.</p>
      ) : (
        <ul className="flex flex-col">
          {o.pairs.map((p, i) => (
            <li key={i} className="border-b border-border py-2 last:border-0">
              <button type="button" className="flex w-full items-center justify-between gap-3 text-left text-sm" onClick={() => setOpen(open === i ? null : i)}>
                <span>{p.fund_a.split(" - ")[0]} ↔ {p.fund_b.split(" - ")[0]} <span className="text-xs text-muted-foreground">({p.common_count} common)</span></span>
                <span className="tnum font-medium">{formatPct(p.overlap)}</span>
              </button>
              {open === i && (
                <table className={cn("tnum mt-2 w-full text-xs")}>
                  <tbody>
                    {p.common.map((c) => (
                      <tr key={c.isin} className="border-t border-border">
                        <td className="py-1">{c.name}</td>
                        <td className="py-1 text-right">{formatPct(c.weight_a, 2)} / {formatPct(c.weight_b, 2)}</td>
                        <td className="py-1 text-right font-medium">min {formatPct(c.min, 2)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </li>
          ))}
        </ul>
      )}
    </Section>
  );
}
