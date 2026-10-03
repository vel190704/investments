"use client";

import { EmptyState, ErrorBox, Loading, Notice, PageHeader } from "@/components/common";
import { RefreshButton } from "@/components/refresh-button";
import { Table, TableBody, TableCell, TableFooter, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useApi, type Holding, type Holdings } from "@/lib/api";
import { formatDate, formatDateTime, formatINR, formatPct, formatPrice, formatQty, signClass } from "@/lib/format";

export function HoldingsPage({ kind }: { kind: "equity" | "funds" }) {
  const { data, error, loading, reload } = useApi<Holdings>("/holdings");
  const rows = data ? (kind === "equity" ? data.equity : data.mutual_funds) : [];
  const isMF = kind === "funds";
  const priced = rows.filter((r) => r.value_paise !== null);
  const invested = rows.reduce((a, r) => a + r.invested_paise, 0);
  const investedPriced = priced.reduce((a, r) => a + r.invested_paise, 0);
  const value = priced.reduce((a, r) => a + (r.value_paise ?? 0), 0);
  const weight = priced.reduce((a, r) => a + Number(r.weight ?? 0), 0);

  return (
    <>
      <PageHeader
        title={isMF ? "Mutual funds" : "Stocks & ETFs"}
        subtitle={
          isMF
            ? "NAVs from AMFI NAVAll.txt (needs a confirmed scheme code). Weight = share of total portfolio value."
            : "Prices from Yahoo Finance (yfinance, NSE tickers). Weight = share of total portfolio value."
        }
        actions={<RefreshButton onDone={reload} />}
      />
      {error && <ErrorBox message={error} />}
      {loading && !data && <Loading />}
      {data && !data.equity.length && !data.mutual_funds.length && <EmptyState />}
      {data && rows.length > 0 && (
        <div className="flex flex-col gap-3">
          {rows.some((r) => r.opening_only) && (
            <Notice>
              Rows marked “opening” come from OPENING balances: they count toward quantity, invested amount, value and
              P&L, but XIRR needs dated BUY/SIP rows.
            </Notice>
          )}
          <div className="rounded-xl ring-1 ring-foreground/10">
            <Table className="tnum">
              <TableHeader>
                <TableRow>
                  <TableHead>{isMF ? "Fund" : "Instrument"}</TableHead>
                  <TableHead className="text-right">{isMF ? "Units" : "Qty"}</TableHead>
                  <TableHead className="text-right">Avg cost</TableHead>
                  <TableHead className="text-right">{isMF ? "NAV" : "Price"}</TableHead>
                  <TableHead className="text-right">Invested</TableHead>
                  <TableHead className="text-right">Current value</TableHead>
                  <TableHead className="text-right">P&L</TableHead>
                  {!isMF && <TableHead className="text-right">Today</TableHead>}
                  <TableHead className="text-right">Weight</TableHead>
                  <TableHead className="text-right">XIRR</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {rows.map((h) => <Row key={h.instrument_id} h={h} isMF={isMF} />)}
              </TableBody>
              <TableFooter>
                <TableRow>
                  <TableCell className="font-medium">Total ({rows.length})</TableCell>
                  <TableCell /><TableCell /><TableCell />
                  <TableCell className="text-right">{formatINR(invested)}</TableCell>
                  <TableCell className="text-right">{priced.length ? formatINR(value) : "Data unavailable"}</TableCell>
                  <TableCell className={`text-right ${signClass(value - investedPriced)}`}>
                    {priced.length ? formatINR(value - investedPriced, { signed: true }) : "—"}
                  </TableCell>
                  {!isMF && <TableCell />}
                  <TableCell className="text-right">{priced.length ? formatPct(weight) : "—"}</TableCell>
                  <TableCell />
                </TableRow>
              </TableFooter>
            </Table>
          </div>
          {priced.length < rows.length && (
            <p className="text-xs text-muted-foreground">
              Totals for value and P&L include priced rows only ({priced.length} of {rows.length}).
            </p>
          )}
        </div>
      )}
    </>
  );
}

function Row({ h, isMF }: { h: Holding; isMF: boolean }) {
  const priceDecimals = isMF ? 4 : 2;
  return (
    <TableRow>
      <TableCell className="max-w-72 whitespace-normal">
        <div className="font-medium">{isMF ? h.name : h.symbol}</div>
        <div className="text-xs text-muted-foreground">
          {isMF ? h.category : h.name}
          {h.exposure === "INTERNATIONAL" && " · International exposure"}
          {h.opening_only && " · opening"}
        </div>
      </TableCell>
      <TableCell className="text-right">{formatQty(h.quantity)}</TableCell>
      <TableCell className="text-right">{formatPrice(h.avg_cost, priceDecimals)}</TableCell>
      <TableCell className="text-right">
        {h.price ? (
          <div title={`${h.price_source} (${h.price_source_ref}) · fetched ${formatDateTime(h.price_fetched_at)}`}>
            <div>{formatPrice(h.price, priceDecimals)}</div>
            <div className="text-xs text-muted-foreground">
              {h.price_source?.startsWith("AMFI") ? "AMFI" : "yfinance"} · {formatDate(h.price_date)}
            </div>
          </div>
        ) : (
          <span className="text-xs text-muted-foreground whitespace-normal">{h.unavailable_reason}</span>
        )}
      </TableCell>
      <TableCell className="text-right">{formatINR(h.invested_paise)}</TableCell>
      <TableCell className="text-right">{h.value_paise === null ? "Data unavailable" : formatINR(h.value_paise)}</TableCell>
      <TableCell className={`text-right ${signClass(h.pnl_paise)}`}>
        {h.pnl_paise === null ? "—" : (
          <>
            <div>{formatINR(h.pnl_paise, { signed: true })}</div>
            <div className="text-xs">{formatPct(h.pnl_pct, 2, true)}</div>
          </>
        )}
      </TableCell>
      {!isMF && (
        <TableCell className={`text-right ${signClass(h.day_change_paise)}`}>
          {h.day_change_paise === null ? "—" : formatINR(h.day_change_paise, { signed: true })}
        </TableCell>
      )}
      <TableCell className="text-right">{h.weight === null ? "—" : formatPct(h.weight)}</TableCell>
      <TableCell className="text-right text-xs text-muted-foreground whitespace-normal">
        {h.xirr.rate !== null ? formatPct(h.xirr.rate, 2) : h.xirr.note}
      </TableCell>
    </TableRow>
  );
}
