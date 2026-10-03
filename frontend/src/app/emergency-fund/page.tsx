"use client";

import Link from "next/link";
import { ErrorBox, Loading, Notice, PageHeader, Section, Stat } from "@/components/common";
import { useApi, type EmergencyFund } from "@/lib/api";
import { formatINR, formatPct } from "@/lib/format";

export default function EmergencyFundPage() {
  const { data, error, loading } = useApi<EmergencyFund>("/emergency-fund");
  const s = data?.status;
  const pct = s?.percent_complete ? Math.min(Number(s.percent_complete), 1) : 0;
  return (
    <>
      <PageHeader title="Emergency fund" subtitle={data?.note} />
      {error && <ErrorBox message={error} />}
      {loading && !data && <Loading />}
      {data && !data.is_set && (
        <Notice>
          No emergency-fund details yet. Enter your monthly essential expenses, current balance and a target of 3–6
          months in <Link className="underline" href="/settings">Settings</Link>. Nothing is assumed until you do.
        </Notice>
      )}
      {s && (
        <div className="flex flex-col gap-4">
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            <Stat label="Target" value={formatINR(s.target_paise, { decimals: false })}
                  sub={`${formatINR(s.monthly_expenses_paise, { decimals: false })} × ${s.target_months} months`} />
            <Stat label="Current balance" value={formatINR(s.balance_paise, { decimals: false })}
                  sub={s.months_covered ? `covers ${Number(s.months_covered).toFixed(1)} months of expenses` : undefined} />
            <Stat label="Remaining to target" value={formatINR(s.remaining_paise, { decimals: false })}
                  sub={s.complete ? "Target reached" : "target − balance"} />
          </div>
          <Section title="Progress" aside={`${formatPct(s.percent_complete)} complete`}>
            {/* meter: single ratio against a limit */}
            <div className="h-3 w-full overflow-hidden rounded-full bg-muted" role="meter" aria-valuemin={0} aria-valuemax={100}
                 aria-valuenow={Math.round(pct * 100)} aria-label="Emergency fund progress">
              <div className="h-full rounded-full bg-series-1" style={{ width: `${pct * 100}%` }} />
            </div>
            <p className="tnum mt-2 text-xs text-muted-foreground">
              {formatINR(s.balance_paise)} / {formatINR(s.target_paise)} = {formatPct(s.percent_complete)}
            </p>
          </Section>
        </div>
      )}
    </>
  );
}
