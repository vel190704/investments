"use client";

import { useState } from "react";
import { useMe } from "@/components/auth-gate";
import { ErrorBox, Loading, Notice, PageHeader, Section } from "@/components/common";
import { Field } from "@/components/form";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { apiDelete, apiDownload, apiPut, errorText } from "@/lib/api";
import { signOut } from "@/lib/auth";

export default function AccountPage() {
  const { me, reload } = useMe();
  if (!me) return <Loading />;
  return (
    <>
      <PageHeader title="Account" subtitle={`${me.email} · ${me.is_admin ? "admin" : "member"}`} />
      <div className="flex flex-col gap-4">
        <Section title="Your data">
          <p className="text-sm text-muted-foreground">
            Your workbook rows, settings, journal, notes and analyses are visible only to you (and, technically, to the
            admin who runs the server). Market data such as prices and news is shared and contains nothing about you.
          </p>
          <div className="mt-3 flex flex-wrap gap-2">
            <Button variant="outline" onClick={() => apiDownload("/export.xlsx", "my_investment_data.xlsx")}>Export my data (Excel)</Button>
            <Button variant="outline" onClick={() => apiDownload("/onboarding/template.xlsx", "investment_tracker_template.xlsx")}>Blank template</Button>
          </div>
        </Section>
        <Section title="AI analysis">
          <p className="text-sm">
            {me.ai.ai_enabled_by_admin
              ? `Enabled by the admin. This month: ${me.ai.calls_this_month}/${me.ai.cap} calls.`
              : "Not enabled for your account. AI analysis uses the app's key and is enabled per person by the admin."}
          </p>
          <OwnKey hasKey={me.ai.own_key} onSaved={reload} />
        </Section>
        <DeleteAccount email={me.email} />
      </div>
    </>
  );
}

function OwnKey({ hasKey, onSaved }: { hasKey: boolean; onSaved: () => void }) {
  const [key, setKey] = useState("");
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  async function save(value: string | null) {
    try {
      await apiPut("/me/ai-key", { key: value });
      setKey("");
      setMsg({ ok: true, text: value ? "Saved (encrypted on the server; it is never shown again)." : "Removed." });
      onSaved();
    } catch (e) {
      setMsg({ ok: false, text: errorText(e) });
    }
  }
  return (
    <div className="mt-3 flex flex-col gap-2">
      <p className="text-xs text-muted-foreground">
        Optional: use your own Anthropic API key. It is stored encrypted, never shown again or logged, and your calls
        then don&apos;t use the app&apos;s shared budget. {hasKey ? "A key is stored." : "No key stored."}
      </p>
      <div className="flex flex-wrap items-end gap-2">
        <Field label="Anthropic API key"><Input type="password" autoComplete="off" className="w-80" value={key} onChange={(e) => setKey(e.target.value)} /></Field>
        <Button variant="outline" disabled={!key} onClick={() => save(key)}>Save key</Button>
        {hasKey && <Button variant="ghost" onClick={() => save(null)}>Remove key</Button>}
      </div>
      {msg && (msg.ok ? <Notice>{msg.text}</Notice> : <ErrorBox message={msg.text} />)}
    </div>
  );
}

function DeleteAccount({ email }: { email: string }) {
  const [confirm, setConfirm] = useState("");
  const [err, setErr] = useState<string | null>(null);
  async function del() {
    try {
      await apiDelete("/me", { confirm });
      await signOut();
    } catch (e) {
      setErr(errorText(e));
    }
  }
  return (
    <Section title="Delete my account and all data">
      <p className="text-sm text-muted-foreground">
        Permanently deletes your transactions, holdings, snapshots, settings, journal, notes, uploads and analyses,
        and your account. This cannot be undone. Export your data first if you want a copy.
      </p>
      <div className="mt-3 flex flex-wrap items-end gap-2">
        <Field label={`Type ${email} to confirm`}><Input className="w-80" value={confirm} onChange={(e) => setConfirm(e.target.value)} /></Field>
        <Button variant="destructive" disabled={confirm.trim().toLowerCase() !== email.toLowerCase()} onClick={del}>Delete everything</Button>
      </div>
      {err && <ErrorBox message={err} />}
    </Section>
  );
}
