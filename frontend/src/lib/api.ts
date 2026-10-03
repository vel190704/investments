"use client";

import { useCallback, useEffect, useState } from "react";

// ---- types (money: integer paise; decimals: strings) ----
export type Xirr = { rate: string | null; note: string | null };
export type AsOf = { source: string; price_dates: string[]; fetched_at: string };
export type AssetClass = { name: string; value_paise: number; weight: string; display_pct: string };
export type Flag = {
  key: string; title: string; level: "LOW" | "MODERATE" | "HIGH"; value: string;
  reason: string; calculation: string; thresholds: string;
};
export type Threshold = { key: string; label: string; low: string; high: string; unit: string; explanation: string };
export type PlanItem = {
  name: string; platform: string | null; asset_type: string; monthly_amount_paise: number;
  allocation_fraction: string; instrument_id: number | null; is_bucket: boolean;
};
export type Plan = { monthly_total_paise: number; items: PlanItem[]; source: string };

export type Summary = {
  valuation_date: string; has_data: boolean;
  total_value_paise: number; total_invested_paise: number; invested_in_priced_paise: number;
  pnl_paise: number; pnl_pct: string | null;
  excluded_unpriced: { name: string; invested_paise: number; reason: string }[];
  realised_paise: number; dividends_paise: number;
  today_change: {
    paise: number | null; pct: string | null; covered: string[];
    not_covered: { name: string; reason: string }[];
  };
  monthly_plan: Plan;
  asset_classes: AssetClass[];
  top_holdings: { instrument_id: number; name: string; short_name: string; asset_class: string;
                  value_paise: number; weight: string }[];
  concentration_flags: Flag[];
  xirr: Xirr;
  data_as_of: AsOf[];
};

export type Holding = {
  instrument_id: number; name: string; short_name: string; symbol: string | null;
  asset_type: "STOCK" | "ETF" | "MF"; asset_class: string; category: string | null; exposure: string;
  platform: string | null; isin: string | null; scheme_code: string | null;
  quantity: string; avg_cost: string | null; price: string | null; previous_close: string | null;
  price_date: string | null; previous_date: string | null; price_source: string | null;
  price_source_ref: string | null; price_fetched_at: string | null; unavailable_reason: string | null;
  invested_paise: number; value_paise: number | null; pnl_paise: number | null; pnl_pct: string | null;
  day_change_paise: number | null; weight: string | null; realised_paise: number; dividends_paise: number;
  opening_only: boolean; xirr: Xirr;
};
export type Holdings = { total_value_paise: number; valuation_date: string; equity: Holding[]; mutual_funds: Holding[] };

export type Allocation = {
  total_value_paise: number; basis: string; asset_classes: AssetClass[];
  instruments: { instrument_id: number; name: string; short_name: string; asset_class: string;
                 value_paise: number; weight: string; display_pct: string }[];
  excluded_unpriced: { name: string; reason: string }[];
  concentration: {
    scope: string; direct_equity_value_paise: number; total_portfolio_value_paise: number;
    companies: { name: string; value_paise: number; share_of_direct_equity: string; share_of_portfolio: string | null }[];
    largest: unknown; top3_share_of_direct_equity: string | null; hhi: string | null;
    flags: Flag[]; thresholds: Threshold[];
  };
  data_as_of: AsOf[];
};

export type Candidate = {
  id: number; kind: "ISIN" | "SCHEME_CODE"; value: string; label: string; source: string; score: number;
  status: "PENDING" | "CONFIRMED" | "REJECTED"; details: Record<string, string | boolean | null>;
  decided_at: string | null;
};
export type MappingRow = {
  instrument_id: number; name: string; symbol: string | null; asset_type: string; exposure: string;
  isin: string | null; scheme_code: string | null; needed_kind: string;
  status: "CONFIRMED" | "PENDING" | "NO_CANDIDATES"; candidates: Candidate[];
};
export type Mappings = { instruments: MappingRow[]; pending: number };

export type ImportReport = {
  file: string; ok: boolean; fatal: string[];
  transactions: {
    rows_in_sheet: number; loaded: number; inserted: number; unchanged: number; updated_notes: number;
    removed: number; pruning: string; skipped: { row: number; reason: string }[];
    errors: { row: number; field: string | null; message: string }[];
    warnings: { row: number; message: string }[]; by_asset_type: Record<string, number>;
  };
  holdings_fallback: { rows: number; used: string[]; ignored: number; errors: { row: number; message: string }[] };
  monthly_plan: { rows: number; total_paise: number; fraction_sum: string; warnings: string[];
                  errors: { row: number; message: string }[] };
  instruments: { created: string[]; existing: number };
};
export type ImportRun = {
  id: number; started_at: string; file_name: string; ok: boolean;
  rows_loaded: number; rows_skipped: number; rows_errors: number; report: ImportReport;
};

export type SimPair = { name: string; before: string; after: string };
export type SimScenario = {
  key: string; label: string; amount_paise: number; invested_paise: number; uninvested_paise: number;
  legs: { instrument_id: number; name: string; amount_paise: number; units: string; invested_paise: number;
          uninvested_paise: number; unit_price: string; whole_units_only: boolean }[];
  total_before_paise: number; total_after_paise: number;
  asset_classes: SimPair[];
  mf_split: (SimPair & { instrument_id: number; category: string })[];
  top_companies: (SimPair & { instrument_id: number })[];
  sentences: string[];
};
export type SimResult = {
  amount_paise: number; assumptions: string[];
  before: { total_paise: number; asset_classes: { name: string; weight: string }[]; mf_total_share: string };
  scenarios: SimScenario[]; excluded: { name: string; reason: string }[];
};
export type SimOptions = {
  presets_rupees: number[]; assumptions: string[];
  default_scenarios: { key: string; label: string }[];
  instruments: { instrument_id: number; name: string; short_name: string; asset_type: string; price: string }[];
  excluded: { name: string; reason: string }[];
};
export type RefreshResult = {
  id: number; ok_count: number; error_count: number; finished_at: string;
  results: { instrument_id: number; name: string; ok: boolean; source: string; error?: string;
             price?: string; price_date?: string }[];
};

// ---- fetch helpers ----
export class ApiError extends Error {}

async function handle<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let msg = `${res.status} ${res.statusText}`;
    try {
      const body = await res.json();
      if (body?.detail) msg = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch { /* not JSON */ }
    throw new ApiError(msg);
  }
  return res.json() as Promise<T>;
}

export async function apiGet<T>(path: string): Promise<T> {
  return handle<T>(await fetch(`/api${path}`, { cache: "no-store" }));
}

export async function apiPost<T>(path: string, body?: unknown): Promise<T> {
  const init: RequestInit = { method: "POST" };
  if (body instanceof FormData) init.body = body;
  else if (body !== undefined) {
    init.body = JSON.stringify(body);
    init.headers = { "Content-Type": "application/json" };
  }
  return handle<T>(await fetch(`/api${path}`, init));
}

export function useApi<T>(path: string) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [version, setVersion] = useState(0);
  useEffect(() => {
    let cancelled = false;
    apiGet<T>(path).then(
      (d) => { if (!cancelled) { setData(d); setError(null); setLoading(false); } },
      (e) => { if (!cancelled) { setError(e instanceof Error ? e.message : String(e)); setLoading(false); } },
    );
    return () => { cancelled = true; };
  }, [path, version]);
  const reload = useCallback(() => {
    setLoading(true);
    setVersion((v) => v + 1);
  }, []);
  return { data, error, loading, reload };
}
