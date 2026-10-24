"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { PageHeader, Section } from "@/components/common";
import { Field } from "@/components/form";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { AUTH_MODE, sendMagicLink, signInProblem, verifyEmailCode } from "@/lib/auth";

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [code, setCode] = useState("");
  const [sent, setSent] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const problem = AUTH_MODE === "dev" ? null : signInProblem();

  async function request(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    const err = await sendMagicLink(email);
    setError(err);
    setSent(!err);
    setBusy(false);
  }
  async function verify(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    const err = await verifyEmailCode(email, code);
    setBusy(false);
    if (err) setError(err);
    else router.replace("/");
  }
  return (
    <>
      <PageHeader title="Sign in" subtitle={<>Invite-only. We email you a sign-in link and a one-time code; there is no password. New here? Read <Link className="underline" href="/help">How to use this app</Link>.</>} />
      <Section title={sent ? "Check your email" : "Email"}>
        {AUTH_MODE === "dev" ? (
          <p className="text-sm text-muted-foreground">Local dev mode: no sign-in needed. <Link className="underline" href="/">Open the dashboard</Link>.</p>
        ) : problem ? (
          <p role="alert" className="text-sm text-destructive">{problem}</p>
        ) : !sent ? (
          <form onSubmit={request} className="flex max-w-md flex-col gap-3">
            <Field label="Your email (the one you were invited with)">
              <Input type="email" required autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} />
            </Field>
            {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
            <Button type="submit" disabled={busy}>{busy ? "Sending…" : "Email me a sign-in link and code"}</Button>
          </form>
        ) : (
          <div className="flex max-w-md flex-col gap-4 text-sm">
            <p>If <b>{email}</b> has been invited, an email is on its way. Use <b>one</b> of these:</p>
            <div>
              <p className="font-medium">The link</p>
              <p className="text-muted-foreground">Open it <b>in this same browser</b> on this device. A link opened in
                another browser, another device or an email app&apos;s built-in browser can&apos;t finish signing in.</p>
            </div>
            <form onSubmit={verify} className="flex flex-col gap-2">
              <p className="font-medium">Or the code (works anywhere)</p>
              <p className="text-muted-foreground">Read the email on any device and type the 6-digit code here.</p>
              <Field label="Code from the email">
                <Input inputMode="numeric" autoComplete="one-time-code" pattern="[0-9 -]*" maxLength={14} required
                       value={code} onChange={(e) => setCode(e.target.value)} className="w-40 tracking-widest" />
              </Field>
              {error && <p role="alert" className="text-destructive">{error}</p>}
              <div className="flex flex-wrap gap-2">
                <Button type="submit" disabled={busy}>{busy ? "Checking…" : "Sign in with the code"}</Button>
                <Button type="button" variant="outline" disabled={busy}
                        onClick={() => { setSent(false); setCode(""); setError(null); }}>Use another email / send again</Button>
              </div>
            </form>
            <p className="text-xs text-muted-foreground">Nothing arrived? Check spam, wait a minute before asking again
              (sending is rate-limited), and use the newest email: older links and codes stop working.</p>
          </div>
        )}
      </Section>
      <p className="mt-4 text-xs text-muted-foreground">
        By signing in you accept the <Link className="underline" href="/terms">terms and data notice</Link>.
      </p>
    </>
  );
}
