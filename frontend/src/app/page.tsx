"use client";

import Link from "next/link";
import { AssetDonut } from "@/components/asset-donut";
import { EmptyState, ErrorBox, FlagRow, Loading, Notice, PageHeader, Section, SourceNote, Stat } from "@/components/common";
import { GrowthChart } from "@/components/growth-chart";
import { RefreshButton } from "@/components/refresh-button";
import { useApi, type Mappings, type Series, type Summary } from "@/lib/api";
import { formatDate, formatINR, formatPct, signClass } from "@/lib/format";

export default function Dashboard() {
  const { data: s, error, loading, reload } = useApi<Summary>("/portfolio/summary");
  const { data: m } = useApi<Mappings>("/mappings");
  const growth = useApi<Series>("/snapshots/series");

  return (
    <>
      <PageHeader
        title="Dashboard"
        subtitle={s ? `Valuation date ${formatDate(s.valuation_date)}` : undefined}
        actions={<RefreshButton onDone={() => { reload(); growth.reload(); }} />}
      />
      {error && <ErrorBox message={error} />}
      {loading && !s && <Loading />}
      {s && !s.has_data && <EmptyState />}
      {s && s.has_data && (
        <div className="flex flex-col gap-4">
          {m && m.pending > 0 && (
            <Notice tone="warn">
              {m.pending} instrument identifier(s) await confirmation. Mutual funds stay “Data unavailable” until
              their AMFI scheme code is confirmed on <Link className="underline" href="/mappings">Mappings</Link>.
            </Notice>
          )}
          {s.excluded_unpriced.length > 0 && (
            <Notice>
              Totals below cover priced holdings only. Excluded (Data unavailable):{" "}
              {s.excluded_unpriced.map((x) => `${x.name} (invested ${formatINR(x.invested_paise)})`).join("; ")}.
            </Notice>
          )}

          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
            <Stat label="Current value" value={formatINR(s.total_value_paise)} sub="Market value of priced holdings" />
            <Stat
              label="Total invested"
              value={formatINR(s.total_invested_paise)}
              sub={s.excluded_unpriced.length
                ? `${formatINR(s.invested_in_priced_paise)} in priced holdings`
                : "Cost basis of current holdings (incl. opening balances)"}
            />
            <Stat
              label="Unrealised P&L"
              value={formatINR(s.pnl_paise, { signed: true })}
              valueClass={signClass(s.pnl_paise)}
              sub={`${formatPct(s.pnl_pct, 2, true)} on ${formatINR(s.invested_in_priced_paise)}`}
            />
            <Stat
              label="Today's change"
              value={s.today_change.paise === null ? "Data unavailable" : formatINR(s.today_change.paise, { signed: true })}
              valueClass={signClass(s.today_change.paise)}
              sub={
                s.today_change.paise === null
                  ? "No previous close available"
                  : `${formatPct(s.today_change.pct, 2, true)} · latest close vs previous close` +
                    (s.today_change.not_covered.length
                      ? ` · excludes ${s.today_change.not_covered.length} holding(s) without a previous price/NAV yet`
                      : "")
              }
            />
            <Stat
              label="Monthly contribution"
              value={formatINR(s.monthly_plan.monthly_total_paise, { decimals: false })}
              sub={s.monthly_plan.items
                .map((i) => `${i.is_bucket ? i.name : i.name.split(" - ")[0]} ${formatPct(i.allocation_fraction, 0)}`)
                .join(" · ")}
            />
            <Stat
              label="XIRR"
              value={s.xirr.rate === null ? "N/A" : formatPct(s.xirr.rate, 2)}
              sub={s.xirr.note ?? "Dated BUY/SIP rows only; OPENING balances excluded"}
            />
          </div>
          {(s.realised_paise !== 0 || s.dividends_paise !== 0) && (
            <p className="text-xs text-muted-foreground">
              Realised P&L {formatINR(s.realised_paise, { signed: true })} · Dividends {formatINR(s.dividends_paise)}
            </p>
          )}

          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            <Section title="Asset-class allocation" aside="Weight = market value / total value">
              <AssetDonut data={s.asset_classes} />
            </Section>
            <Section title="Top concentrations" aside="Share of total portfolio value">
              <table className="w-full text-sm">
                <tbody>
                  {s.top_holdings.map((h) => (
                    <tr key={h.instrument_id} className="border-b border-border last:border-0">
                      <td className="py-1.5 pr-2">
                        <div className="font-medium">{h.short_name}</div>
                        <div className="text-xs text-muted-foreground">{h.asset_class}</div>
                      </td>
                      <td className="tnum py-1.5 pr-2 text-right font-medium">{formatPct(h.weight)}</td>
                      <td className="tnum py-1.5 text-right text-muted-foreground">{formatINR(h.value_paise)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Section>
          </div>

          <Section title="Growth" aside={<Link className="underline" href="/history">History</Link>}>
            {growth.data?.enough_history ? <GrowthChart points={growth.data.points} /> : (
              <p className="text-sm text-muted-foreground">
                History builds from today: {growth.data?.points.length ?? 0} daily snapshot(s) so far. The chart appears
                from the second day; earlier history is never estimated.
              </p>
            )}
          </Section>

          <Section title="Concentration flags" aside={<Link className="underline" href="/allocation">Details & thresholds</Link>}>
            {s.concentration_flags.length
              ? s.concentration_flags.map((f) => <FlagRow key={f.key} flag={f} />)
              : <p className="text-sm text-muted-foreground">No direct stock holdings with prices.</p>}
          </Section>

          <SourceNote asOf={s.data_as_of} />
        </div>
      )}
    </>
  );
}
