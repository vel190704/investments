"use client";

import Link from "next/link";
import { ErrorBox, Loading, Notice, PageHeader, Section } from "@/components/common";
import { useApi, type MonthlyUpdate } from "@/lib/api";
import { formatINR } from "@/lib/format";
import { cn } from "@/lib/utils";

const LINKS: Record<string, string> = { sip_rows: "/transactions", stock_buys: "/transactions", import: "/import", prices: "/", snapshot: "/history" };

export default function MonthlyPage() {
  const { data, error, loading } = useApi<MonthlyUpdate>("/monthly-update");
  return (
    <>
      <PageHeader title="Monthly update" subtitle={data ? `${data.month}: ${data.done} of ${data.total} done. Ticks come from your data, not from checkboxes.` : undefined} />
      {error && <ErrorBox message={error} />}
      {loading && !data && <Loading />}
      {data && (
        <div className="flex flex-col gap-4">
          {data.warnings.map((w) => <Notice key={w} tone="warn">▲ {w}</Notice>)}
          <Section title="Checklist">
            <ol className="flex flex-col gap-2">
              {data.items.map((i, n) => (
                <li key={i.key} className="flex items-start gap-3">
                  <span aria-label={i.done ? "done" : "to do"} className={cn("mt-0.5 inline-flex size-5 shrink-0 items-center justify-center rounded-full border text-xs",
                    i.done ? "border-status-low text-status-low" : "border-border text-muted-foreground")}>{i.done ? "✓" : n + 1}</span>
                  <div>
                    <Link href={LINKS[i.key] ?? "/"} className="text-sm hover:underline">{i.title}</Link>
                    <div className="text-xs text-muted-foreground">{i.detail}</div>
                  </div>
                </li>
              ))}
            </ol>
          </Section>
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            <Section title="Planned funds (monthly_plan)">
              <ul className="tnum text-sm">{data.plan.map((p) => <li key={p.name} className="flex justify-between border-b border-border py-1 last:border-0"><span>{p.name}</span><span>{formatINR(p.monthly_amount_paise, { decimals: false })}</span></li>)}</ul>
            </Section>
            <Section title="Adding SIP rows from Coin">
              <ol className="list-decimal space-y-1 pl-5 text-sm text-muted-foreground">{data.how_to.map((h) => <li key={h}>{h}</li>)}</ol>
            </Section>
          </div>
        </div>
      )}
    </>
  );
}
