// Sign-in needs two public Supabase values, inlined into the browser bundle at BUILD time. A build without them
// produces a site whose sign-in can never work, so `next build` fails instead (next.config.ts), and /login names
// the missing one. Pure functions (tested); never print a value, only a name.

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

/** The build-time check: an error message, or null when the build may go on. Local dev sign-in (DEV_AUTH=1) needs
 * neither value. */
export function buildEnvProblem(env: Record<string, string | undefined>): string | null {
  if (env.NEXT_PUBLIC_DEV_AUTH === "1") return null;
  const missing = missingSupabaseVars({ url: env.NEXT_PUBLIC_SUPABASE_URL, anonKey: env.NEXT_PUBLIC_SUPABASE_ANON_KEY });
  if (missing.length === 0) return null;
  const scope = env.VERCEL_ENV ? ` for the Vercel "${env.VERCEL_ENV}" environment` : "";
  return `next build refused: ${missing.join(" and ")} ${missing.length === 2 ? "are" : "is"} missing or empty${scope}. ` +
    "The site's sign-in would not work. Set it (Vercel › Project › Settings › Environment Variables, the scope " +
    "being built) and redeploy. For a local build without sign-in use NEXT_PUBLIC_DEV_AUTH=1.";
}
