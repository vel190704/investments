// "Send feedback": limits shared by the form and its tests. The backend enforces the same (app/services/feedback.py).

export const MAX_FEEDBACK = 2000;
export const FEEDBACK_NOTE =
  "Please don't include account numbers, PAN, passwords or personal financial figures. Describe what you saw and on which page.";

/** Why the text can't be sent yet, or null when it can. */
export function feedbackProblem(text: string): string | null {
  const n = text.trim().length;
  if (n === 0) return "Write something first.";
  if (n > MAX_FEEDBACK) return `At most ${MAX_FEEDBACK.toLocaleString("en-IN")} characters (this is ${n.toLocaleString("en-IN")}).`;
  return null;
}

/** The page path only: never the query string, which can carry symbols or ids. */
export function feedbackPage(pathname: string): string {
  return pathname.split("?")[0].split("#")[0] || "/";
}
