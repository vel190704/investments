"use client";

// Sign-in with Supabase Auth (invite-only magic link). Only the public project URL and publishable ("anon") key are
// used here; both are designed to be public. No secrets in client code: the service-role key and the AI key live on
// the backend only. Only with NEXT_PUBLIC_DEV_AUTH=1 (local dev) is there no sign-in: the backend uses a local user.

import { createClient, type Session, type SupabaseClient } from "@supabase/supabase-js";
import { useEffect, useState } from "react";
import { missingSupabaseVars, notConfiguredMessage, publicConfigProblems } from "./buildenv";
import { normaliseOtp } from "./callback";
import { previewProblem } from "./envguard";

// Static references: Next.js inlines NEXT_PUBLIC_* values at build time, only when written out literally like this
// (never process.env[name] or destructuring). `next build` refuses to run without these two (next.config.ts).
const RAW_SUPABASE_URL = process.env.NEXT_PUBLIC_SUPABASE_URL ?? "";
const RAW_SUPABASE_ANON_KEY = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY ?? "";
const SUPABASE_URL = RAW_SUPABASE_URL.trim();
const SUPABASE_ANON_KEY = RAW_SUPABASE_ANON_KEY.trim();
// Vercel's environment (production | preview | development), injected by next.config.ts from VERCEL_ENV at build
// time, so it doesn't depend on the "Automatically expose System Environment Variables" project setting.
const DEPLOYMENT_ENV = process.env.NEXT_PUBLIC_VERCEL_ENV || process.env.BUILD_VERCEL_ENV || undefined;
// Fail closed: sign-in is required unless NEXT_PUBLIC_DEV_AUTH is exactly "1" (local `make dev` sets it).
export const AUTH_MODE: "dev" | "supabase" = process.env.NEXT_PUBLIC_DEV_AUTH === "1" ? "dev" : "supabase";
export const PUBLIC_PATHS = ["/login", "/auth/callback", "/terms", "/help"];
/** Problems with this build's public configuration (the same check `next build` runs); shown on /login. */
export const CONFIG_PROBLEMS: string[] = AUTH_MODE === "dev" ? [] : publicConfigProblems({
  NEXT_PUBLIC_SUPABASE_URL: RAW_SUPABASE_URL, NEXT_PUBLIC_SUPABASE_ANON_KEY: RAW_SUPABASE_ANON_KEY,
  NEXT_PUBLIC_API_URL: process.env.NEXT_PUBLIC_API_URL,
}, process.env.NODE_ENV === "production");
/** Set in a Vercel preview that points at a Supabase project not on its allow-list: sign-in is then disabled. */
export const PREVIEW_PROBLEM = previewProblem(DEPLOYMENT_ENV, SUPABASE_URL,
                                              process.env.NEXT_PUBLIC_PREVIEW_SUPABASE_REFS);

// ONE client for the whole page (kept on globalThis so a second copy of this module, e.g. after a hot reload,
// can't create another). detectSessionInUrl is OFF: /auth/callback exchanges the link's code itself, exactly once
// (lib/callback.ts). With it on, the client exchanged the code on creation AND the callback did again; the second
// exchange found the PKCE verifier already used ("code verifier not found in storage").
const holder = globalThis as unknown as { __investmentsSupabase?: SupabaseClient };

export function supabase(): SupabaseClient | null {
  if (AUTH_MODE !== "supabase" || !SUPABASE_URL || !SUPABASE_ANON_KEY || PREVIEW_PROBLEM) return null;
  if (CONFIG_PROBLEMS.length) return null;
  holder.__investmentsSupabase ??= createClient(SUPABASE_URL, SUPABASE_ANON_KEY, {
    auth: { flowType: "pkce", persistSession: true, autoRefreshToken: true, detectSessionInUrl: false },
  });
  return holder.__investmentsSupabase;
}

function notAvailable(): string {
  if (PREVIEW_PROBLEM) return PREVIEW_PROBLEM;
  const missing = missingSupabaseVars({ url: SUPABASE_URL, anonKey: SUPABASE_ANON_KEY });
  if (missing.length) return notConfiguredMessage(missing, DEPLOYMENT_ENV);
  if (CONFIG_PROBLEMS.length) return `Sign-in is not configured correctly in this build: ${CONFIG_PROBLEMS.join("; ")}.`;
  return "Sign-in is not available in this build.";
}

export async function accessToken(): Promise<string | null> {
  const sb = supabase();
  if (!sb) return null;
  const { data } = await sb.auth.getSession();
  return data.session?.access_token ?? null;
}

/** Why sign-in can't work in this build, or null. */
export function signInProblem(): string | null {
  if (AUTH_MODE === "dev") return null;  // config only: never creates the client (also safe while prerendering)
  return SUPABASE_URL && SUPABASE_ANON_KEY && !PREVIEW_PROBLEM && !CONFIG_PROBLEMS.length ? null : notAvailable();
}

/** Invite-only: shouldCreateUser=false, so an email that was not invited gets no account. The same email carries
 * the link (same browser only) and, with the template in docs/DEPLOY.md §3, a one-time code (any browser). */
export async function sendMagicLink(email: string): Promise<string | null> {
  const sb = supabase();
  if (!sb) return notAvailable();
  const { error } = await sb.auth.signInWithOtp({
    email: email.trim(),
    options: { shouldCreateUser: false, emailRedirectTo: `${window.location.origin}/auth/callback` },
  });
  return error ? error.message : null;
}

/** Sign in with the emailed one-time code: works in any browser or device (no PKCE verifier involved). */
export async function verifyEmailCode(email: string, code: string): Promise<string | null> {
  const sb = supabase();
  if (!sb) return notAvailable();
  const token = normaliseOtp(code);
  if (!token) return "Enter the code from the email: 6 digits (spaces are fine).";
  const { error } = await sb.auth.verifyOtp({ email: email.trim(), token, type: "email" });
  if (!error) return null;
  return /expired|invalid/i.test(error.message)
    ? "That code is wrong or has expired. Check the newest email, or ask for a new code."
    : error.message;
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
