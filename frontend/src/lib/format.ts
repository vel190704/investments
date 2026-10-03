// INR formatting with Indian digit grouping (1,23,456.00). Mirrors backend app/money.py.
// Money arrives from the API as integer paise; this file never does float arithmetic on money.

export function groupIndian(digits: string): string {
  if (digits.length <= 3) return digits;
  let head = digits.slice(0, -3);
  const tail = digits.slice(-3);
  const groups: string[] = [];
  while (head.length > 2) {
    groups.unshift(head.slice(-2));
    head = head.slice(0, -2);
  }
  if (head) groups.unshift(head);
  return `${groups.join(",")},${tail}`;
}

export function formatINR(
  paise: number | null | undefined,
  opts: { symbol?: boolean; decimals?: boolean; signed?: boolean } = {},
): string {
  if (paise === null || paise === undefined) return "Data unavailable";
  const { symbol = true, decimals = true, signed = false } = opts;
  const p = BigInt(Math.round(paise));
  const negative = p < 0n;
  const abs = negative ? -p : p;
  let body: string;
  if (decimals) {
    const rupees = abs / 100n;
    const rem = abs % 100n;
    body = `${groupIndian(rupees.toString())}.${rem.toString().padStart(2, "0")}`;
  } else {
    body = groupIndian(((abs + 50n) / 100n).toString());
  }
  const sign = negative ? "-" : signed && abs > 0n ? "+" : "";
  return `${sign}${symbol ? "₹" : ""}${body}`;
}

/** Decimal-string fraction ("0.379951") -> "38.0%". Display only. */
export function formatPct(
  fraction: string | number | null | undefined,
  places = 1,
  signed = false,
): string {
  if (fraction === null || fraction === undefined) return "N/A";
  const v = Number(fraction) * 100;
  const s = v.toFixed(places);
  return `${signed && v > 0 ? "+" : ""}${s === `-${(0).toFixed(places)}` ? (0).toFixed(places) : s}%`;
}

/** Already-rounded percent string from the API ("93.2") -> "93.2%". */
export function pctLabel(displayPct: string): string {
  return `${displayPct}%`;
}

export function formatQty(q: string | null | undefined): string {
  if (q === null || q === undefined) return "—";
  const [i, f] = q.split(".");
  return f ? `${groupIndian(i)}.${f}` : groupIndian(i);
}

export function formatPrice(p: string | null | undefined, places = 2): string {
  if (p === null || p === undefined) return "Data unavailable";
  // Unit prices are display-only here (never summed), so fixed-point rounding is fine.
  const [i, f] = Number(p).toFixed(places).split(".");
  const neg = i.startsWith("-");
  return `${neg ? "-" : ""}₹${groupIndian(neg ? i.slice(1) : i)}${f ? `.${f}` : ""}`;
}

export function formatDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso.length === 10 ? `${iso}T00:00:00` : iso);
  return d.toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" });
}

export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("en-IN", {
    day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit",
    timeZone: "Asia/Kolkata", timeZoneName: "short",
  });
}

export function signClass(n: number | null | undefined): string {
  if (n === null || n === undefined || n === 0) return "text-muted-foreground";
  return n > 0 ? "text-gain" : "text-loss";
}
