"""News helpers (pure): rule-based categories, headline de-duplication, company matching, feed ranking."""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timedelta

CATEGORIES = ["results", "order win / contract", "dividend", "board meeting", "acquisition / merger",
              "regulatory / legal", "management change", "rating action", "other"]

# First matching rule wins (order matters: "board meeting to consider results" -> board meeting).
RULES: list[tuple[str, tuple[str, ...]]] = [
    ("board meeting", ("board meeting", "meeting of the board", "outcome of board", "board of directors meeting")),
    ("dividend", ("dividend", "record date for", "interim payout")),
    ("results", ("financial result", "quarterly result", "q1 result", "q2 result", "q3 result", "q4 result",
                 "results for the quarter", "net profit", "profit rises", "profit falls", "profit jumps",
                 "profit drops", "earnings", "revenue rises", "revenue falls", "audited result", "unaudited result")),
    ("order win / contract", ("order win", "bags order", "wins order", "secures order", "order worth", "receives order",
                              "order from", "contract", "letter of award", "loa ", "orders worth", "bagged")),
    ("acquisition / merger", ("acquisition", "acquire", "acquires", "merger", "amalgamation", "takeover",
                              "scheme of arrangement", "stake sale", "buys stake", "demerger")),
    ("regulatory / legal", ("sebi", "rbi ", "penalty", "fine ", "court", "tribunal", "nclt", "show cause",
                            "litigation", "lawsuit", "regulator", "investigation", "tax demand", "gst demand",
                            "order passed by")),
    ("management change", ("appointment", "appoints", "resignation", "resigns", "ceo", "managing director",
                           "chief financial officer", "cessation", "re-appointment", "key managerial")),
    ("rating action", ("credit rating", "rating action", "upgrade", "downgrade", "crisil", "icra", "care ratings",
                       "india ratings", "reaffirm")),
]
STOPWORDS = {"the", "a", "an", "of", "for", "to", "in", "on", "and", "at", "by", "with", "its", "is", "as", "from",
             "ltd", "limited", "says", "said"}


def categorize(title: str, summary: str | None = None) -> str:
    text = f" {title} {summary or ''} ".lower()
    for category, needles in RULES:
        if any(n in text for n in needles):
            return category
    return "other"


def tokens(title: str) -> frozenset[str]:
    words = re.findall(r"[a-z0-9]+", title.lower())
    return frozenset(w for w in words if w not in STOPWORDS)


def dedupe_key(title: str) -> str:
    return hashlib.sha256(" ".join(sorted(tokens(title))).encode()).hexdigest()


def jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def is_near_duplicate(title: str, published: datetime, existing: list[tuple[str, datetime]],
                      threshold: float = 0.8, window_days: int = 3) -> bool:
    """existing: (title, published_at) of items for the same company."""
    t = tokens(title)
    for other, when in existing:
        if abs(published - when) <= timedelta(days=window_days) and jaccard(t, tokens(other)) >= threshold:
            return True
    return False


def company_patterns(name: str, symbol: str | None, aliases: tuple[str, ...] = ()) -> list[re.Pattern]:
    """Headline matchers: full company name (without Ltd/Limited) and the upper-case NSE symbol (>= 3 chars)."""
    core = re.sub(r"\b(ltd|limited|ltd\.)\b\.?", "", name, flags=re.I).strip(" .,")
    pats = [re.compile(r"(?<![A-Za-z0-9])" + re.escape(core) + r"(?![A-Za-z0-9])", re.I)] if len(core) >= 3 else []
    for a in aliases:
        pats.append(re.compile(r"(?<![A-Za-z0-9])" + re.escape(a) + r"(?![A-Za-z0-9])", re.I))
    if symbol and len(symbol) >= 3:
        pats.append(re.compile(r"(?<![A-Za-z0-9])" + re.escape(symbol.upper()) + r"(?![A-Za-z0-9])"))  # case-sensitive
    return pats


def mentions(title: str, patterns: list[re.Pattern]) -> bool:
    return any(p.search(title) for p in patterns)


def rank_feed(items: list[dict], exposure_by_isin: dict[str, float]) -> list[dict]:
    """Most portfolio-relevant first: company total exposure (desc), then newest first."""
    return sorted(items, key=lambda i: (-exposure_by_isin.get(i["isin"], 0.0), -i["published_ts"]))



def _n(count: int, one: str, many: str) -> str:
    return f"{count} {one if count == 1 else many}"


def empty_explanation(sources: list[dict], tracked: int, untracked: int, days: int) -> dict:
    """Why the news feed is empty. sources: last-refresh status per whole source
    ({source, ok, items_fetched, items_matched, message})."""
    failed = [{"source": x["source"], "message": x["message"]} for x in sources if not x["ok"]]
    ok = [x for x in sources if x["ok"]]
    fetched = sum(x.get("items_fetched") or 0 for x in ok)
    known = all(x.get("items_fetched") is not None for x in ok)  # rows from before counts were recorded: unknown
    items = _n(fetched, "item", "items") if known else "Items"
    tail = f" {_n(len(failed), 'source', 'sources')} failed (see below)." if failed else ""
    if not sources:
        kind, msg = "NOT_FETCHED", "News has not been fetched yet. Click Refresh."
    elif not ok:
        kind = "SOURCES_FAILED"
        msg = f"All {_n(len(failed), 'source', 'sources')} failed, so there was nothing to match. Reasons below."
    elif tracked == 0:
        kind = "NO_TRACKED_HOLDINGS"
        msg = (f"{items} fetched, none matched because no holdings are tracked: confirm ISINs "
               f"on Mappings ({_n(untracked, 'stock', 'stocks')} waiting).{tail}")
    elif known and fetched == 0:
        kind, msg = "NO_ITEMS", f"Sources answered but returned 0 items.{tail}"
    else:
        kind = "NO_MATCHES"
        msg = (f"{items} fetched from {_n(len(ok), 'source', 'sources')}; none were about your "
               f"{_n(tracked, 'tracked company', 'tracked companies')} in the last {days} days.{tail}")
    return {"kind": kind, "message": msg, "failed": failed}
