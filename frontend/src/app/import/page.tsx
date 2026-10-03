"use client";

import Link from "next/link";
import { useState } from "react";
import { ErrorBox, Notice, PageHeader, Section } from "@/components/common";
import { Button } from "@/components/ui/button";
import { apiPost, useApi, type ImportReport, type ImportRun } from "@/lib/api";
import { formatDateTime, formatINR } from "@/lib/format";

type UploadResult = { report: ImportReport; text: string; resolution: { summary: string } | null };

export default function ImportPage() {
  const runs = useApi<ImportRun[]>("/import/runs");
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<UploadResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function upload() {
    if (!file) return;
    setBusy(true);
    setError(null);
    try {
      const fd = new FormData();
      fd.append("file", file);
      setResult(await apiPost<UploadResult>("/import", fd));
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
            <Button onClick={upload} disabled={!file || busy}>{busy ? "Importing…" : "Import"}</Button>
          </div>
          <p className="mt-3 text-xs text-muted-foreground">
            CLI alternative: <code>cd backend && .venv/bin/python -m app.import_excel ../data/your_file.xlsx</code>
          </p>
        </Section>
        {error && <ErrorBox message={error} />}
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
