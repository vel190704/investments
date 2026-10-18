"use client";

import { useState } from "react";
import { useMe } from "@/components/auth-gate";
import { ErrorBox, Loading, Notice, PageHeader, Section } from "@/components/common";
import { Field, Select } from "@/components/form";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { apiDelete, apiPost, apiPut, errorText, useApi } from "@/lib/api";
import { formatDateTime } from "@/lib/format";

type AdminUser = {
  id: number | null; email: string; role: string; invited: boolean; signed_in: boolean; created_at: string | null;
  last_active_at: string | null; ai_enabled: boolean; ai_monthly_cap: number | null; ai_calls_this_month: number;
  ai_tokens_this_month: { input: number; output: number }; own_key: boolean; rows: Record<string, number>;
  disabled: boolean;
};
type AdminPage = { users: AdminUser[]; global_ai: { calls_this_month: number; cap: number } };

export default function AdminPageView() {
  const { me } = useMe();
  const { data, error, loading, reload } = useApi<AdminPage>("/admin/users");
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  if (me && !me.is_admin) return <ErrorBox message="Admin only." />;
  const run = async (fn: () => Promise<unknown>, ok: string) => {
    try {
      await fn();
      setMsg({ ok: true, text: ok });
      reload();
    } catch (e) {
      setMsg({ ok: false, text: errorText(e) });
    }
  };
  return (
    <>
      <PageHeader title="Admin" subtitle="People with access, their AI usage, invitations and data deletion. Row counts only: you are not shown anyone's figures here." />
      {msg && (msg.ok ? <Notice>{msg.text}</Notice> : <ErrorBox message={msg.text} />)}
      {error && <ErrorBox message={error} />}
      {loading && !data && <Loading />}
      {data && (
        <div className="flex flex-col gap-4">
          <Operations />
          <Invite onInvite={(email, send) => run(() => apiPost("/admin/invites", { email, send_email: send }), `Invited ${email}.`)} />
          <Section title={`People (${data.users.length})`} aside={`App AI budget this month: ${data.global_ai.calls_this_month}/${data.global_ai.cap} calls`}>
            <div className="overflow-x-auto">
              <table className="tnum w-full text-sm">
                <thead className="text-xs text-muted-foreground">
                  <tr><th className="py-1 text-left font-normal">Email</th><th className="py-1 text-left font-normal">Status</th>
                    <th className="py-1 text-left font-normal">Last active</th><th className="py-1 text-right font-normal">Rows</th>
                    <th className="py-1 pl-4 text-left font-normal">AI</th><th className="py-1 text-left font-normal"></th></tr>
                </thead>
                <tbody>
                  {data.users.map((u) => <UserRow key={u.email} u={u} self={u.id === me?.id} run={run} />)}
                </tbody>
              </table>
            </div>
          </Section>
          <FeedbackList />
        </div>
      )}
    </>
  );
}

type FeedbackItem = { id: number; user_id: number; email: string; page: string; text: string; created_at: string;
                      done_at: string | null };
type FeedbackPage = { items: FeedbackItem[]; pages: string[]; open: number };

function FeedbackList() {
  const [filter, setFilter] = useState({ status: "open", page: "", since: "", until: "" });
  const qs = new URLSearchParams(Object.entries(filter).filter(([, v]) => v)).toString();
  const { data, error, reload } = useApi<FeedbackPage>(`/admin/feedback?${qs}`);
  const [msg, setMsg] = useState<string | null>(null);
  const mark = async (id: number, done: boolean) => {
    try {
      await apiPut(`/admin/feedback/${id}/done`, { done });
      setMsg(null);
      reload();
    } catch (e) {
      setMsg(errorText(e));
    }
  };
  const set = (k: keyof typeof filter) => (e: { target: { value: string } }) => setFilter({ ...filter, [k]: e.target.value });
  return (
    <Section title="Feedback" aside={data ? `${data.open} open` : undefined}>
      <div className="mb-3 flex flex-wrap items-end gap-2 text-xs">
        <Field label="Status">
          <Select value={filter.status} onChange={set("status")}>
            <option value="open">open</option><option value="done">done</option><option value="all">all</option>
          </Select>
        </Field>
        <Field label="Page">
          <Select value={filter.page} onChange={set("page")}>
            <option value="">all pages</option>
            {data?.pages.map((p) => <option key={p} value={p}>{p}</option>)}
          </Select>
        </Field>
        <Field label="From (IST)"><Input type="date" value={filter.since} onChange={set("since")} /></Field>
        <Field label="To (IST)"><Input type="date" value={filter.until} onChange={set("until")} /></Field>
      </div>
      {error && <ErrorBox message={error} />}
      {msg && <ErrorBox message={msg} />}
      {data && data.items.length === 0 && <p className="text-sm text-muted-foreground">No feedback for this filter.</p>}
      <ul className="flex flex-col gap-2">
        {data?.items.map((f) => (
          <li key={f.id} className="rounded-md border border-border p-2 text-sm">
            <div className="mb-1 flex flex-wrap gap-2 text-xs text-muted-foreground">
              <span>{formatDateTime(f.created_at)}</span><span>{f.page}</span><span>user {f.user_id} · {f.email}</span>
              {f.done_at && <span>done {formatDateTime(f.done_at)}</span>}
              <span className="flex-1" />
              <button className="underline" onClick={() => mark(f.id, !f.done_at)}>{f.done_at ? "reopen" : "mark as done"}</button>
            </div>
            <p className="whitespace-pre-wrap break-words">{f.text}</p>
          </li>
        ))}
      </ul>
    </Section>
  );
}

