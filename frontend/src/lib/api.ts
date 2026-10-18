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
  drift: Drift;
  not_held: { asset_class: string; text: string }[];
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
    matched_ui: { row: number; message: string }[];
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
  lookthrough: null | {
    companies: { isin: string; name: string; before: string; after: string }[];
    sectors: { name: string; before: string; after: string }[];
    funds_without_disclosure: string[];
  };
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

// ---- Phase 2 types ----
export type Txn = {
  id: number; date: string; type: string; instrument_id: number; name: string; symbol: string | null;
  asset_type: string; quantity: string | null; price: string | null; amount_paise: number; charges_paise: number;
  platform: string | null; notes: string | null; source: "excel" | "ui"; source_row: number | null;
};
export type InstrumentRef = {
  instrument_id: number; name: string; symbol: string | null; asset_type: string; platform: string | null;
  scheme_code: string | null;
};
export type SeriesPoint = {
  date: string; value_paise: number | null; invested_paise: number | null; invested_priced_paise: number | null;
  partial: boolean; unpriced: string[]; gap?: boolean; reason?: string;
};
export type Series = { points: SeriesPoint[]; enough_history: boolean; note: string | null; gaps?: string[] };
export type Snapshot = {
  snapshot_date: string; total_value_paise: number; total_invested_paise: number; invested_priced_paise: number;
  partial: boolean; unpriced: string[]; trigger: string; updated_at: string;
  asset_classes: { asset_class: string; value_paise: number; invested_paise: number }[];
};
export type Change = {
  id: number; occurred_at: string; kind: string; cause: string; instrument_id: number | null;
  snapshot_date: string | null; summary: string; details: Record<string, unknown>;
};
export type CompareRow = {
  instrument_id: number; name: string; asset_class: string; status: "added" | "removed" | "changed" | "unchanged";
  quantity_a: string; quantity_b: string; avg_cost_a: string | null; avg_cost_b: string | null;
  value_a_paise: number | null; value_b_paise: number | null; weight_a: string | null; weight_b: string | null;
  value_change_paise: number | null;
};
export type Compare = {
  a: string; b: string; label_a: string; label_b: string; total_a_paise: number; total_b_paise: number;
  total_change_paise: number; instruments: CompareRow[];
  asset_classes: { asset_class: string; value_a_paise: number; value_b_paise: number; weight_a: string | null;
                   weight_b: string | null; value_change_paise: number }[];
};
export type XirrFull = Xirr & { flows: number };
export type XirrReport = {
  valuation_date: string; method: string; portfolio: XirrFull;
  asset_classes: (XirrFull & { asset_class: string })[];
  instruments: (XirrFull & { instrument_id: number; name: string; short_name: string; asset_class: string; open: boolean })[];
};
export type DriftRow = {
  asset_class: string; value_paise: number; current: string; target: string; deviation_pp: string;
  value_vs_target_paise: number; status: "OVERWEIGHT" | "UNDERWEIGHT" | "WITHIN BAND"; held: boolean;
  reason: string; calculation: string;
};
export type Drift = { targets_set: boolean; tolerance_pp: string; rows: DriftRow[]; message: string | null; basis?: string };
export type SettingsSection<T> = { value: T; is_set: boolean; default: T };
export type ProjectionCfg = {
  conservative: string; base: string; higher: string; default_years: number; default_step_up: string; reviewed: boolean;
};
export type EmergencyCfg = { monthly_expenses_paise: number; balance_paise: number; target_months: number };
export type Settings = {
  target_classes: string[];
  sections: {
    targets: SettingsSection<Record<string, string> | null>;
    drift: SettingsSection<{ tolerance_pp: string }>;
    concentration: SettingsSection<Record<string, { low: string; high: string }>>;
    projection: SettingsSection<ProjectionCfg>;
    emergency_fund: SettingsSection<EmergencyCfg | null>;
    sector_ranges: SettingsSection<Record<string, { min: string; max: string }> | null>;
    themes: SettingsSection<Record<string, string[]> | null>;
    health: SettingsSection<Record<string, Record<string, string>>>;
    llm: SettingsSection<{ outbound_enabled: boolean; model: string | null; monthly_call_cap: number; weekly_job: boolean;
                           price_in_per_mtok: string | null; price_out_per_mtok: string | null; effort: string;
                           refusal_fallback: boolean }>;
    rubric: SettingsSection<{ pe_vs_peer_tolerance_pct: string; peg_max: string; roe_min_pct: string; de_max: string;
                              fcf_positive: boolean; fcf_not_declining: boolean }>;
    sector_rules: SettingsSection<Record<string, string[]>>;
    news: SettingsSection<{ feeds: { name: string; url: string }[] }>;
    alerts: SettingsSection<{ announcement: boolean; announcement_categories: string[]; concentration_change: boolean;
                              disclosure_stale: boolean; review_due: boolean }>;
  };
};
export type PlanLineOut = {
  label: string; asset_class: string; instrument_id: number | null; amount_paise: number; invested_paise: number;
  uninvested_paise: number; units: string | null; whole_units_only: boolean; unit_price: string | null; note?: string;
};
export type Consideration = { kind: string; level?: string; title: string; text: string; calculation: string };
export type PlannerMode = {
  mode: "plan" | "targets"; label: string; available: boolean; reason?: string; budget_paise?: number;
  invested_paise?: number; uninvested_paise?: number; total_before_paise?: number; total_after_paise?: number;
  lines?: PlanLineOut[];
  asset_classes?: { asset_class: string; held: boolean; current_paise: number; add_paise: number;
                    projected_paise: number; current: string; projected: string; target: string | null }[];
  mutual_funds?: { instrument_id: number; name: string; category: string; add_paise: number; current: string; projected: string }[];
  considerations?: Consideration[];
};
export type Planner = {
  budget_paise: number; default_budget_paise: number; budget_source: string; presets_rupees: number[];
  assumptions: string[]; excluded: { name: string; reason: string }[]; targets_set: boolean; picks: number[];
  pickable: { instrument_id: number; short_name: string; name: string; asset_class: string; price: string }[];
  modes: PlannerMode[];
};
export type ProjectionScenario = {
  name: string; annual_return_pct: string; years: number; step_up_pct: string; start_paise: number; monthly_paise: number;
  monthly_rate: string; total_contributions_paise: number; growth_paise: number; ending_value_paise: number;
  growth_share_of_end: string | null; sentence: string;
  yearly: { year: number; value_paise: number; contributions_paise: number; start_paise: number }[];
};
export type Projection = {
  inputs: { start_paise: number; monthly_paise: number; years: number; step_up_pct: string };
  defaults: { start_paise: number; start_source: string; start_excludes: string[]; monthly_paise: number;
              monthly_source: string; years: number; step_up_pct: string };
  rates_reviewed: boolean; rates_note: string | null; formula: string; closed_form_check_paise: number | null;
  assumptions: string[]; scenarios: ProjectionScenario[];
};
export type EmergencyFund = {
  is_set: boolean; note: string;
  status: null | { target_paise: number; balance_paise: number; remaining_paise: number; percent_complete: string | null;
                   months_covered: string | null; target_months: number; monthly_expenses_paise: number; complete: boolean };
};

