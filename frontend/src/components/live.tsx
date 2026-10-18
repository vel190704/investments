"use client";

import Link from "next/link";
import { useState } from "react";
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { ErrorBox, Notice, Section, Stat } from "@/components/common";
import { Button } from "@/components/ui/button";
import type { LiveRowT, LiveView } from "@/lib/api";
import { formatDateTime, formatINR, formatPct, formatPrice, signClass } from "@/lib/format";
import { useLive } from "@/lib/live";
import { cn } from "@/lib/utils";

export function timeIST(iso: string | null | undefined): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit", second: "2-digit", timeZone: "Asia/Kolkata" });
}

export function MarketBadge({ m }: { m: LiveView["market"] }) {
  return (
    <span title={m.hours}
          className={cn("rounded border px-1.5 py-0.5 text-xs font-medium",
                        m.open ? "border-status-low/50 text-status-low" : "border-border text-muted-foreground")}>
      {m.label}{m.open ? "" : ` · ${m.reason}`}
    </span>
  );
}

export function StaleBadge() {
  return <span className="ml-1 rounded border border-status-moderate/50 px-1 text-[10px] text-status-moderate">delayed/stale</span>;
}

export function LiveToggle({ live }: { live: ReturnType<typeof useLive> }) {
  const on = live.data?.enabled ?? false;
  return (
    <label className="flex items-center gap-2 text-sm">
      <input type="checkbox" checked={on} disabled={live.busy || !live.data} onChange={(e) => live.setEnabled(e.target.checked)} />
      Live {on ? "on" : "off"}
    </label>
  );
}

/** Real quotes only: each point is a stored 1-minute bar; nothing is drawn between gaps it doesn't have. */
export function Sparkline({ points, up }: { points: { ts: string; price: string }[]; up: boolean | null }) {
  if (points.length < 2) return <span className="text-[10px] text-muted-foreground">—</span>;
  const w = 84, h = 22;
  const ys = points.map((p) => Number(p.price));
  const t0 = new Date(points[0].ts).getTime(), t1 = new Date(points[points.length - 1].ts).getTime();
  const lo = Math.min(...ys), hi = Math.max(...ys);
  const x = (ts: string) => (t1 === t0 ? 0 : ((new Date(ts).getTime() - t0) / (t1 - t0)) * w);
  const y = (v: number) => (hi === lo ? h / 2 : h - ((v - lo) / (hi - lo)) * h);
  const d = points.map((p, i) => `${i ? "L" : "M"}${x(p.ts).toFixed(1)},${y(Number(p.price)).toFixed(1)}`).join(" ");
  return (
    <svg width={w} height={h} viewBox={`0 0 ${w} ${h}`} role="img" aria-label="Intraday price, today"
         className={up === null ? "text-muted-foreground" : up ? "text-gain" : "text-loss"}>
      <path d={d} fill="none" stroke="currentColor" strokeWidth={1.5} />
    </svg>
  );
}

/** Live cell for the Stocks table: live price (or last close when the market is closed), day change, sparkline. */
export function LiveCell({ r, view }: { r: LiveRowT | undefined; view: LiveView | null }) {
  if (!view || !r) return <span className="text-xs text-muted-foreground">—</span>;
  if (!view.market.open || !view.enabled || !r.price || !r.quote_ts || r.quote_ts < view.market.session_date) {
    return (
      <div className="text-xs text-muted-foreground" title={r.last_close_source ?? undefined}>
        {view.market.open && view.enabled && r.error ? <span className="text-status-high">quote failed</span>
          : <>Last close {r.last_close ? formatPrice(r.last_close) : "N/A"}<div>{r.last_close_date ?? ""}</div></>}
      </div>
    );
  }
  const ch = r.day_change_pct === null ? null : Number(r.day_change_pct);
  return (
    <div className="flex items-center justify-end gap-2" title={`${r.source} · quote ${formatDateTime(r.quote_ts)}`}>
      <Sparkline points={r.spark} up={ch === null ? null : ch >= 0} />
      <div className="text-right">
        <div>{formatPrice(r.price)}{r.stale && <StaleBadge />}</div>
        <div className={cn("text-xs", signClass(ch))}>{ch === null ? "no prev. close" : formatPct(ch, 2, true)} · {timeIST(r.quote_ts)}</div>
      </div>
    </div>
  );
}

export function LiveHeader({ live, compact = false }: { live: ReturnType<typeof useLive>; compact?: boolean }) {
  const v = live.data;
  const [note, setNote] = useState<string | null>(null);
  async function manual() {
    const c = await live.refresh();
    setNote(c && !c.ran ? c.reason ?? null : null);
  }
  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-wrap items-center gap-3 text-sm">
        <LiveToggle live={live} />
        {v && <MarketBadge m={v.market} />}
        {v && (
          <span className="text-xs text-muted-foreground">
            {v.last_cycle?.at ? `Last poll ${timeIST(v.last_cycle.at)} IST (${v.last_cycle.succeeded}/${v.last_cycle.requested} ok)` : "No poll yet"}
            {v.enabled && ` · every ${v.poll_seconds}s while this tab is visible`}
          </span>
        )}
        <Button size="sm" variant="ghost" disabled={live.busy} onClick={manual}>Refresh quotes now</Button>
      </div>
      {note && <p className="text-xs text-muted-foreground">{note}</p>}
      {live.error && <ErrorBox message={live.error} />}
      {!compact && v && v.holidays_entered === 0 && (
        <Notice tone="warn">
          No exchange holidays entered yet, so every weekday counts as a trading day. Add them in{" "}
          <Link className="underline" href="/settings#market-holidays">Settings › Market holidays</Link> (verify against the NSE holiday list).
        </Notice>
      )}
    </div>
  );
}