function Invite({ onInvite }: { onInvite: (email: string, send: boolean) => void }) {
  const [email, setEmail] = useState("");
  const [send, setSend] = useState(true);
  return (
    <Section title="Invite someone">
      <form className="flex flex-wrap items-end gap-2" onSubmit={(e) => { e.preventDefault(); onInvite(email, send); setEmail(""); }}>
        <Field label="Email"><Input type="email" required className="w-72" value={email} onChange={(e) => setEmail(e.target.value)} /></Field>
        <label className="flex items-center gap-2 text-xs text-muted-foreground">
          <input type="checkbox" checked={send} onChange={(e) => setSend(e.target.checked)} />
          send the invitation email (needs the Supabase service key on the server; otherwise invite them in the Supabase dashboard too)
        </label>
        <Button type="submit">Invite</Button>
      </form>
    </Section>
  );
}

function UserRow({ u, self, run }: { u: AdminUser; self: boolean;
                                     run: (fn: () => Promise<unknown>, ok: string) => void }) {
  const [cap, setCap] = useState(String(u.ai_monthly_cap ?? ""));
  const [confirm, setConfirm] = useState("");
  const [open, setOpen] = useState(false);
  const rows = Object.values(u.rows).reduce((a, b) => a + b, 0);
  return (
    <tr className="border-t border-border align-top">
      <td className="py-2 pr-2">{u.email}{u.role === "admin" && <span className="ml-1 rounded border border-border px-1 text-[10px]">admin</span>}</td>
      <td className="py-2 pr-2 text-xs text-muted-foreground">
        {u.id === null ? "invited, not signed in yet" : u.signed_in ? "signed in" : "account created"}{!u.invited && u.role !== "admin" && u.id !== null ? " · invite removed" : ""}
        {u.disabled && <span className="ml-1 font-medium text-destructive">· disabled</span>}
      </td>
      <td className="py-2 pr-2 text-xs">{u.last_active_at ? formatDateTime(u.last_active_at) : "—"}</td>
      <td className="py-2 pr-2 text-right text-xs" title={Object.entries(u.rows).map(([k, v]) => `${k}: ${v}`).join("\n")}>{u.id === null ? "—" : rows}</td>
      <td className="py-2 pr-2 pl-4 text-xs">
        {u.id === null ? "—" : (
          <div className="flex flex-wrap items-center gap-2">
            <label className="flex items-center gap-1">
              <input type="checkbox" checked={u.ai_enabled} disabled={u.role === "admin"}
                     onChange={(e) => run(() => apiPut(`/admin/users/${u.id}/ai`, { ai_enabled: e.target.checked, ai_monthly_cap: Number(cap) || null }), "AI setting saved.")} />
              enabled
            </label>
            <input className="w-14 rounded border border-input bg-input/30 px-1" value={cap} onChange={(e) => setCap(e.target.value.replace(/\D/g, ""))}
                   onBlur={() => run(() => apiPut(`/admin/users/${u.id}/ai`, { ai_enabled: u.ai_enabled, ai_monthly_cap: Number(cap) || 0 }), "Cap saved.")} />
            <span className="text-muted-foreground">/mo · used {u.ai_calls_this_month}{u.own_key ? " · own key" : ""}</span>
          </div>
        )}
      </td>
      <td className="py-2 text-xs">
        {u.id !== null && !self && u.role !== "admin" && (
          <button className="mr-2 underline"
                  onClick={() => (u.disabled || window.confirm(`Disable ${u.email}? Every request of theirs is refused until you enable them again. Their data is kept.`))
                    && run(() => apiPut(`/admin/users/${u.id}/disabled`, { disabled: !u.disabled }), u.disabled ? `Enabled ${u.email}.` : `Disabled ${u.email}.`)}>
            {u.disabled ? "enable" : "disable"}
          </button>
        )}
        {u.invited && <button className="underline" onClick={() => run(() => apiDelete(`/admin/invites/${encodeURIComponent(u.email)}`), "Invitation removed.")}>remove invite</button>}
        {u.id !== null && !self && (
          <div className="mt-1">
            {!open ? <button className="text-destructive underline" onClick={() => setOpen(true)}>delete all data…</button> : (
              <div className="flex flex-col gap-1">
                <input className="w-52 rounded border border-input bg-input/30 px-1" placeholder={`type ${u.email}`} value={confirm} onChange={(e) => setConfirm(e.target.value)} />
                <Button size="sm" variant="destructive" disabled={confirm.trim().toLowerCase() !== u.email.toLowerCase()}
                        onClick={() => run(() => apiDelete(`/admin/users/${u.id}`, { confirm, remove_account: true }), `Deleted ${u.email} and all their data.`)}>
                  Delete permanently
                </Button>
              </div>
            )}
          </div>
        )}
      </td>
    </tr>
  );
}

