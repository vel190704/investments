// The public build-time configuration: values inlined into the browser bundle when the site is BUILT. A build with a
// missing or malformed value produces a site whose sign-in or API calls can never work, so `next build` fails
// (next.config.ts) and /login shows the same problem. Pure functions (tested). Messages name the variable and the
// problem only, never the value.

export const SUPABASE_VARS = ["NEXT_PUBLIC_SUPABASE_URL", "NEXT_PUBLIC_SUPABASE_ANON_KEY"] as const;
export type SupabaseVar = (typeof SUPABASE_VARS)[number];

/** Names of the Supabase variables that are missing or empty (whitespace counts as empty). */
export function missingSupabaseVars(values: { url?: string; anonKey?: string }): SupabaseVar[] {
  const out: SupabaseVar[] = [];
  if (!values.url?.trim()) out.push("NEXT_PUBLIC_SUPABASE_URL");
  if (!values.anonKey?.trim()) out.push("NEXT_PUBLIC_SUPABASE_ANON_KEY");
  return out;
}

/** The /login message for a build without them; `deployment` is Vercel's environment if known. */
export function notConfiguredMessage(missing: SupabaseVar[], deployment?: string): string {
  const which = missing.length === 2 ? `${missing[0]} and ${missing[1]} are` : `${missing[0]} is`;
  const where = deployment ? ` (this is a ${deployment} deployment: set it in that Vercel scope)` : "";
  return `Sign-in is not configured: ${which} missing or empty in this build${where}. Set the value and redeploy; ` +
    "NEXT_PUBLIC_* values are fixed when the site is built.";
}

/** Shape problems shared by both URLs: what is wrong, never the value. */
function urlShapeProblem(raw: string): { problem: string } | { url: URL } {
  if (/\s/.test(raw)) return { problem: "contains a space or line break (check for a pasted space at either end)" };
  if (raw.includes(",")) return { problem: "contains a comma (exactly one URL is expected)" };
  if (raw.endsWith("/")) return { problem: "ends with a slash (remove the trailing /)" };
  let url: URL;
  try {
    url = new URL(raw);
  } catch {
    return { problem: "is not a valid URL (expected https://…)" };
  }
  if (url.protocol !== "https:") return { problem: `must start with https:// (it uses ${url.protocol.replace(":", "")})` };
  if (url.username || url.password) return { problem: "must not contain a user name or password" };
  if (url.search || url.hash) return { problem: "must not contain ? or #" };
  return { url };
}

/** NEXT_PUBLIC_SUPABASE_URL: https://<project-ref>.supabase.co, nothing else. Null when fine. */
export function supabaseUrlProblem(raw: string | undefined): string | null {
  if (!raw) return null;  // missing is reported by missingSupabaseVars
  const r = urlShapeProblem(raw);
  if ("problem" in r) return `NEXT_PUBLIC_SUPABASE_URL ${r.problem}`;
  if (!r.url.hostname.endsWith(".supabase.co") || r.url.hostname.split(".").length !== 3) {
    return "NEXT_PUBLIC_SUPABASE_URL must be the project URL https://<project-ref>.supabase.co (the host is not a supabase.co project)";
  }
  if (r.url.port) return "NEXT_PUBLIC_SUPABASE_URL must not contain a port";
  if (r.url.pathname !== "/") return "NEXT_PUBLIC_SUPABASE_URL must not contain a path (only https://<project-ref>.supabase.co)";
  return null;
}

const LOCAL_HOSTS = new Set(["localhost", "127.0.0.1", "0.0.0.0", "[::1]", "::1"]);

/** NEXT_PUBLIC_API_URL: the backend origin, https, not a local address. Null when fine. */
export function apiUrlProblem(raw: string | undefined): string | null {
  if (!raw) return "NEXT_PUBLIC_API_URL is missing or empty (the backend origin, e.g. https://<service>.onrender.com)";
  const r = urlShapeProblem(raw);
  if ("problem" in r) return `NEXT_PUBLIC_API_URL ${r.problem}`;
  if (LOCAL_HOSTS.has(r.url.hostname) || r.url.hostname.endsWith(".localhost")) {
    return "NEXT_PUBLIC_API_URL points at this computer (localhost/127.0.0.1); a deployed site needs the backend's public https URL";
  }
  if (r.url.pathname !== "/") {
    return "NEXT_PUBLIC_API_URL must be the backend origin only, without a path (the app adds /api itself)";
  }
  return null;
}

/** Every problem with the public configuration (empty list = fine). Local builds without sign-in
 * (NEXT_PUBLIC_DEV_AUTH=1) need none of these. NEXT_PUBLIC_API_URL is checked in production builds only: local
 * `next dev` leaves it empty and proxies /api to the backend on 127.0.0.1. */
export function publicConfigProblems(env: Record<string, string | undefined>, production = true): string[] {
  if (env.NEXT_PUBLIC_DEV_AUTH === "1") return [];
  const url = env.NEXT_PUBLIC_SUPABASE_URL;
  const out: string[] = missingSupabaseVars({ url, anonKey: env.NEXT_PUBLIC_SUPABASE_ANON_KEY })
    .map((name) => `${name} is missing or empty`);
  const u = supabaseUrlProblem(url?.trim() ? url : undefined);
  if (u) out.push(u);
  if (env.NEXT_PUBLIC_SUPABASE_ANON_KEY?.trim() && /\s/.test(env.NEXT_PUBLIC_SUPABASE_ANON_KEY)) {
    out.push("NEXT_PUBLIC_SUPABASE_ANON_KEY contains a space or line break");
  }
  const a = production ? apiUrlProblem(env.NEXT_PUBLIC_API_URL) : null;
  if (a) out.push(a);
  return out;
}

/** The build-time check: an error message, or null when the build may go on. */
export function buildEnvProblem(env: Record<string, string | undefined>): string | null {
  const problems = publicConfigProblems(env);
  if (problems.length === 0) return null;
  const scope = env.VERCEL_ENV ? ` for the Vercel "${env.VERCEL_ENV}" environment` : "";
  return `next build refused${scope}:\n${problems.map((p) => `  - ${p}`).join("\n")}\n` +
    "Fix it in Vercel › Project › Settings › Environment Variables (the scope being built) and redeploy. " +
    "For a local build without sign-in use NEXT_PUBLIC_DEV_AUTH=1.";
}
