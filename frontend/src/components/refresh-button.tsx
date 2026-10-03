"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { apiPost, type RefreshResult } from "@/lib/api";

export function RefreshButton({ onDone }: { onDone?: () => void }) {
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  async function run() {
    setBusy(true);
    setMsg(null);
    try {
      const r = await apiPost<RefreshResult>("/market/refresh");
      const failed = r.results.filter((x) => !x.ok);
      setMsg(
        `${r.ok_count} updated` +
          (failed.length ? `, ${failed.length} unavailable: ${failed.map((f) => `${f.name} (${f.error})`).join("; ")}` : ""),
      );
      onDone?.();
    } catch (e) {
      setMsg(`Refresh failed: ${e instanceof Error ? e.message : e}`);
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="flex flex-col items-start gap-1 sm:items-end">
      <Button variant="outline" onClick={run} disabled={busy}>
        {busy ? "Refreshing prices…" : "Refresh prices"}
      </Button>
      {msg && <p className="max-w-md text-xs text-muted-foreground sm:text-right">{msg}</p>}
    </div>
  );
}