type Switches = { new_signins_off: boolean; members_paused: boolean; ai_off: boolean };
type AuditEntry = { id: number; at: string; admin_user_id: number | null; action: string; target_user_id: number | null;
                    details: Record<string, unknown> };
type OpsPage = { switches: Switches; messages: Record<string, string>; audit: AuditEntry[] };

const SWITCH_TEXT: Record<keyof Switches, { label: string; what: string }> = {
  new_signins_off: { label: "New sign-ins off",
                     what: "Nobody can sign in for the first time. People who already signed in keep working." },
  members_paused: { label: "Pause everyone except admins",
                    what: "Every request from a non-admin is refused (incidents, e.g. suspected data exposure)." },
  ai_off: { label: "AI off for everyone", what: "No AI call is made for anyone, whatever their own setting or key." },
};

function Operations() {
  const { data, error, reload } = useApi<OpsPage>("/admin/ops");
  const [msg, setMsg] = useState<string | null>(null);
  const flip = async (k: keyof Switches, on: boolean) => {
    if (on && !window.confirm(`${SWITCH_TEXT[k].label}: ${SWITCH_TEXT[k].what} Turn it on now?`)) return;
    try {
      await apiPut("/admin/ops", { [k]: on });
      setMsg(null);
      reload();
    } catch (e) {
      setMsg(errorText(e));
    }
  };
  return (
    <Section title="Kill switches" aside="take effect on the next request, without a redeploy; every change is audit-logged">
      {error && <ErrorBox message={error} />}
      {msg && <ErrorBox message={msg} />}
      {data && (
        <>
          <ul className="flex flex-col gap-2 text-sm">
            {(Object.keys(SWITCH_TEXT) as (keyof Switches)[]).map((k) => (
              <li key={k} className="flex flex-wrap items-center gap-2">
                <label className="flex items-center gap-2 font-medium">
                  <input type="checkbox" checked={data.switches[k]} onChange={(e) => flip(k, e.target.checked)} />
                  {SWITCH_TEXT[k].label}
                </label>
                {data.switches[k] && <span className="rounded border border-destructive/40 px-1 text-xs text-destructive">ON</span>}
                <span className="text-xs text-muted-foreground">{SWITCH_TEXT[k].what}</span>
              </li>
            ))}
          </ul>
          <details className="mt-3 text-xs">
            <summary className="cursor-pointer text-muted-foreground">Audit log ({data.audit.length} most recent)</summary>
            <table className="tnum mt-2 w-full">
              <thead className="text-muted-foreground">
                <tr><th className="text-left font-normal">When</th><th className="text-left font-normal">Admin</th>
                  <th className="text-left font-normal">Action</th><th className="text-left font-normal">User</th>
                  <th className="text-left font-normal">Details</th></tr>
              </thead>
              <tbody>
                {data.audit.map((a) => (
                  <tr key={a.id} className="border-t border-border">
                    <td className="py-1 pr-2">{formatDateTime(a.at)}</td><td className="pr-2">{a.admin_user_id ?? "—"}</td>
                    <td className="pr-2">{a.action}</td><td className="pr-2">{a.target_user_id ?? "—"}</td>
                    <td className="text-muted-foreground">{Object.entries(a.details).map(([k, v]) => `${k}=${String(v)}`).join(" ")}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </details>
        </>
      )}
    </Section>
  );
}
