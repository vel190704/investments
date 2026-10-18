"use client";

import { useSyncExternalStore } from "react";
import { Button } from "@/components/ui/button";
import { DOWN_MESSAGE, WAKING_MESSAGE, connection } from "@/lib/wake";

/** "The server is waking up" while the API is slow or unreachable (cold start), with a retry; never raw errors. */
export function ServerStatus() {
  const state = useSyncExternalStore(connection.subscribe, connection.get, () => "ok" as const);
  if (state === "ok") return null;
  const down = state === "down";
  return (
    <div role="status" aria-live="polite"
         className="fixed inset-x-0 top-0 z-50 flex flex-wrap items-center justify-center gap-3 border-b border-border bg-background px-4 py-2 text-sm">
      <span>{down ? DOWN_MESSAGE : `${WAKING_MESSAGE} Retrying automatically…`}</span>
      <Button size="sm" variant="outline"
              onClick={() => { if (!connection.retryNow()) window.location.reload(); }}>
        {down ? "Retry" : "Retry now"}
      </Button>
    </div>
  );
}
