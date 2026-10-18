"use client";

// Sign-in with Supabase Auth (invite-only magic link). Only the public project URL and publishable ("anon") key are
// used here; both are designed to be public. No secrets in client code: the service-role key and the AI key live on
// the backend only. Only with NEXT_PUBLIC_DEV_AUTH=1 (local dev) is there no sign-in: the backend uses a local user.

import { createClient, type Session, type SupabaseClient } from "@supabase/supabase-js";
import { useEffect, useState } from "react";
import { previewProblem } from "./envguard";

// Static references: Next.js inlines NEXT_PUBLIC_* values at build time.
const SUPABASE_URL = process.env.NEXT_PUBLIC_SUPABASE_URL ?? "";
const SUPABASE_ANON_KEY = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY ?? "";
// Fail closed: sign-in is required unless NEXT_PUBLIC_DEV_AUTH is exactly "1" (local `make dev` sets it).
export const AUTH_MODE: "dev" | "supabase" = process.env.NEXT_PUBLIC_DEV_AUTH === "1" ? "dev" : "supabase";
export const PUBLIC_PATHS = ["/login", "/auth/callback", "/terms", "/help"];
/** Set in a Vercel preview that points at a Supabase project not on its allow-list: sign-in is then disabled. */
export const PREVIEW_PROBLEM = previewProblem(process.env.NEXT_PUBLIC_VERCEL_ENV, SUPABASE_URL,
                                              process.env.NEXT_PUBLIC_PREVIEW_SUPABASE_REFS);

let client: SupabaseClient | null = null;

export function supabase(): SupabaseClient | null {
  if (AUTH_MODE !== "supabase" || !SUPABASE_URL || !SUPABASE_ANON_KEY || PREVIEW_PROBLEM) return null;
  if (!client) {
    client = createClient(SUPABASE_URL, SUPABASE_ANON_KEY, {
      auth: { flowType: "pkce", persistSession: true, autoRefreshToken: true, detectSessionInUrl: true },
    });
  }
  return client;
}

export async function accessToken(): Promise<string | null> {
  const sb = supabase();
  if (!sb) return null;
  const { data } = await sb.auth.getSession();
  return data.session?.access_token ?? null;
}

/** Invite-only: shouldCreateUser=false, so an email that was not invited gets no account. */
export async function sendMagicLink(email: string): Promise<string | null> {
  if (PREVIEW_PROBLEM) return PREVIEW_PROBLEM;
  const sb = supabase();
  if (!sb) return "Sign-in is not configured (NEXT_PUBLIC_SUPABASE_URL / NEXT_PUBLIC_SUPABASE_ANON_KEY).";
  const { error } = await sb.auth.signInWithOtp({
    email: email.trim(),
    options: { shouldCreateUser: false, emailRedirectTo: `${window.location.origin}/auth/callback` },
  });
  return error ? error.message : null;
}

export async function signOut(): Promise<void> {
  const sb = supabase();
  if (sb) await sb.auth.signOut();
  window.location.href = AUTH_MODE === "supabase" ? "/login" : "/";
}

/** undefined while loading; null when signed out (always a placeholder session in dev mode). */
export function useSession(): Session | null | undefined {
  const [session, setSession] = useState<Session | null | undefined>(undefined);
  useEffect(() => {
    const sb = supabase();
    if (!sb) {
      const t = setTimeout(() => setSession(AUTH_MODE === "dev" ? ({} as Session) : null), 0);
      return () => clearTimeout(t);
    }
    sb.auth.getSession().then(({ data }) => setSession(data.session));
    const { data } = sb.auth.onAuthStateChange((_e, s) => setSession(s));
    return () => data.subscription.unsubscribe();
  }, []);
  return session;
}
