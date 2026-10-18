"""`make release`: fast-forward the `production` branch to `main`, but only when CI for that exact commit is green.

The free-plan-safe alternative to branch protection (docs/DEPLOY.md §17). Vercel and Render deploy production from
the `production` branch only; everything on `main` goes to preview. This tool refuses unless:
  1. `gh` (GitHub CLI) is installed and signed in;
  2. you are on `main` with a clean working tree;
  3. local `main` equals `origin/main` (pushed, nothing newer upstream);
  4. `production` can fast-forward to it (never a force push);
  5. the latest CI workflow run for this exact commit completed with conclusion "success".
It then shows the commits that will ship, asks for confirmation (or --yes), and pushes `<sha>:production`.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections.abc import Callable

WORKFLOW = "ci.yml"
Runner = Callable[[list[str]], tuple[int, str]]


def sh(cmd: list[str]) -> tuple[int, str]:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True)
    except FileNotFoundError:
        return 127, f"{cmd[0]}: not installed"
    return p.returncode, (p.stdout or "") + (p.stderr or "")


class Refused(Exception):
    pass


def check(run: Runner = sh) -> dict:
    """All the preconditions; returns {sha, production_sha, commits} or raises Refused with the reason."""
    code, out = run(["gh", "auth", "status"])
    if code == 127:
        raise Refused("the GitHub CLI `gh` is not installed: https://cli.github.com, then `gh auth login`")
    if code != 0:
        raise Refused("`gh` is not signed in: run `gh auth login`")
    code, branch = run(["git", "rev-parse", "--abbrev-ref", "HEAD"])
    if branch.strip() != "main":
        raise Refused(f"releases are made from `main` (you are on {branch.strip()!r})")
    code, status = run(["git", "status", "--porcelain"])
    if status.strip():
        raise Refused("the working tree has uncommitted changes")
    code, out = run(["git", "fetch", "--quiet", "origin", "main"])
    if code != 0:
        raise Refused(f"`git fetch` failed: {out.strip()[:200]}")
    run(["git", "fetch", "--quiet", "origin", "production"])  # absent before the first release: that's fine
    _, sha = run(["git", "rev-parse", "HEAD"])
    _, remote = run(["git", "rev-parse", "origin/main"])
    sha, remote = sha.strip(), remote.strip()
    if sha != remote:
        raise Refused("local `main` is not the same as `origin/main`: push (or pull) first, then wait for CI")
    code, prod = run(["git", "rev-parse", "--verify", "--quiet", "origin/production"])
    prod = prod.strip() if code == 0 else None
    if prod == sha:
        raise Refused("`production` is already at this commit: nothing to release")
    if prod is not None:
        code, _ = run(["git", "merge-base", "--is-ancestor", prod, sha])
        if code != 0:
            raise Refused("`production` has commits that are not on `main`: it cannot be fast-forwarded "
                          "(fix this by hand; never force-push production)")
    code, out = run(["gh", "run", "list", "--workflow", WORKFLOW, "--commit", sha, "--limit", "20",
                     "--json", "status,conclusion,headSha,event,createdAt,url"])
    if code != 0:
        raise Refused(f"could not read CI runs: {out.strip()[:200]}")
    runs = sorted((r for r in json.loads(out or "[]") if r.get("headSha") == sha),
                  key=lambda r: r.get("createdAt", ""), reverse=True)
    if not runs:
        raise Refused(f"no CI run found for {sha[:12]}: has it been pushed, and has CI started?")
    latest = runs[0]
    if latest.get("status") != "completed":
        raise Refused(f"CI for {sha[:12]} is still {latest.get('status')}: wait for it ({latest.get('url', '')})")
    if latest.get("conclusion") != "success":
        raise Refused(f"CI for {sha[:12]} did not pass ({latest.get('conclusion')}): {latest.get('url', '')}")
    rng = f"{prod}..{sha}" if prod else sha
    _, log = run(["git", "log", "--oneline", "--no-decorate", rng])
    return {"sha": sha, "production_sha": prod, "commits": [line for line in log.splitlines() if line.strip()],
            "ci_url": latest.get("url")}


def release(run: Runner = sh, confirm: Callable[[str], bool] | None = None, out=print) -> int:
    try:
        info = check(run)
    except Refused as e:
        out(f"release refused: {e}")
        return 1
    out(f"CI passed for {info['sha'][:12]} ({info.get('ci_url') or 'GitHub Actions'}).")
    out(f"Releasing {len(info['commits'])} commit(s) to production:")
    for line in info["commits"][:30]:
        out(f"  {line}")
    if confirm is not None and not confirm("Fast-forward `production` to this commit? Type yes: "):
        out("cancelled")
        return 1
    code, msg = run(["git", "push", "origin", f"{info['sha']}:refs/heads/production"])  # no --force, ever
    if code != 0:
        out(f"push failed: {msg.strip()[:300]}")
        return 1
    out("Pushed. Vercel and Render now deploy `production`; then run `make smoke` against preview if not done.")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--yes", action="store_true", help="don't ask for confirmation")
    args = ap.parse_args(argv)
    confirm = None if args.yes else (lambda prompt: input(prompt).strip().lower() == "yes")
    return release(confirm=confirm)


if __name__ == "__main__":
    sys.exit(main())
