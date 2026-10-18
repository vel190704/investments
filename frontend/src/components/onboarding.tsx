"use client";

import Link from "next/link";
import { Button } from "@/components/ui/button";
import { apiDownload } from "@/lib/api";

/** Shown wherever a page has no data yet: what to do first, with the Excel template. */
export function Onboarding() {
  return (
    <div className="rounded-xl border border-border p-4 text-sm">
      <div className="font-medium">No portfolio data yet</div>
      <ol className="mt-2 list-decimal space-y-1 pl-5 text-muted-foreground">
        <li>Download the blank template (or use your own tracker with the same column names) and fill in the
          <i> transactions</i> sheet: one row per buy, SIP, sell, dividend or opening balance.</li>
        <li>Upload it on the <Link className="underline" href="/import">Import</Link> page. You see a preview first; nothing changes until you confirm.</li>
        <li>Confirm the proposed identifiers on <Link className="underline" href="/mappings">Mappings</Link> (funds get NAVs only after you confirm a scheme code), then refresh prices.</li>
      </ol>
      <div className="mt-3 flex flex-wrap gap-2">
        <Button variant="outline" onClick={() => apiDownload("/onboarding/template.xlsx", "investment_tracker_template.xlsx")}>
          Download the Excel template
        </Button>
        <Link className="inline-flex h-8 items-center rounded-lg border border-border px-2.5 text-sm hover:bg-muted" href="/import">Go to Import</Link>
      </div>
      <p className="mt-3 text-xs text-muted-foreground">Your data is visible only to you. This is an analytics tool, not investment advice.</p>
    </div>
  );
}
