"use client";

import { useState } from "react";

export function RequestId({ id }: { id: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <span className="inline-flex items-center gap-1">
      request <code className="rounded bg-background/40 px-1">{id}</code>
      <button type="button" className="underline" aria-label="Copy request id"
              onClick={async () => {
                try { await navigator.clipboard.writeText(id); setCopied(true); setTimeout(() => setCopied(false), 1500); }
                catch { /* clipboard unavailable */ }
              }}>
        {copied ? "copied" : "copy"}
      </button>
      <span className="opacity-70">(find it in logs/app.log: rid={id})</span>
    </span>
  );
}
