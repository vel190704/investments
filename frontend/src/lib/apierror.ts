// Turning failed API responses into readable messages that carry the HTTP status and the backend's request id
// (X-Request-ID), so an error on screen can be matched to its lines in logs/app.log. Pure functions; tested.

export const BACKEND_DOWN = "Cannot reach the backend on 127.0.0.1:8000. Is it running? (make dev)";

type Detail = unknown;

function locText(loc: unknown): string {
  return Array.isArray(loc) ? loc.filter((p) => p !== "body" && p !== "query" && p !== "path").join(".") : "";
}

/** Readable message from a FastAPI error body ({detail}); never raw JSON. */
export function messageFromBody(status: number, body: unknown): string {
  const d: Detail = (body as { detail?: Detail } | null)?.detail;
  if (typeof d === "string" && d.trim()) return d;
  if (Array.isArray(d)) {
    const parts = d.map((e: { loc?: unknown; msg?: string }) => {
      const where = locText(e.loc);
      return where ? `${where}: ${e.msg ?? "invalid"}` : (e.msg ?? "invalid");
    });
    return parts.length ? parts.join("; ") : `Request rejected (HTTP ${status})`;
  }
  if (d && typeof d === "object") {
    const o = d as { errors?: { field?: string; message: string }[]; message?: string };
    if (Array.isArray(o.errors)) return o.errors.map((e) => (e.field ? `${e.field}: ${e.message}` : e.message)).join("; ");
    if (typeof o.message === "string") return o.message;
  }
  return status >= 500 ? `Server error (HTTP ${status})` : `Request failed (HTTP ${status})`;
}

/** Message for a non-JSON error body (usually the dev proxy when the backend is down). */
export function messageFromText(status: number, text: string): string {
  if (status >= 500 || /ECONNREFUSED|socket hang up/i.test(text)) return BACKEND_DOWN;
  const t = text.trim();
  return t && t.length < 200 && !t.startsWith("<") ? t : `Request failed (HTTP ${status})`;
}

const SUFFIX = / \[HTTP (\d{3})(?: · request ([A-Za-z0-9._:-]{1,64}))?\]$/;

export function withSuffix(message: string, status: number, requestId: string | null): string {
  return `${message} [HTTP ${status}${requestId ? ` · request ${requestId}` : ""}]`;
}

/** Inverse of withSuffix: lets ErrorBox show status and request id separately (with a copy button). */
export function parseErrorText(text: string): { message: string; status: number | null; requestId: string | null } {
  const m = text.match(SUFFIX);
  if (!m) return { message: text, status: null, requestId: null };
  return { message: text.slice(0, m.index), status: Number(m[1]), requestId: m[2] ?? null };
}
