"use client";

import { ErrorBox, Loading, PageHeader, Section } from "@/components/common";
import { useApi, type SourceHealth } from "@/lib/api";
import { formatDateTime } from "@/lib/format";
import { cn } from "@/lib/utils";

const CELL: Record<string, string> = { ok: "bg-status-low", failed: "bg-status-high", mixed: "bg-status-moderate", none: "bg-muted" };

export default function SourcesPage() {
  const { data, error, loading } = useApi<SourceHealth>("/source-health");
  return (
    <>
      <PageHeader title="Source health" subtitle={data?.note} />
      {error && <ErrorBox message={error} />}
      {loading && !data && <Loading />}
      {data && (
        <Section title="Data sources" aside={<span className="inline-flex gap-3"><Legend c="ok" /> <Legend c="mixed" /> <Legend c="failed" /> <Legend c="none" /></span>}>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="text-xs text-muted-foreground">
                <tr><th className="py-1 text-left font-normal">Source</th><th className="py-1 text-left font-normal">Last success</th>
                  <th className="py-1 text-left font-normal">Last failure</th><th className="py-1 text-left font-normal">Last 30 days</th></tr>
              </thead>
              <tbody>
                {data.sources.map((r) => (
                  <tr key={r.source} className="border-t border-border align-top">
                    <td className="py-2 pr-3">{r.source}{r.last_error && <div className="max-w-80 text-xs text-status-high">{r.last_error}</div>}</td>
                    <td className="py-2 pr-3 text-xs whitespace-nowrap">{r.last_success ? formatDateTime(r.last_success) : "never"}</td>
                    <td className="py-2 pr-3 text-xs whitespace-nowrap">{r.last_failure ? formatDateTime(r.last_failure) : "—"}</td>
                    <td className="py-2">
                      <div className="flex gap-[2px]" role="img" aria-label={`${r.source}: daily status for 30 days`}>
                        {r.history.map((h) => <span key={h.date} title={`${h.date}: ${h.status} (${h.events} event(s))`} className={cn("h-4 w-2 rounded-[2px]", CELL[h.status])} />)}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Section>
      )}
    </>
  );
}

function Legend({ c }: { c: string }) {
  return <span className="inline-flex items-center gap-1"><span className={cn("inline-block h-3 w-2 rounded-[2px]", CELL[c])} />{c}</span>;
}
