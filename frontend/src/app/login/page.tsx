"use client";

import Link from "next/link";
import { useState } from "react";
import { PageHeader, Section } from "@/components/common";
import { Field } from "@/components/form";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { AUTH_MODE, sendMagicLink } from "@/lib/auth";

export default function LoginPage() {
  const [email, setEmail] = useState("");
  const [state, setState] = useState<{ sent?: boolean; error?: string }>({});
  const [busy, setBusy] = useState(false);
  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    const err = await sendMagicLink(email);
    setState(err ? { error: err } : { sent: true });
    setBusy(false);
  }
  return (
    <>
      <PageHeader title="Sign in" subtitle="Invite-only. We email you a one-time sign-in link; there is no password." />
      <Section title="Email">
        {AUTH_MODE === "dev" ? (
          <p className="text-sm text-muted-foreground">Local dev mode: no sign-in needed. <Link className="underline" href="/">Open the dashboard</Link>.</p>
        ) : state.sent ? (
          <p className="text-sm">If <b>{email}</b> has been invited, a sign-in link is on its way. Open it on this device.</p>
        ) : (
          <form onSubmit={submit} className="flex max-w-md flex-col gap-3">
            <Field label="Your email (the one you were invited with)">
              <Input type="email" required autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} />
            </Field>
            {state.error && <p role="alert" className="text-sm text-destructive">{state.error}</p>}
            <Button type="submit" disabled={busy}>{busy ? "Sending…" : "Email me a sign-in link"}</Button>
          </form>
        )}
      </Section>
      <p className="mt-4 text-xs text-muted-foreground">
        By signing in you accept the <Link className="underline" href="/terms">terms and data notice</Link>.
      </p>
    </>
  );
}
