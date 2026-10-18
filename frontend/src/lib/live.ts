"use client";

import { useCallback, useEffect, useState } from "react";
import { apiGet, apiPost, apiPut, errorText, type LiveView } from "./api";

/** Live view of intraday quotes. While Live is on, re-reads /api/live every poll interval, but only while this tab
 *  is visible (and once more when it becomes visible again). Reading /api/live is also what tells the backend that
 *  someone is watching; with no viewer it stops polling Yahoo. */
export function useLive() {
  const [data, setData] = useState<LiveView | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      setData(await apiGet<LiveView>("/live"));
      setError(null);
    } catch (e) {
      setError(errorText(e));
    }
  }, []);

  useEffect(() => {
    const first = setTimeout(load, 0);
    return () => clearTimeout(first);
  }, [load]);

  const enabled = data?.enabled ?? false;
  const everyMs = Math.max(15, data?.poll_seconds ?? 60) * 1000;
  useEffect(() => {
    if (!enabled) return;
    const visible = () => document.visibilityState === "visible";
    const timer = setInterval(() => { if (visible()) load(); }, everyMs);
    const onVisibility = () => { if (visible()) load(); };
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      clearInterval(timer);
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [enabled, everyMs, load]);

  const pollSeconds = data?.poll_seconds ?? 60;
  const setEnabled = useCallback(async (on: boolean) => {
    setBusy(true);
    try {
      await apiPut("/settings/live", { enabled: on, poll_seconds: pollSeconds });
      await load();
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  }, [pollSeconds, load]);

  const refresh = useCallback(async () => {
    setBusy(true);
    try {
      const r = await apiPost<{ cycle: { ran: boolean; reason?: string }; view: LiveView }>("/live/refresh");
      setData(r.view);
      setError(null);
      return r.cycle;
    } catch (e) {
      setError(errorText(e));
      return null;
    } finally {
      setBusy(false);
    }
  }, []);

  return { data, error, busy, load, setEnabled, refresh };
}
