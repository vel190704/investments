"""`make release` refuses unless CI for the exact commit is green and production can fast-forward."""

import json

from app.tools import release as rel

SHA, PROD = "a" * 40, "b" * 40


def runner(overrides=None, prod_exists=True, runs=None):
    calls = []
    base = {
        ("gh", "auth", "status"): (0, "ok"),
        ("git", "rev-parse", "--abbrev-ref", "HEAD"): (0, "main\n"),
        ("git", "status", "--porcelain"): (0, ""),
        ("git", "fetch", "--quiet", "origin", "main"): (0, ""),
        ("git", "fetch", "--quiet", "origin", "production"): (0, "") if prod_exists else (128, "couldn't find ref"),
        ("git", "rev-parse", "HEAD"): (0, SHA + "\n"),
        ("git", "rev-parse", "origin/main"): (0, SHA + "\n"),
        ("git", "rev-parse", "--verify", "--quiet", "origin/production"): (0, PROD + "\n") if prod_exists else (1, ""),
        ("git", "merge-base", "--is-ancestor", PROD, SHA): (0, ""),
        ("git", "log", "--oneline", "--no-decorate", f"{PROD}..{SHA}" if prod_exists else SHA): (0, "aaaa fix\nbbbb feat\n"),
        ("git", "push", "origin", f"{SHA}:refs/heads/production"): (0, ""),
    }
    ci = runs if runs is not None else [{"headSha": SHA, "status": "completed", "conclusion": "success",
                                          "createdAt": "2026-10-18T10:00:00Z", "url": "https://ci/1"}]
    base[("gh", "run", "list", "--workflow", "ci.yml", "--commit", SHA, "--limit", "20",
          "--json", "status,conclusion,headSha,event,createdAt,url")] = (0, json.dumps(ci))
    base.update(overrides or {})

    def run(cmd):
        calls.append(tuple(cmd))
        return base.get(tuple(cmd), (99, f"unexpected command {cmd}"))
    return run, calls


def go(run):
    lines = []
    code = rel.release(run, confirm=lambda _p: True, out=lines.append)
    return code, "\n".join(lines)


def test_green_ci_fast_forwards_production_without_force():
    run, calls = runner()
    code, out = go(run)
    assert code == 0 and "Releasing 2 commit(s)" in out
    push = [c for c in calls if c[:2] == ("git", "push")]
    assert push == [("git", "push", "origin", f"{SHA}:refs/heads/production")] and "--force" not in push[0]


def test_first_release_creates_production():
    run, calls = runner(prod_exists=False)
    assert go(run)[0] == 0


def _refused(run, text):
    code, out = go(run)
    assert code == 1 and text in out, out


def test_refusals():
    _refused(runner({("gh", "auth", "status"): (127, "gh: not installed")})[0], "not installed")
    _refused(runner({("gh", "auth", "status"): (1, "")})[0], "gh auth login")
    _refused(runner({("git", "rev-parse", "--abbrev-ref", "HEAD"): (0, "feature\n")})[0], "from `main`")
    _refused(runner({("git", "status", "--porcelain"): (0, " M x.py\n")})[0], "uncommitted")
    _refused(runner({("git", "rev-parse", "origin/main"): (0, "c" * 40)})[0], "not the same as `origin/main`")
    _refused(runner({("git", "merge-base", "--is-ancestor", PROD, SHA): (1, "")})[0], "cannot be fast-forwarded")
    _refused(runner({("git", "rev-parse", "--verify", "--quiet", "origin/production"): (0, SHA)})[0], "already at")
    _refused(runner(runs=[])[0], "no CI run found")
    _refused(runner(runs=[{"headSha": SHA, "status": "in_progress", "conclusion": None, "createdAt": "x"}])[0],
             "still in_progress")
    _refused(runner(runs=[{"headSha": SHA, "status": "completed", "conclusion": "failure", "createdAt": "x"}])[0],
             "did not pass (failure)")
    # the LATEST run decides: an old success doesn't outweigh a newer failure for the same commit
    _refused(runner(runs=[{"headSha": SHA, "status": "completed", "conclusion": "success", "createdAt": "2026-10-18T09:00"},
                          {"headSha": SHA, "status": "completed", "conclusion": "failure", "createdAt": "2026-10-18T10:00"}])[0],
             "did not pass")


def test_cancelled_confirmation_pushes_nothing():
    run, calls = runner()
    assert rel.release(run, confirm=lambda _p: False, out=lambda _l: None) == 1
    assert not any(c[:2] == ("git", "push") for c in calls)
