"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { Loading } from "@/components/common";
import { supabase } from "@/lib/auth";

/** Lands here from the magic link (PKCE): exchange the code for a session, then go to the dashboard. */
export default function AuthCallback() {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    const sb = supabase();
    const code = new URLSearchParams(window.location.search).get("code");
    if (!sb || !code) {
      router.replace("/login");
      return;
    }
    sb.auth.exchangeCodeForSession(code).then(({ error: err }) => {
      if (err) setError(err.message);
      else router.replace("/");
    });
  }, [router]);
  return error ? <p role="alert" className="text-sm text-destructive">Sign-in failed: {error}. Request a new link.</p> : <Loading />;
}