// ---- Phase 3 types ----
export type Level = "LOW" | "MODERATE" | "HIGH";
export type SectorRow = {
  sector: string; value_paise: number; pct: string; count: number; origins: string[];
  contributors: { name: string; value_paise: number; pct: string }[];
};
export type SectorFlag = { key: string; title: string; level: Level; value: string; reason: string; calculation: string; thresholds: string };
export type SectorsPage = {
  total_value_paise: number; sectors: SectorRow[]; basis: string;
  metrics: { equity_value_paise: number; sectors: number; largest: { sector: string; share: string } | null; hhi: string | null; flags: SectorFlag[] };
  ranges: { sector: string; current: string; min: string; max: string; status: string; reason: string }[];
  geography: { india_paise: number; india_pct: string; international_paise: number; international_pct: string;
               regions: { region: string; value_paise: number; pct: string }[] };
  themes: { tag: string; value_paise: number; pct: string; members: { isin: string; name: string; total_paise: number }[]; missing: string[] }[];
  direct: { instrument_id: number; name: string; asset_type: string; sector: string; origin: string | null; manual: boolean;
            source: string | null; as_of: string | null; value_paise: number }[];
  funds_looked_through: { name: string; label: string }[]; funds_not_looked_through: string[];
};
export type ClassificationRow = {
  instrument_id: number; name: string; symbol: string | null; asset_type: string; asset_class: string;
  asset_class_override: string | null; etf_underlying: string | null; etf_underlying_key: string | null; region: string | null;
  sector: string; sector_origin: string | null; sector_manual: boolean; sector_source: string | null; sector_as_of: string | null;
};
export type Classification = { asset_classes: string[]; instruments: ClassificationRow[] };
export type FactCell = {
  metric: string; label: string; unit: "inr" | "ratio" | "fraction" | "text"; manual_allowed: boolean;
  value: string | null; text: string | null; display_na: string | null; origin: string | null; manual?: boolean;
  source?: string | null; as_of?: string | null; fetched_at?: string | null; note?: string | null; derivation?: string | null;
  portfolio_sector_median?: string | null;
};
export type Fundamentals = {
  stocks: { instrument_id: number; symbol: string; name: string; sector: string; price: string | null;
            price_source: string | null; price_date: string | null; metrics: FactCell[] }[];
  funds: { instrument_id: number; name: string; scheme_code: string | null; is_index_fund: boolean; metrics: FactCell[] }[];
  metric_defs: { key: string; label: string; unit: string; applies_to: string; manual: boolean; auto: boolean; note: string; bounds: (string | null)[] }[];
  notes: string[];
};
export type DisclosureItem = {
  id: number; instrument_id: number; fund: string; kind: string; as_of: string; index_name: string | null; parser: string;
  source_file: string; uploaded_at: string; rows: number; equity_weight: string; label: string; in_use: boolean; stale: boolean;
};
export type CompanyExposure = {
  isin: string; name: string; direct_paise: number; indirect_paise: number; total_paise: number;
  direct_pct: string | null; indirect_pct: string | null; total_pct: string | null;
  via: { instrument_id: number; fund: string; paise: number; pct: string | null }[];
  level: Level | null; reason: string | null; calculation: string | null;
};
export type Lookthrough = {
  companies: CompanyExposure[]; unmatched_direct: { instrument_id: number; name: string; reason: string }[];
  not_looked_through: { instrument_id: number; name: string; value_paise: number }[];
  coverage: { instrument_id: number; name: string; label: string; as_of: string; equity_weight: string }[];
  thresholds: { low: string; high: string; rule: string }; stale: { fund: string; as_of: string; warning: string }[];
  total_value_paise: number; basis: string;
};
export type OverlapPair = {
  fund_a: string; fund_b: string; overlap: string; common_count: number; labels: (string | null)[];
  common: { isin: string; name: string; weight_a: string; weight_b: string; min: string }[];
};
export type Overlap = { pairs: OverlapPair[]; not_looked_through: string[]; basis: string };
export type HealthDim = {
  key: string; title: string; level: Level | null; value: string | null; reason: string; calculation: string | null;
  thresholds: string | null; available: boolean; info_only: boolean;
};
export type Health = { valuation_date: string; dimensions: HealthDim[]; stale: { warning: string }[]; not_looked_through: string[]; note: string };

