"use client";

import { AssetDonut, ASSET_CLASS_COLOR } from "@/components/asset-donut";
import { EmptyState, ErrorBox, FlagRow, Loading, Notice, PageHeader, Section, SourceNote } from "@/components/common";
import { RefreshButton } from "@/components/refresh-button";
import { useApi, type Allocation } from "@/lib/api";
import { formatINR, formatPct, pctLabel } from "@/lib/format";

function fmtThreshold(v: string, unit: string) {
  return unit === "fraction" ? formatPct(v, 0) : Number(v).toLocaleString("en-IN");
}

export default function AllocationPage() {
  const { data: a, error, loading, reload } = useApi<Allocation>("/allocation");
  const c = a?.concentration;
  const maxW = a ? Math.max(...a.instruments.map((i) => Number(i.weight)), 0) : 0;

  return (
    <>
      <PageHeader title="Allocation & concentration" subtitle={a?.basis} actions={<RefreshButton onDone={reload} />} />
      {error && <ErrorBox message={error} />}
      {loading && !a && <Loading />}
      {a && a.total_value_paise === 0 && !a.excluded_unpriced.length && <EmptyState />}
      {a && (a.total_value_paise > 0 || a.excluded_unpriced.length > 0) && (
        <div className="flex flex-col gap-4">
          {a.excluded_unpriced.length > 0 && (
            <Notice>
              Excluded from weights (Data unavailable): {a.excluded_unpriced.map((x) => x.name).join("; ")}. Weights
              below are shares of {formatINR(a.total_value_paise)} of priced holdings.
            </Notice>
          )}
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            <Section title="Asset classes" aside={`Total ${formatINR(a.total_value_paise)}`}>
              <AssetDonut data={a.asset_classes} />
              <p className="mt-3 text-xs text-muted-foreground">
                International ETFs = Mirae Asset NYSE FANG+ (MAFANG) and Nippon India Hang Seng BeES (HNGSNGBEES):
                rupee-denominated, but the underlying exposure is US / Hong Kong equities.
              </p>
            </Section>

            <Section title="Every holding by weight" aside="% of total portfolio value">
              <ul className="flex flex-col gap-1.5">
                {a.instruments.map((i) => (
                  <li key={i.instrument_id} className="grid grid-cols-[7rem_1fr_3.5rem] items-center gap-2 text-sm"
                      title={`${i.name}: ${formatINR(i.value_paise)} (${pctLabel(i.display_pct)})`}>
                    <span className="truncate">{i.short_name.length > 16 ? i.name.split(" ").slice(0, 2).join(" ") : i.short_name}</span>
                    <span className="h-2.5 rounded-r bg-muted/40">
                      <span className="block h-full rounded-r"
                            style={{ width: `${(Number(i.weight) / maxW) * 100}%`, background: ASSET_CLASS_COLOR[i.asset_class] }} />
                    </span>
                    <span className="tnum text-right">{pctLabel(i.display_pct)}</span>
                  </li>
                ))}
              </ul>
              <p className="mt-3 text-xs text-muted-foreground">Bar colour = asset class (same key as the donut).</p>
            </Section>
          </div>

          {c && (
            <Section title="Company concentration" aside={c.scope}>
              {c.flags.length ? c.flags.map((f) => <FlagRow key={f.key} flag={f} />) : (
                <p className="text-sm text-muted-foreground">No priced direct stock holdings.</p>
              )}
            </Section>
          )}

          {c && c.companies.length > 0 && (
            <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
              <Section title="Companies" aside={`Direct equity ${formatINR(c.direct_equity_value_paise)}`}>
                <table className="tnum w-full text-sm">
                  <thead className="text-xs text-muted-foreground">
                    <tr>
                      <th className="py-1 text-left font-normal">Company</th>
                      <th className="py-1 text-right font-normal">Value</th>
                      <th className="py-1 text-right font-normal">% direct equity</th>
                      <th className="py-1 text-right font-normal">% portfolio</th>
                    </tr>
                  </thead>
                  <tbody>
                    {c.companies.map((co) => (
                      <tr key={co.name} className="border-t border-border">
                        <td className="py-1.5">{co.name}</td>
                        <td className="py-1.5 text-right text-muted-foreground">{formatINR(co.value_paise)}</td>
                        <td className="py-1.5 text-right">{formatPct(co.share_of_direct_equity)}</td>
                        <td className="py-1.5 text-right">{formatPct(co.share_of_portfolio)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </Section>
              <Section title="Thresholds used" aside="Defined in backend/app/calc/concentration.py">
                <table className="w-full text-sm">
                  <thead className="text-xs text-muted-foreground">
                    <tr>
                      <th className="py-1 text-left font-normal">Metric</th>
                      <th className="py-1 pl-3 text-right font-normal">LOW</th>
                      <th className="py-1 pl-3 text-right font-normal">MODERATE</th>
                      <th className="py-1 pl-3 text-right font-normal">HIGH</th>
                    </tr>
                  </thead>
                  <tbody>
                    {c.thresholds.map((t) => (
                      <tr key={t.key} className="border-t border-border align-top">
                        <td className="py-1.5 pr-2">
                          <div>{t.label}</div>
                          <div className="text-xs text-muted-foreground">{t.explanation}</div>
                        </td>
                        <td className="tnum py-1.5 pl-3 text-right whitespace-nowrap">&lt; {fmtThreshold(t.low, t.unit)}</td>
                        <td className="tnum py-1.5 pl-3 text-right whitespace-nowrap">
                          {fmtThreshold(t.low, t.unit)}–{fmtThreshold(t.high, t.unit)}
                        </td>
                        <td className="tnum py-1.5 pl-3 text-right whitespace-nowrap">≥ {fmtThreshold(t.high, t.unit)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </Section>
            </div>
          )}
          <SourceNote asOf={a.data_as_of} />
        </div>
      )}
    </>
  );
}
