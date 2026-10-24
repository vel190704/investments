"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { Loading } from "@/components/common";
import { supabase } from "@/lib/auth";
import { exchangeOnce, urlError } from "@/lib/callback";

/** Lands here from the magic link (PKCE): exchange the code for a session exactly once, then go to the dashboard.
 * The client never exchanges it by itself (detectSessionInUrl is off, lib/auth.ts). */
export default function AuthCallback() {
  const router = useRouter();
  const started = useRef(false);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    if (started.current) return;  // React may run this effect twice; exchangeOnce also de-duplicates per code
    started.current = true;
    const sb = supabase();
    const params = new URLSearchParams(window.location.search);
    const code = params.get("code");
    const fromUrl = urlError(window.location.search, window.location.hash);
    if (!sb) {
      router.replace("/login");
      return;
    }
    const finish = (ok: boolean, message?: string) => {
      window.history.replaceState(null, "", "/auth/callback");  // the code is single-use: drop it from the URL
      if (ok) router.replace("/");
      else setError(message ?? "Sign-in failed. Ask for a new link on the sign-in page.");
    };
    if (!code) {
      // no code (or an error from Supabase in the URL): already signed in counts as success
      sb.auth.getSession().then(({ data }) => (data.session ? finish(true) : fromUrl ? finish(false, fromUrl)
        : router.replace("/login")));
      return;
    }
    exchangeOnce(sb.auth, code).then((r) => (r.ok ? finish(true) : finish(false, r.message)));
  }, [router]);
  if (!error) return <Loading />;
  return (
    <div role="alert" className="flex max-w-xl flex-col gap-2 text-sm">
      <p className="text-destructive">{error}</p>
      <p><Link className="underline" href="/login">Go to the sign-in page</Link> (you can enter the code from the email there).</p>
    </div>
  );
}
