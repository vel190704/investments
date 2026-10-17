"use client";

import Link from "next/link";
import { useState } from "react";
import { ErrorBox, Loading, Notice, PageHeader, Section } from "@/components/common";
import { Button } from "@/components/ui/button";
import { apiPost, errorText, useApi, type AlertItem } from "@/lib/api";
import { formatDateTime } from "@/lib/format";
import { cn } from "@/lib/utils";

type AlertsPage = { alerts: AlertItem[]; unread: number; rules: Record<string, unknown> };
const RULE: Record<string, string> = {
  announcement: "Announcement", concentration_change: "Concentration level", disclosure_stale: "Stale disclosure", review_due: "Review due",
};

export default function AlertsPageView() {
  const { data, error, loading, reload } = useApi<AlertsPage>("/alerts");
  const [msg, setMsg] = useState<string | null>(null);
  async function evaluate() {
    try {
      const r = await apiPost<{ created: number }>("/alerts/evaluate");
      setMsg(`${r.created} new alert(s).`);
      reload();
    } catch (e) {
      setMsg(errorText(e));
    }
  }
  return (
    <>
      <PageHeader title="Alerts" subtitle="In-app only — no email or push. Rules are toggled in Settings."
                  actions={<Button variant="outline" onClick={evaluate}>Check now</Button>} />
      {msg && <Notice>{msg}</Notice>}
      {error && <ErrorBox message={error} />}
      {loading && !data && <Loading />}
      {data && (
        <Section title={`${data.unread} unread`} aside={<Link className="underline" href="/settings">Alert rules</Link>}>
          {!data.alerts.length ? <p className="text-sm text-muted-foreground">No alerts yet.</p> : (
            <ul className="flex flex-col">
              {data.alerts.map((a) => (
                <li key={a.id} className={cn("flex items-start justify-between gap-3 border-b border-border py-2 last:border-0", a.read && "opacity-60")}>
                  <div>
                    <div className="text-xs text-muted-foreground">{RULE[a.rule] ?? a.rule} · {formatDateTime(a.created_at)}</div>
                    <div className="text-sm font-medium">{a.title}</div>
                    <div className="text-xs text-muted-foreground">{a.detail}</div>
                  </div>
                  {!a.read && <Button size="sm" variant="ghost" onClick={async () => { await apiPost(`/alerts/${a.id}/read`); reload(); }}>Mark read</Button>}
                </li>
              ))}
            </ul>
          )}
        </Section>
      )}
    </>
  );
}
