"use client";

import { useState } from "react";
import { ErrorBox, Loading, Notice, PageHeader, Section } from "@/components/common";
import { Select } from "@/components/form";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { apiDelete, apiPut, errorText, useApi, type Classification, type ClassificationRow } from "@/lib/api";
import { formatDate } from "@/lib/format";

export default function ClassificationPage() {
  const { data, error, loading, reload } = useApi<Classification>("/classification");
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);

  async function put(r: ClassificationRow, body: Record<string, string>) {
    try {
      await apiPut(`/instruments/${r.instrument_id}/classification`, body);
      setMsg({ ok: true, text: `Saved for ${r.symbol ?? r.name}. Allocation, drift and sectors now use it.` });
      reload();
    } catch (e) {
      setMsg({ ok: false, text: errorText(e) });
    }
  }
  async function clear(r: ClassificationRow, field: string) {
    await apiDelete(`/instruments/${r.instrument_id}/classification/${field}`);
    reload();
  }

  return (
    <>
      <PageHeader
        title="Classification"
        subtitle="Overrides win over official lists and are marked manual. Use this to move, for example, a gold or debt ETF out of Indian stocks, or to set a sector NSE does not list."
      />
      {msg && (msg.ok ? <Notice>{msg.text}</Notice> : <ErrorBox message={msg.text} />)}
      {error && <ErrorBox message={error} />}
      {loading && !data && <Loading />}
      {data && (
        <Section title="Instruments" aside="ETFs are classified by what they hold (NSE ETF list), not by name">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="text-xs text-muted-foreground">
                <tr>
                  <th className="py-1 pr-3 text-left font-normal">Instrument</th>
                  <th className="py-1 pr-3 text-left font-normal">Asset class</th>
                  <th className="py-1 pr-3 text-left font-normal">Sector</th>
                  <th className="py-1 text-left font-normal">Region</th>
                </tr>
              </thead>
              <tbody>
                {data.instruments.map((r) => <Row key={r.instrument_id} r={r} classes={data.asset_classes} put={put} clear={clear} />)}
              </tbody>
            </table>
          </div>
        </Section>
      )}
    </>
  );
}

function Row({ r, classes, put, clear }: {
  r: ClassificationRow; classes: string[]; put: (r: ClassificationRow, b: Record<string, string>) => void;
  clear: (r: ClassificationRow, f: string) => void;
}) {
  const [sector, setSector] = useState("");
  const [region, setRegion] = useState("");
  return (
    <tr className="border-t border-border align-top">
      <td className="py-2 pr-3">
        <div className="font-medium">{r.symbol ?? r.name}</div>
        <div className="text-xs text-muted-foreground">
          {r.asset_type}{r.etf_underlying ? ` · NSE: ${r.etf_underlying} / ${r.etf_underlying_key}` : ""}
        </div>
      </td>
      <td className="py-2 pr-3">
        <Select aria-label="Asset class" value={r.asset_class_override ?? ""}
                onChange={(e) => e.target.value ? put(r, { asset_class: e.target.value }) : clear(r, "asset_class")}>
          <option value="">Automatic ({r.asset_class_override ? "clear override" : r.asset_class})</option>
          {classes.map((c) => <option key={c} value={c}>{c}</option>)}
        </Select>
        {r.asset_class_override && <div className="mt-0.5 text-xs text-series-1">manual</div>}
      </td>
      <td className="py-2 pr-3">
        {r.asset_type === "MF" ? <span className="text-xs text-muted-foreground">Funds: sectors come from their holdings (look-through)</span> : (
          <>
            <div>{r.sector}{r.sector_manual && <span className="ml-1 text-xs text-series-1">manual</span>}</div>
            <div className="text-xs text-muted-foreground">{r.sector_source ?? "no official classification"}{r.sector_as_of ? ` · ${formatDate(r.sector_as_of)}` : ""}</div>
            <form className="mt-1 flex gap-1" onSubmit={(e) => { e.preventDefault(); if (sector.trim()) { put(r, { sector }); setSector(""); } }}>
              <Input className="h-7 w-44" placeholder="Override sector" value={sector} onChange={(e) => setSector(e.target.value)} />
              <Button size="sm" variant="outline" type="submit" disabled={!sector.trim()}>Set</Button>
              {r.sector_origin === "MANUAL" && <Button size="sm" variant="ghost" type="button" onClick={() => clear(r, "sector")}>Clear</Button>}
            </form>
          </>
        )}
      </td>
      <td className="py-2">
        {r.asset_type === "ETF" ? (
          <>
            <div>{r.region ?? "—"}</div>
            <form className="mt-1 flex gap-1" onSubmit={(e) => { e.preventDefault(); if (region.trim()) { put(r, { region }); setRegion(""); } }}>
              <Input className="h-7 w-40" placeholder="Override region" value={region} onChange={(e) => setRegion(e.target.value)} />
              <Button size="sm" variant="outline" type="submit" disabled={!region.trim()}>Set</Button>
            </form>
          </>
        ) : <span className="text-xs text-muted-foreground">{r.asset_type === "STOCK" ? "India" : "—"}</span>}
      </td>
    </tr>
  );
}
