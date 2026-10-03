import type { ComponentProps, ReactNode } from "react";
import { cn } from "@/lib/utils";

export function Field({ label, hint, children, className }: {
  label: string; hint?: ReactNode; children: ReactNode; className?: string;
}) {
  return (
    <label className={cn("flex flex-col gap-1 text-sm", className)}>
      <span className="text-xs text-muted-foreground">{label}</span>
      {children}
      {hint && <span className="text-xs text-muted-foreground">{hint}</span>}
    </label>
  );
}

export function Select({ className, ...props }: ComponentProps<"select">) {
  return (
    <select
      className={cn("h-8 rounded-lg border border-input bg-input/30 px-2 text-sm outline-none focus-visible:ring-3 focus-visible:ring-ring/50", className)}
      {...props}
    />
  );
}

/** Keep digits and one decimal point (money/quantity inputs). */
export function numeric(v: string): string {
  const cleaned = v.replace(/[^0-9.]/g, "");
  const [i, ...rest] = cleaned.split(".");
  return rest.length ? `${i}.${rest.join("")}` : i;
}

/** Rupees string -> integer paise (no float arithmetic). */
export function rupeesToPaise(v: string): number | null {
  if (!/^\d+(\.\d{0,2})?$/.test(v.trim())) return null;
  const [i, f = ""] = v.trim().split(".");
  return Number(i) * 100 + Number((f + "00").slice(0, 2));
}
