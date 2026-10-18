"use client";

import Link from "next/link";
import { useState } from "react";
import { AnalysisFooter, ErrorBox, Loading, Notice, PageHeader, Section } from "@/components/common";
import { Field, Select } from "@/components/form";
import { Button } from "@/components/ui/button";
import { apiPost, errorText, useApi, type NewsFeed } from "@/lib/api";
import { formatDateTime, formatPct } from "@/lib/format";
import { cn } from "@/lib/utils";

export default function NewsPage() {
  const [isin, setIsin] = useState("");
  const [category, setCategory] = useState("");
  const [days, setDays] = useState("30");
  const q = new URLSearchParams({ days, ...(isin ? { isin } : {}), ...(category ? { category } : {}) });
  const { data, error, loading, reload } = useApi<NewsFeed>(`/news?${q}`);
  const [msg, setMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function refresh() {
    setBusy(true);
    try {
      const r = await apiPost<{ added: number; duplicates: number; pruned: number; alerts_created: number }>("/news/refresh");
      setMsg(`${r.added} new item(s); ${r.duplicates} near-duplicate(s) skipped; ${r.pruned} older than 90 days removed; ${r.alerts_created} alert(s).`);
      reload();
    } catch (e) {
      setMsg(errorText(e));
    } finally {
      setBusy(false);
    }
  }
  async function suggest() {
    try {
      const r = await apiPost<{ suggested: number }>("/news/suggest-categories");
      setMsg(`AI suggested a category for ${r.suggested} item(s) the keyword rules left as “other”.`);
      reload();
    } catch (e) {
      setMsg(errorText(e));
    }
  }

  return (
    <>
      <PageHeader
        title="News & announcements"
        subtitle="Exchange announcements (NSE official feeds) and market news that name your companies, sorted by your look-through exposure."
        actions={<>
          <Button variant="outline" onClick={suggest}>AI-suggest “other” categories</Button>
          <Button variant="outline" disabled={busy} onClick={refresh}>{busy ? "Fetching…" : "Refresh"}</Button>
        </>}
      />
      {msg && <Notice>{msg}</Notice>}
      {error && <ErrorBox message={error} />}
      {loading && !data && <Loading />}
      {data && (
        <div className="mt-4 flex flex-col gap-4">
          <Section title="Filters">
            <div className="flex flex-wrap gap-3">
              <Field label="Company">
                <Select value={isin} onChange={(e) => setIsin(e.target.value)}>
                  <option value="">All tracked</option>
                  {data.companies.map((c) => <option key={c.isin} value={c.isin}>{c.symbol ?? c.name} ({formatPct(c.exposure)})</option>)}
                </Select>
              </Field>
              <Field label="Category">
                <Select value={category} onChange={(e) => setCategory(e.target.value)}>
                  <option value="">All</option>
                  {data.categories.map((c) => <option key={c} value={c}>{c}</option>)}
                </Select>
              </Field>
              <Field label="Period">
                <Select value={days} onChange={(e) => setDays(e.target.value)}>
                  {["7", "30", "90"].map((d) => <option key={d} value={d}>Last {d} days</option>)}
                </Select>
              </Field>
            </div>
          </Section>

          {data.untracked.length > 0 && (
            <Notice>
              Not tracked: {data.untracked.map((u) => u.name).join(", ")} — {data.untracked[0].reason.split("—")[1]?.trim() ?? data.untracked[0].reason}.{" "}
              <Link className="underline" href="/mappings">Mappings</Link>
            </Notice>
          )}

          <Section title={`Items (${data.items.length})`} aside={data.basis}>
            {!data.items.length ? <EmptyNews e={data.empty} /> : (
              <ul className="flex flex-col">
                {data.items.map((n) => (
                  <li key={n.id} className="border-b border-border py-2.5 last:border-0">
                    <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                      <span className="font-medium text-foreground">{n.company}</span>
                      <span>· your exposure {formatPct(n.exposure)}{n.via_funds.length ? ` (incl. via ${n.via_funds.map((f) => f.split(" - ")[0]).join(", ")})` : ""}</span>
                      <span className="rounded border border-border px-1.5">{n.category}</span>
                      <span className={cn("rounded px-1.5", n.category_origin === "MODEL" ? "border border-series-1/50 text-series-1" : "")}>
                        {n.category_origin === "MODEL" ? "category: AI-suggested" : "category: keyword rule"}
                      </span>
                    </div>
                    <a href={n.url} target="_blank" rel="noreferrer noopener" className="mt-0.5 block text-sm hover:underline">{n.title}</a>
                    {n.summary && <p className="mt-0.5 line-clamp-2 text-xs text-muted-foreground">{n.summary}</p>}
                    <p className="mt-0.5 text-[11px] text-muted-foreground">
                      {n.source} ({n.source_kind === "EXCHANGE" ? "exchange filing" : "news"}) · published {formatDateTime(n.published_at)} · fetched {formatDateTime(n.fetched_at)}
                    </p>
                  </li>
                ))}
              </ul>
            )}
          </Section>

          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            <Section title="Mutual funds">
              <ul className="flex flex-col gap-2 text-sm">
                {data.funds.map((f) => (
                  <li key={f.fund}>
                    <div className="font-medium">{f.fund}</div>
                    <div className="text-xs text-muted-foreground">{f.note}{f.companies.length ? ` ${f.companies.join(", ")}.` : ""}</div>
                  </li>
                ))}
              </ul>
            </Section>
            <Section title="Sources">
              <ul className="flex flex-col gap-1 text-xs">
                {data.sources.map((s) => (
                  <li key={s.source} className="flex justify-between gap-2">
                    <span>{s.source}</span>
                    <span className={s.ok ? "text-muted-foreground" : "text-status-high"}>{s.ok ? (s.items_fetched !== null ? `${s.items_fetched} fetched · ${s.items_matched ?? 0} matched` : s.message) : `▲ ${s.message}`}</span>
                  </li>
                ))}
                {(() => {
                  const g = data.companies.flatMap((c) => c.unavailable).find((u) => u.source === "Google News");
                  return g ? <li className="flex justify-between gap-2"><span>Google News</span><span className="text-status-high">▲ {g.message}</span></li> : null;
                })()}
              </ul>
              <p className="mt-2 text-xs text-muted-foreground">
                Requests are cached, rate-limited, identify this tool, and respect robots.txt. Blocked sources are shown as unavailable, never worked around.
              </p>
            </Section>
          </div>
          <AnalysisFooter />
        </div>
      )}
    </>
  );
}

function EmptyNews({ e }: { e: NewsFeed["empty"] }) {
  if (!e) return null;
  return (
    <div className="flex flex-col gap-2 text-sm">
      <p className={e.kind === "SOURCES_FAILED" ? "text-status-high" : "text-muted-foreground"}>
        {e.message}
        {e.kind === "NO_TRACKED_HOLDINGS" && <> <Link className="underline" href="/mappings">Open Mappings</Link></>}
      </p>
      {e.failed.length > 0 && (
        <ul className="text-xs text-muted-foreground">
          {e.failed.map((f) => <li key={f.source}><span className="text-foreground">{f.source}:</span> {f.message}</li>)}
        </ul>
      )}
    </div>
  );
}