export function LivePanel() {
  const live = useLive();
  const v = live.data;
  return (
    <Section title="Live prices (stocks & ETFs)" aside={v?.source}>
      <LiveHeader live={live} />
      {v && !v.enabled && (
        <p className="mt-2 text-sm text-muted-foreground">
          Live is off. When on, quotes for your direct stocks and ETFs are polled every {v.poll_seconds}s during market
          hours ({v.market.hours}), only while this app is open. Values above are end-of-day.
        </p>
      )}
      {v && v.enabled && !v.market.open && (
        <p className="mt-2 text-sm text-muted-foreground">
          Market closed ({v.market.reason}). Next open {formatDateTime(v.market.next_open)}. Values shown are the last close.
        </p>
      )}
      {v && v.enabled && v.market.open && v.totals && <LiveTotals v={v} />}
      {v && (
        <p className="mt-2 text-xs text-muted-foreground">
          {v.funds.note}{" "}
          {v.funds.value_paise !== null && <>Funds at their latest NAV ({v.funds.nav_dates.join(", ")}): {formatINR(v.funds.value_paise)}. </>}
          {v.funds.unpriced.length > 0 && <>No NAV yet for {v.funds.unpriced.length} fund(s): Data unavailable (confirm scheme codes on Mappings).</>}
        </p>
      )}
    </Section>
  );
}

function LiveTotals({ v }: { v: LiveView }) {
  const t = v.totals!;
  return (
    <div className="mt-3 flex flex-col gap-3">
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-3">
        <Stat label="Live value (fresh quotes)" value={formatINR(t.value_paise)} sub={`${t.included.length} of ${v.rows.length} stocks/ETFs`} />
        <Stat label="Day P&L vs previous close" value={t.day_pnl_paise === null ? "N/A" : formatINR(t.day_pnl_paise, { signed: true })}
              sub={t.day_pnl_pct === null ? "no previous close stored" : formatPct(t.day_pnl_pct, 2, true)} />
        <Stat label="Stale after" value={`${v.stale_after_s}s`} sub="two poll intervals" />
      </div>
      {t.excluded.length > 0 && (
        <Notice tone="warn">
          Not in the live totals: {t.excluded.map((e) => `${e.name} (${e.reason})`).join("; ")}.
        </Notice>
      )}
      {t.no_previous_close.length > 0 && (
        <p className="text-xs text-muted-foreground">No previous close stored for {t.no_previous_close.join(", ")}: in value, not in day P&L.</p>
      )}
      {v.series.length > 1 && <IntradayChart v={v} />}
    </div>
  );
}

function compact(paise: number) {
  const r = paise / 100;
  if (r >= 1e7) return `₹${(r / 1e7).toFixed(2)}Cr`;
  if (r >= 1e5) return `₹${(r / 1e5).toFixed(2)}L`;
  return `₹${(r / 1e3).toFixed(1)}k`;
}

function IntradayChart({ v }: { v: LiveView }) {
  return (
    <div>
      <div className="h-48 w-full" role="img" aria-label="Portfolio intraday value of stocks and ETFs with fresh quotes">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={v.series} margin={{ top: 6, right: 12, bottom: 0, left: 4 }}>
            <CartesianGrid stroke="var(--border)" vertical={false} />
            <XAxis dataKey="ts" tickFormatter={(t) => timeIST(t).slice(0, 5)} stroke="var(--muted-foreground)" tick={{ fontSize: 11 }} minTickGap={40} />
            <YAxis tickFormatter={compact} stroke="var(--muted-foreground)" tick={{ fontSize: 11 }} width={60} domain={["auto", "auto"]} />
            <Tooltip isAnimationActive={false}
                     content={({ active, payload }) => active && payload?.length ? (
                       <div className="rounded-md border border-border bg-popover px-2 py-1 text-xs">
                         <div>{timeIST((payload[0].payload as { ts: string }).ts)} IST</div>
                         <div className="tnum">{formatINR((payload[0].payload as { value_paise: number }).value_paise)}</div>
                       </div>) : null} />
            <Line type="linear" dataKey="value_paise" stroke="var(--series-1)" strokeWidth={2} dot={false} isAnimationActive={false} />
          </LineChart>
        </ResponsiveContainer>
      </div>
      <p className="text-[11px] text-muted-foreground">{v.series_note}</p>
    </div>
  );
}
