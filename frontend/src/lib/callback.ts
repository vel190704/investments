// /auth/callback: turn the magic link's ?code= into a session exactly once. The Supabase client is created with
// detectSessionInUrl: false (lib/auth.ts), so nothing else exchanges the code. Exchanging twice was the cause of
// "PKCE code verifier not found in storage": the first exchange consumes the verifier. Repeated calls for the same
// code (React effects running twice, a remount) share one promise. Pure apart from the client passed in (tested).

export type AuthLike = {
  exchangeCodeForSession(code: string): Promise<{ error: { message: string } | null }>;
  getSession(): Promise<{ data: { session: unknown | null } }>;
};
export type CallbackResult = { ok: true } | { ok: false; message: string };

const inflight = new Map<string, Promise<CallbackResult>>();

export function exchangeOnce(auth: AuthLike, code: string): Promise<CallbackResult> {
  let p = inflight.get(code);
  if (!p) {
    p = run(auth, code);
    inflight.set(code, p);
  }
  return p;
}

async function run(auth: AuthLike, code: string): Promise<CallbackResult> {
  let raw: string;
  try {
    const { error } = await auth.exchangeCodeForSession(code);
    if (!error) return { ok: true };
    raw = error.message;
  } catch (e) {
    raw = e instanceof Error ? e.message : String(e);
  }
  // Already signed in (e.g. the link was opened twice, or another tab finished first): that is success.
  try {
    const { data } = await auth.getSession();
    if (data.session) return { ok: true };
  } catch {
    // fall through to the message
  }
  return { ok: false, message: callbackErrorMessage(raw) };
}

/** Errors Supabase puts in the redirect URL itself (?error_description=… or #error_description=…). */
export function urlError(search: string, hash: string): string | null {
  for (const part of [search, hash.replace(/^#/, "?")]) {
    const q = new URLSearchParams(part);
    const d = q.get("error_description") || q.get("error");
    if (d) return callbackErrorMessage(d);
  }
  return null;
}

export const OTHER_BROWSER =
  "This sign-in link was opened in a different browser or app from the one where you asked for it (or this " +
  "browser's site data was cleared since). A link only works in the same browser. Go back to the sign-in page " +
  "and type the 6-digit code from the same email instead, or ask for a new link from this browser.";

export function callbackErrorMessage(raw: string): string {
  if (/code verifier|code_verifier|both auth code and code verifier/i.test(raw)) return OTHER_BROWSER;
  if (/expired|invalid|already been used|not found/i.test(raw)) {
    return "This sign-in link has expired or was already used. Ask for a new one on the sign-in page.";
  }
  return `Sign-in failed: ${raw.slice(0, 200)}. Ask for a new link on the sign-in page.`;
}

/** The emailed one-time code: digits only (spaces ignored), 6 to 10 long (Supabase's configurable length). */
export function normaliseOtp(input: string): string | null {
  const digits = input.replace(/[\s-]/g, "");
  return /^\d{6,10}$/.test(digits) ? digits : null;
}
