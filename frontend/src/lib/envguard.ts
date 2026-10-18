// A Vercel preview must never sign in against the production Supabase project. Vercel sets NEXT_PUBLIC_VERCEL_ENV
// (production | preview | development); in a preview the project ref in NEXT_PUBLIC_SUPABASE_URL must be on
// NEXT_PUBLIC_PREVIEW_SUPABASE_REFS, or sign-in is disabled with this message. The backend has the same check for
// its credentials (PREVIEW_ALLOWED_SUPABASE_REFS) and refuses to start.

export function supabaseRef(url: string): string | null {
  const m = /^https:\/\/([a-z0-9]+)\.supabase\.co\/?$/i.exec(url.trim());
  return m ? m[1].toLowerCase() : null;
}

/** Why sign-in is disabled in this deployment, or null. */
export function previewProblem(vercelEnv: string | undefined, supabaseUrl: string, allowedRefs: string | undefined): string | null {
  if (vercelEnv !== "preview") return null;
  const allowed = (allowedRefs ?? "").split(",").map((r) => r.trim().toLowerCase()).filter(Boolean);
  if (allowed.length === 0) return "This preview has no NEXT_PUBLIC_PREVIEW_SUPABASE_REFS: sign-in is disabled.";
  const ref = supabaseRef(supabaseUrl);
  return ref && allowed.includes(ref) ? null
    : "This preview points at a Supabase project that is not on NEXT_PUBLIC_PREVIEW_SUPABASE_REFS: sign-in is disabled.";
}