// ---- Phase 4 types ----
export type NewsItem = {
  id: number; isin: string; company: string; instrument_id: number | null; title: string; source: string;
  source_kind: "EXCHANGE" | "NEWS"; url: string; published_at: string; fetched_at: string; category: string;
  category_origin: "RULE" | "MODEL"; summary: string | null; exposure: number; via_funds: string[];
};
export type NewsFeed = {
  items: NewsItem[]; categories: string[]; basis: string;
  companies: { isin: string; name: string; symbol: string | null; exposure: number; direct: boolean; via_funds: string[];
               unavailable: { source: string; message: string }[] }[];
  untracked: { instrument_id: number; name: string; reason: string }[];
  funds: { fund: string; companies: string[]; note: string }[];
  sources: { source: string; ok: boolean; message: string; checked_at: string; items_fetched: number | null; items_matched: number | null }[];
  empty: { kind: "FILTERED" | "NOT_FETCHED" | "SOURCES_FAILED" | "NO_TRACKED_HOLDINGS" | "NO_ITEMS" | "NO_MATCHES"; message: string;
           failed: { source: string; message: string }[] } | null;
};
export type MacroRow = {
  key: string; label: string; unit: string; origin: "AUTO" | "MANUAL"; value: string | null; display: string;
  source: string | null; as_of: string | null; fetched_at: string | null; note: string | null; manual: boolean;
};
export type MacroPage = {
  snapshot: MacroRow[]; tags: string[]; starter_label: string; basis: string;
  table: { sector: string; tags: string[]; origin: string | null; note: string | null; held_pct: string }[];
  scenarios: { scenario: string; label: string;
               tags: { tag: string; weight: string; weight_text: string; sectors: { sector: string; pct: string }[]; holdings: string[] }[] }[];
};
export type Statement = { text: string; citations: string[] };
export type AnalysisCard = {
  id: number; kind: "stock" | "fund" | "portfolio"; status: "OK" | "FAILED"; model: string; requested_model: string | null;
  fallback_used: boolean; prompt_version: string; created_at: string; data_as_of: string | null;
  attempts: number; input_tokens: number; output_tokens: number; stale: boolean; errors: string[];
  analysis?: Record<string, Statement[]> & {
    scenarios?: { scenario: string; direction: string; because: string; citations: string[]; sentence: string }[];
  };
};
export type LlmUsage = { calls_this_month: number; cap: number; input_tokens: number; output_tokens: number;
                         estimated_cost_usd: string | null; pricing_note: string };
