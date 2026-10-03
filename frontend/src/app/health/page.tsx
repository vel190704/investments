"use client";

import Link from "next/link";
import { ErrorBox, LevelBadge, Loading, Notice, PageHeader, Section } from "@/components/common";
import { useApi, type Health } from "@/lib/api";
import { formatDate } from "@/lib/format";

export default function HealthPage() {
  const { data, error, loading } = useApi<Health>("/health-check");
  return (
    <>
      <PageHeader title="Portfolio health" subtitle={data ? `${data.note} Valuation date ${formatDate(data.valuation_date)}.` : undefined} />
      {error && <ErrorBox message={error} />}
      {loading && !data && <Loading />}
      {data && (
        <div className="flex flex-col gap-4">
          {data.stale.map((s) => <Notice key={s.warning} tone="warn">{s.warning}</Notice>)}
          {data.not_looked_through.length > 0 && (
            <Notice>
              Not looked through yet: {data.not_looked_through.join("; ")}. Upload their portfolio disclosures on{" "}
              <Link className="underline" href="/overlap">Fund look-through</Link> to include indirect exposure.
            </Notice>
          )}
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            {data.dimensions.map((d) => (
              <Section key={d.key} title={d.title}
                       aside={d.level ? <LevelBadge level={d.level} /> : d.info_only ? "Information only" : d.available ? "" : "N/A"}>
                <div className="flex flex-col gap-1.5">
                  {d.value && <div className="tnum text-xl font-semibold">{d.value}</div>}
                  <p className="text-sm">{d.level ? `Reason: ${d.reason}` : d.reason}</p>
                  {d.calculation && <p className="tnum text-xs text-muted-foreground">Calculation: {d.calculation}</p>}
                  {d.thresholds && <p className="text-xs text-muted-foreground">Thresholds: {d.thresholds}</p>}
                </div>
              </Section>
            ))}
          </div>
          <p className="text-xs text-muted-foreground">
            Thresholds are defined in code and editable in <Link className="underline" href="/settings">Settings</Link>.
          </p>
        </div>
      )}
    </>
  );
}
