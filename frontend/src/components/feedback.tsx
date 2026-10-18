"use client";

import { usePathname } from "next/navigation";
import { useState } from "react";
import { useMe } from "@/components/auth-gate";
import { ErrorBox } from "@/components/common";
import { Button } from "@/components/ui/button";
import { apiPost, errorText } from "@/lib/api";
import { FEEDBACK_NOTE, MAX_FEEDBACK, feedbackPage, feedbackProblem } from "@/lib/feedback";

/** "Send feedback", in the footer of every signed-in page. Text only; the admin reads it on the Admin page. */
export function FeedbackButton() {
  const { me } = useMe();
  const path = usePathname();
  const [open, setOpen] = useState(false);
  const [text, setText] = useState("");
  const [state, setState] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  if (!me) return null;
  const problem = feedbackProblem(text);
  const submit = async () => {
    setBusy(true);
    try {
      await apiPost("/feedback", { text: text.trim(), page: feedbackPage(path) });
      setText("");
      setState({ ok: true, text: "Thank you, your feedback was sent to the admin." });
    } catch (e) {
      setState({ ok: false, text: errorText(e) });
    } finally {
      setBusy(false);
    }
  };
  if (!open) {
    return (
      <> · <button className="underline" onClick={() => { setOpen(true); setState(null); }}>Send feedback</button></>
    );
  }
  return (
    <div className="mt-3 flex max-w-xl flex-col gap-2 rounded-md border border-border p-3 text-sm text-foreground">
      <label htmlFor="feedback-text" className="font-medium">Send feedback about this page ({feedbackPage(path)})</label>
      <p className="text-xs text-muted-foreground">{FEEDBACK_NOTE}</p>
      <textarea id="feedback-text" rows={4} maxLength={MAX_FEEDBACK + 200} value={text}
                onChange={(e) => { setText(e.target.value); setState(null); }}
                className="rounded border border-input bg-input/30 p-2" />
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <span className={text.trim().length > MAX_FEEDBACK ? "text-destructive" : "text-muted-foreground"}>
          {text.trim().length.toLocaleString("en-IN")} / {MAX_FEEDBACK.toLocaleString("en-IN")}
        </span>
        {text && problem && <span className="text-destructive">{problem}</span>}
        <span className="flex-1" />
        <Button size="sm" variant="outline" onClick={() => setOpen(false)}>Close</Button>
        <Button size="sm" disabled={busy || problem !== null} onClick={submit}>{busy ? "Sending…" : "Send"}</Button>
      </div>
      {state && (state.ok ? <p className="text-xs">{state.text}</p> : <ErrorBox message={state.text} />)}
    </div>
  );
}
