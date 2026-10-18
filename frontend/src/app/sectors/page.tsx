"use client";

import Link from "next/link";
import { useState } from "react";
import { ErrorBox, FlagRow, Loading, Notice, PageHeader, Section } from "@/components/common";
import { Button } from "@/components/ui/button";
import { apiPost, errorText, useApi, type Flag, type SectorsPage } from "@/lib/api";
import { formatDate, formatINR, formatPct } from "@/lib/format";
import { cn } from "@/lib/utils";

export default function SectorsPageView() {
  const { data: d, error, loading, reload } = useApi<SectorsPage>("/sectors");
  const [msg, setMsg] = useState<string | null>(null);
  const [fail, setFail] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function refresh() {
    setBusy(true);
    try {
      const r = await apiPost<{ summary: string; errors: string[] }>("/sectors/refresh");
      setFail(null);
      setMsg(r.summary + (r.errors.length ? ` — ${r.errors.join("; ")}` : ""));
      reload();
    } catch (e) {
      setMsg(null);
      setFail(errorText(e));
    } finally {
      setBusy(false);
    }
  }

  const max = d ? Math.max(...d.sectors.map((s) => Number(s.pct)), 0.0001) : 1;
  return (
    <>
      <PageHeader
        title="Sectors"
        subtitle="Sector exposure including what your funds hold. Sector names come from NSE's official index lists (Industry field) unless you override them."
        actions={<Button variant="outline" disabled={busy} onClick={refresh}>{busy ? "Refreshing…" : "Refresh classifications"}</Button>}
      />
      {msg && <Notice>{msg}</Notice>}
      {fail && <ErrorBox message={fail} />}
      {error && <ErrorBox message={error} />}
      {loading && !d && <Loading />}
      {d && (
        <div className="mt-4 flex flex-col gap-4">
          {d.funds_not_looked_through.length > 0 && (
            <Notice>
              Not looked through: {d.funds_not_looked_through.join("; ")} — shown as single rows. Upload disclosures on{" "}
              <Link className="underline" href="/overlap">Fund look-through</Link>.
            </Notice>
          )}
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-[2fr_1fr]">
            <Section title="Exposure by sector" aside="% of total portfolio">
              <ul className="flex flex-col gap-2">
                {d.sectors.map((s) => (
                  <li key={s.sector} className="text-sm">
                    <div className="grid grid-cols-[1fr_4rem] items-center gap-2">
                      <span className="truncate">{s.sector}</span>
                      <span className="tnum text-right">{formatPct(s.pct)}</span>
                    </div>
                    <div className="mt-1 h-1.5 rounded-r bg-muted/40">
                      <div className="h-full rounded-r bg-series-1" style={{ width: `${(Number(s.pct) / max) * 100}%` }} />
                    </div>
                    <div className="mt-0.5 text-xs text-muted-foreground">
                      {s.count} holding(s) · {formatINR(s.value_paise, { decimals: false })} · major: {s.contributors.slice(0, 3).map((c) => `${c.name} ${formatPct(c.pct)}`).join(", ")}
                    </div>
                  </li>
                ))}
              </ul>
              <p className="mt-3 text-xs text-muted-foreground">{d.basis}</p>
            </Section>
            <div className="flex flex-col gap-4">
              <Section title="Sector concentration">
                {d.metrics.flags.length ? d.metrics.flags.map((f) => <FlagRow key={f.key} flag={f as Flag} />) :
                  <p className="text-sm text-muted-foreground">No classified equity exposure yet.</p>}
              </Section>
              <Section title="Geography">
                <p className="tnum text-sm">India {formatPct(d.geography.india_pct)} · International {formatPct(d.geography.international_pct)}</p>
                <ul className="mt-1 text-xs text-muted-foreground">
                  {d.geography.regions.map((r) => <li key={r.region}>{r.region}: {formatPct(r.pct)} ({formatINR(r.value_paise, { decimals: false })})</li>)}
                </ul>
              </Section>
            </div>
          </div>

          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            <Section title="Your desired ranges" aside={<Link className="underline" href="/settings">Edit in Settings</Link>}>
              {!d.ranges.length ? <p className="text-sm text-muted-foreground">No ranges set (there are no defaults).</p> : (
                <ul className="flex flex-col gap-1 text-sm">
                  {d.ranges.map((r) => (
                    <li key={r.sector} className="flex justify-between gap-2">
                      <span>{r.reason}</span>
                      <span className={cn("text-xs whitespace-nowrap", r.status === "IN RANGE" ? "text-status-low" : "text-status-high")}>
                        {r.status === "IN RANGE" ? "●" : "▲"} {r.status}
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </Section>
            <Section title="Your themes" aside={<Link className="underline" href="/settings">Edit in Settings</Link>}>
              {!d.themes.length ? <p className="text-sm text-muted-foreground">No themes defined (there are no defaults). Tag companies by ISIN, e.g. Defence, Power, Banking.</p> : (
                <ul className="flex flex-col gap-2 text-sm">
                  {d.themes.map((t) => (
                    <li key={t.tag}>
                      <div className="flex justify-between"><span className="font-medium">{t.tag}</span><span className="tnum">{formatPct(t.pct)}</span></div>
                      <div className="text-xs text-muted-foreground">
                        {t.members.map((m) => m.name).join(", ") || "no exposure"} (direct + through funds)
                        {t.missing.length > 0 && ` · not held: ${t.missing.join(", ")}`}
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </Section>
          </div>

          <Section title="How each direct holding is classified" aside={<Link className="underline" href="/classification">Override</Link>}>
            <table className="tnum w-full text-sm">
              <tbody>
                {d.direct.map((h) => (
                  <tr key={h.instrument_id} className="border-b border-border last:border-0">
                    <td className="py-1.5">{h.name}</td>
                    <td className="py-1.5">{h.sector}</td>
                    <td className="py-1.5 text-xs text-muted-foreground">
                      {h.manual ? "manual · " : ""}{h.source ?? "no source — set it manually"}{h.as_of ? ` · ${formatDate(h.as_of)}` : ""}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Section>
        </div>
      )}
    </>
  );
}
