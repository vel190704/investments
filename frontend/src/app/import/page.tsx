"use client";

import Link from "next/link";
import { useState } from "react";
import { ErrorBox, Notice, PageHeader, Section } from "@/components/common";
import { Button } from "@/components/ui/button";
import { apiPost, useApi, type ImportReport, type ImportRun } from "@/lib/api";
import { formatDateTime, formatINR } from "@/lib/format";

type UploadResult = { report: ImportReport; text: string; resolution: { summary: string } | null };
type PreviewResult = { token: string; file_name: string; report: ImportReport & { transactions: ImportReport["transactions"] & {
  added_rows: { row: number; date: string; type: string; name: string; quantity: string | null; amount_paise: number }[];
  removed_rows: { id: number; date: string; type: string; name: string; quantity: string | null; amount_paise: number; source_row: number | null }[];
} } };

export default function ImportPage() {
  const runs = useApi<ImportRun[]>("/import/runs");
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<UploadResult | null>(null);
  const [preview, setPreview] = useState<PreviewResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function upload() {
    if (!file) return;
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const fd = new FormData();
      fd.append("file", file);
      setPreview(await apiPost<PreviewResult>("/import/preview", fd));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }
  async function confirm() {
    if (!preview) return;
    setBusy(true);
    try {
      setResult(await apiPost<UploadResult>("/import/confirm", { token: preview.token }));
      setPreview(null);
      void runs.reload();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <PageHeader
        title="Import workbook"
        subtitle="The Excel file is the source of truth. Re-importing is safe: unchanged rows are recognised, not duplicated."
      />
      <div className="flex flex-col gap-4">
        <Section title="Upload .xlsx">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
            <input
              type="file"
              accept=".xlsx"
              aria-label="Workbook file"
              className="text-sm file:mr-3 file:rounded-md file:border file:border-border file:bg-muted file:px-3 file:py-1.5 file:text-sm file:text-foreground"
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            />
            <Button onClick={upload} disabled={!file || busy}>{busy && !preview ? "Checking…" : "Preview"}</Button>
          </div>
          <p className="mt-3 text-xs text-muted-foreground">
            Nothing is saved until you confirm the preview. CLI: <code>make import FILE=…</code> (add <code>--dry-run</code> via
            <code> .venv/bin/python -m app.import_excel FILE --dry-run</code> to preview).
          </p>
        </Section>
        {error && <ErrorBox message={error} />}
        {preview && <Preview p={preview} busy={busy} onConfirm={confirm} onCancel={() => setPreview(null)} />}
        {result && <Report r={result.report} resolution={result.resolution?.summary} />}

        <Section title="Import history">
          {runs.data?.length ? (
            <table className="tnum w-full text-sm">
              <thead className="text-xs text-muted-foreground">
                <tr>
                  <th className="py-1 text-left font-normal">When</th>
                  <th className="py-1 text-left font-normal">File</th>
                  <th className="py-1 text-right font-normal">Loaded</th>
                  <th className="py-1 text-right font-normal">Skipped</th>
                  <th className="py-1 text-right font-normal">Errors</th>
                  <th className="py-1 text-right font-normal">Result</th>
                </tr>
              </thead>
              <tbody>
                {runs.data.map((r) => (
                  <tr key={r.id} className="border-t border-border">
                    <td className="py-1.5 pr-2 whitespace-nowrap">{formatDateTime(r.started_at)}</td>
                    <td className="py-1.5 pr-2 break-all">{r.file_name}</td>
                    <td className="py-1.5 text-right">{r.rows_loaded}</td>
                    <td className="py-1.5 text-right">{r.rows_skipped}</td>
                    <td className="py-1.5 text-right">{r.rows_errors}</td>
                    <td className="py-1.5 text-right">{r.ok ? "OK" : "Errors"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : <p className="text-sm text-muted-foreground">No imports yet.</p>}
        </Section>
      </div>
    </>
  );
}

function Report({ r, resolution }: { r: ImportReport; resolution?: string }) {
  if (r.fatal.length) {
    return <ErrorBox message={`Nothing imported: ${r.fatal.join("; ")}`} />;
  }
  const t = r.transactions;
  return (
    <Section title={`Import report — ${r.file}`} aside={r.ok ? "OK" : "Completed with errors"}>
      <div className="flex flex-col gap-3 text-sm">
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
          <Count label="Rows loaded" value={t.loaded} sub={Object.entries(t.by_asset_type).map(([k, v]) => `${k} ${v}`).join(" · ")} />
          <Count label="New / unchanged" value={`${t.inserted} / ${t.unchanged}`} sub={t.updated_notes ? `notes updated: ${t.updated_notes}` : undefined} />
          <Count label="Skipped" value={t.skipped.length} />
          <Count label="Errors" value={t.errors.length} />
        </div>
        <p className="text-xs text-muted-foreground">Pruning: {t.pruning}. In-app entries are never removed by an import.</p>
        {t.matched_ui?.length > 0 && (
          <p className="text-xs text-muted-foreground">
            {t.matched_ui.length} row(s) already present as in-app entries (rows {t.matched_ui.map((m) => m.row).join(", ")}): kept once, not duplicated.
          </p>
        )}
        {t.skipped.map((s) => <p key={`s${s.row}`} className="text-xs">Skipped row {s.row}: {s.reason}</p>)}
        {t.errors.map((e, i) => (
          <p key={`e${i}`} className="text-xs text-destructive">Error row {e.row}{e.field ? ` [${e.field}]` : ""}: {e.message}</p>
        ))}
        {t.warnings.map((w, i) => <p key={`w${i}`} className="text-xs text-muted-foreground">Warning row {w.row}: {w.message}</p>)}
        <p className="text-xs text-muted-foreground">
          holdings_fallback: {r.holdings_fallback.rows} rows, used for {r.holdings_fallback.used.length} instrument(s)
          {r.holdings_fallback.used.length ? ` (${r.holdings_fallback.used.join(", ")})` : ""}, ignored{" "}
          {r.holdings_fallback.ignored} (instrument has transactions).
        </p>
        <p className="text-xs text-muted-foreground">
          monthly_plan: {r.monthly_plan.rows} items, {formatINR(r.monthly_plan.total_paise)}/month, allocation sum{" "}
          {r.monthly_plan.fraction_sum}. {r.monthly_plan.warnings.join(" ")}
        </p>
        {resolution && (
          <Notice>
            Identifier matching: {resolution}. Review on <Link className="underline" href="/mappings">Mappings</Link>.
          </Notice>
        )}
      </div>
    </Section>
  );
}

function Count({ label, value, sub }: { label: string; value: number | string; sub?: string }) {
  return (
    <div className="rounded-lg bg-muted/40 p-2">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="tnum text-lg font-semibold">{value}</div>
      {sub && <div className="text-xs text-muted-foreground">{sub}</div>}
    </div>
  );
}

function Preview({ p, busy, onConfirm, onCancel }: { p: PreviewResult; busy: boolean; onConfirm: () => void; onCancel: () => void }) {
  const t = p.report.transactions;
  if (p.report.fatal.length) return <ErrorBox message={`Cannot import: ${p.report.fatal.join("; ")}`} />;
  return (
    <Section title={`Preview — ${p.file_name}`} aside="Nothing has been saved yet">
      <div className="flex flex-col gap-3 text-sm">
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
          <Count label="Rows to add" value={t.added_rows.length} />
          <Count label="Rows to remove (excel only)" value={t.removed_rows.length} />
          <Count label="Already in-app entries" value={t.matched_ui.length} />
          <Count label="Rows with errors" value={t.errors.length} />
        </div>
        {t.added_rows.length > 0 && (
          <div><div className="mb-1 text-xs font-medium text-muted-foreground">To add</div>
            <ul className="tnum text-xs">{t.added_rows.map((r) => <li key={r.row}>row {r.row}: {r.date} {r.type} {r.name} {r.quantity ?? ""} · {formatINR(r.amount_paise)}</li>)}</ul></div>
        )}
        {t.removed_rows.length > 0 && (
          <div><div className="mb-1 text-xs font-medium text-status-high">To remove (no longer in the file; in-app entries are never removed)</div>
            <ul className="tnum text-xs">{t.removed_rows.map((r) => <li key={r.id}>{r.date} {r.type} {r.name} {r.quantity ?? ""} · {formatINR(r.amount_paise)} (was excel row {r.source_row})</li>)}</ul></div>
        )}
        {t.errors.length > 0 && (
          <div><div className="mb-1 text-xs font-medium text-destructive">Errors (these rows will be skipped; nothing is removed while errors exist)</div>
            <ul className="text-xs text-destructive">{t.errors.map((e, i) => <li key={i}>row {e.row}{e.field ? ` [${e.field}]` : ""}: {e.message}</li>)}</ul></div>
        )}
        {t.added_rows.length === 0 && t.removed_rows.length === 0 && t.errors.length === 0 && <Notice>No changes: the database already matches this file.</Notice>}
        <div className="flex gap-2">
          <Button onClick={onConfirm} disabled={busy}>{busy ? "Applying…" : "Confirm import"}</Button>
          <Button variant="ghost" onClick={onCancel}>Cancel</Button>
        </div>
      </div>
    </Section>
  );
}
