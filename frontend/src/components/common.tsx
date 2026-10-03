import type { ReactNode } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { AsOf, Flag } from "@/lib/api";
import { formatDate, formatDateTime } from "@/lib/format";
import { cn } from "@/lib/utils";

export function PageHeader({ title, subtitle, actions }: { title: string; subtitle?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="mb-6 flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">{title}</h1>
        {subtitle && <p className="mt-1 text-sm text-muted-foreground">{subtitle}</p>}
      </div>
      {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
    </div>
  );
}

export function Stat({ label, value, sub, valueClass }: {
  label: string; value: ReactNode; sub?: ReactNode; valueClass?: string;
}) {
  return (
    <Card size="sm">
      <CardContent className="flex flex-col gap-1">
        <span className="text-xs text-muted-foreground">{label}</span>
        <span className={cn("text-2xl font-semibold tracking-tight", valueClass)}>{value}</span>
        {sub && <span className="text-xs text-muted-foreground">{sub}</span>}
      </CardContent>
    </Card>
  );
}

export function Section({ title, children, aside, className }: {
  title: string; children: ReactNode; aside?: ReactNode; className?: string;
}) {
  return (
    <Card className={className}>
      <CardHeader className="flex flex-row items-start justify-between gap-2">
        <CardTitle>{title}</CardTitle>
        {aside && <div className="text-xs text-muted-foreground">{aside}</div>}
      </CardHeader>
      <CardContent>{children}</CardContent>
    </Card>
  );
}

/** Source + as-of line required next to every market-derived number. */
export function SourceNote({ asOf, className }: { asOf: AsOf[]; className?: string }) {
  if (!asOf.length) {
    return <p className={cn("text-xs text-muted-foreground", className)}>Market data: Data unavailable (no prices fetched yet).</p>;
  }
  return (
    <div className={cn("space-y-0.5 text-xs text-muted-foreground", className)}>
      {asOf.map((a) => (
        <p key={a.source}>
          Source: {a.source} · price date {a.price_dates.map(formatDate).join(", ")} · fetched {formatDateTime(a.fetched_at)}
        </p>
      ))}
    </div>
  );
}

const LEVEL_STYLE: Record<Flag["level"], string> = {
  LOW: "border-status-low/50 text-status-low",
  MODERATE: "border-status-moderate/50 text-status-moderate",
  HIGH: "border-status-high/50 text-status-high",
};
const LEVEL_ICON: Record<Flag["level"], string> = { LOW: "●", MODERATE: "▲", HIGH: "■" };

/** Status colour always paired with an icon shape and the word itself. */
export function LevelBadge({ level }: { level: Flag["level"] }) {
  return (
    <span className={cn("inline-flex items-center gap-1 rounded border px-1.5 py-0.5 text-xs font-semibold", LEVEL_STYLE[level])}>
      <span aria-hidden>{LEVEL_ICON[level]}</span>
      {level}
    </span>
  );
}

export function FlagRow({ flag }: { flag: Flag }) {
  return (
    <div className="flex flex-col gap-1 border-b border-border py-3 last:border-0">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm font-medium">{flag.title}:</span>
        <LevelBadge level={flag.level} />
      </div>
      <p className="text-sm">Reason: {flag.reason}</p>
      <p className="tnum text-xs text-muted-foreground">Calculation: {flag.calculation}</p>
      <p className="text-xs text-muted-foreground">Thresholds: {flag.thresholds}</p>
    </div>
  );
}

export function Loading() {
  return <p className="text-sm text-muted-foreground">Loading…</p>;
}

export function ErrorBox({ message }: { message: string }) {
  return (
    <div role="alert" className="rounded-md border border-destructive/40 bg-destructive/10 p-3 text-sm text-destructive">
      {message.includes("ECONNREFUSED") || message.startsWith("500")
        ? "Cannot reach the backend on 127.0.0.1:8000. Is it running? (make dev)"
        : message}
    </div>
  );
}

export function Notice({ children, tone = "info" }: { children: ReactNode; tone?: "info" | "warn" }) {
  return (
    <div className={cn(
      "rounded-md border p-3 text-sm",
      tone === "warn" ? "border-status-moderate/40 bg-status-moderate/10" : "border-border bg-muted/40",
    )}>
      {children}
    </div>
  );
}

export function EmptyState() {
  return (
    <Notice>
      No portfolio data yet. Import your workbook on the <a className="underline" href="/import">Import</a> page,
      confirm identifiers on <a className="underline" href="/mappings">Mappings</a>, then refresh prices.
    </Notice>
  );
}