export type AnalysisHolding = { instrument_id: number; symbol: string | null; name: string; card: AnalysisCard | null };
export type AnalysisPage = {
  holdings: AnalysisHolding[]; funds: AnalysisHolding[]; portfolio: { card: AnalysisCard | null };
  gate: string | null; usage: LlmUsage; funds_note: string;
  settings: { outbound_enabled: boolean; model: string; effort: string; monthly_call_cap: number; weekly_job: boolean;
              refusal_fallback: boolean };
};
export type ThesisEntry = {
  id: number; instrument_id: number; version: number; why: string; change_view: string; horizon: string;
  review_date: string | null; review_due: boolean; created_at: string; linked_txn_ids: number[]; linked_change_ids: number[];
};
export type JournalPage = {
  holdings: { instrument_id: number; name: string; symbol: string | null; asset_type: string; latest: ThesisEntry | null;
              versions: number; send_to_llm: boolean; transactions: { id: number; date: string; type: string; source: string }[] }[];
  review_due: (ThesisEntry & { name: string })[]; note: string;
};
export type AlertItem = { id: number; rule: string; title: string; detail: string; instrument_id: number | null; created_at: string; read: boolean };

// ---- Phase 5 types ----
export type FrameworkCheck = { key: string; title: string; status: string; value: string | null; display: string | null; rule: string; reason: string; sources: (string | null)[] };
export type PeerComparison = {
  metric: string; mine: string | null; peer_median: string | null; median_note: string | null;
  peers: { symbol: string; value: string | null; status: string; note: string | null; as_of: string | null }[];
};
export type HistoryRow = {
  fiscal_year_end: string; roe: string | null; net_margin: string | null; fcf: string | null; fcf_margin: string | null;
  eps: string | null; pe: { value: string | null; reason: string | null; price_date?: string; price?: string; eps?: string };
};
export type StockValuation = {
  instrument_id: number; symbol: string; name: string; sector: string;
  metrics: Record<string, { value: string | null; source: string | null; as_of: string | null; reason: string | null; note?: string | null }>;
  framework: FrameworkCheck[]; peers: { symbols: string[]; note: string | null; label: string; comparisons: PeerComparison[] };
  history: HistoryRow[]; own_hist_pe_median: string | null; notes: string[];
};
export type ValuationPage = { stocks: StockValuation[]; rubric: Record<string, string | boolean>; sector_rules: Record<string, string[]> };
export type MonthlyUpdate = {
  month: string; from: string; to: string; done: number; total: number; warnings: string[];
  items: { key: string; title: string; done: boolean; detail: string }[];
  plan: { name: string; monthly_amount_paise: number }[]; how_to: string[];
};
export type SourceHealth = { sources: { source: string; last_success: string | null; last_failure: string | null; last_error: string | null;
  last_message: string | null; history: { date: string; status: "ok" | "failed" | "mixed" | "none"; events: number }[] }[]; note: string };
export type QualitativeEntry = { id: number; instrument_id: number; version: number; moat_type: string; moat_note: string;
  capital_allocation_note: string; source_note: string; as_of: string; thesis_entry_id: number | null; created_at: string };

// ---- fetch helpers ----
export class ApiError extends Error {}

async function handle<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let msg = `${res.status} ${res.statusText}`;
    try {
      const body = await res.json();
      const d = body?.detail;
      if (typeof d === "string") msg = d;
      else if (d?.errors) msg = d.errors.map((e: { field?: string; message: string }) =>
        e.field ? `${e.field}: ${e.message}` : e.message).join("; ");
      else if (d) msg = JSON.stringify(d);
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

export async function apiPut<T>(path: string, body: unknown): Promise<T> {
  return handle<T>(await fetch(`/api${path}`, {
    method: "PUT", body: JSON.stringify(body), headers: { "Content-Type": "application/json" },
  }));
}

export async function apiDelete<T>(path: string): Promise<T> {
  return handle<T>(await fetch(`/api${path}`, { method: "DELETE" }));
}

export function errorText(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
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
