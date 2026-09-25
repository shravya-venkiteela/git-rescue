from __future__ import annotations
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from .gitenv import NON_INTERACTIVE, env_for
from . import backup as backup_mod
from . import risk as risk_mod


@dataclass
class StepResult:
    command: str
    returncode: int
    output: str
    ran: bool = True


@dataclass
class Outcome:
    ok: bool
    reason: str
    steps: list[StepResult] = field(default_factory=list)
    review: dict = field(default_factory=dict)
    shadow_diff: str = ""
    backup: object = None
    verified: bool = True
    #True once any step has run on the REAL repository. Until then a failure
    #(blocked, fails on the copy, not confirmed) left the repository untouched.
    ran_for_real: bool = False


def _env(date: str | None = None):
    env = env_for(Path(tempfile.gettempdir()) / "git-rescue-exec-home")
    env.update(NON_INTERACTIVE)
    if date:
        #Same clock for the preview and the real run, so a step that makes a
        #commit (cherry-pick, merge, commit) makes the SAME commit both times.
        #Without this a correct plan failed "differs from the preview" because
        #the real cherry-pick ran one second later. Cherry-pick and rebase keep
        #the original author date regardless; only new timestamps are pinned.
        env["GIT_AUTHOR_DATE"] = env["GIT_COMMITTER_DATE"] = date
    return env


def _run(repo: Path, argv: list[str], date: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(argv, cwd=repo, env=_env(date), stdin=subprocess.DEVNULL,
                          capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=60)


def fingerprint(repo: Path) -> str:
    """What the repository looks like now: refs, HEAD, status. Comparing two
    fingerprints is how the shadow run is checked against the real one."""
    parts = []
    for argv in (["git", "for-each-ref", "--format=%(refname) %(objectname)"],
                 ["git", "status", "--porcelain=v2", "--branch"],
                 ["git", "stash", "list", "--format=%gd %H"]):
        env = _env()
        env["GIT_OPTIONAL_LOCKS"] = "0"
        p = subprocess.run(argv, cwd=repo, env=env, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=30)
        parts.append(p.stdout.strip())
    return "\n".join(parts)


def _apply(repo: Path, steps, date: str | None = None) -> tuple[list[StepResult], bool]:
    results = []
    for step in steps:
        p = _run(repo, step.argv, date)
        output = (p.stdout + p.stderr).strip()
        results.append(StepResult(step.text, p.returncode, output))
        if p.returncode != 0:
            return results, False        # later steps assume this one worked
    return results, True


def shadow_run(repo: Path, steps, date: str | None = None) -> tuple[list[StepResult], bool, str]:
    """Run the plan on a copy and report what changed. This is the dry run."""
    with tempfile.TemporaryDirectory(prefix="git-rescue-shadow-") as tmp:
        copy = Path(tmp) / "repo"
        shutil.copytree(repo, copy, symlinks=True)
        before = fingerprint(copy)
        results, ok = _apply(copy, steps, date)
        after = fingerprint(copy)
        return results, ok, _diff(before, after)


def _diff(before: str, after: str) -> str:
    old, new = set(before.splitlines()), set(after.splitlines())
    lines = [f"- {l}" for l in sorted(old - new)] + [f"+ {l}" for l in sorted(new - old)]
    return "\n".join(lines) or "(nothing would change)"


def execute(repo: Path, plan, confirm=None, backup_root: Path | None = None) -> Outcome:
    """Run a plan against a real repository.

    confirm: called with (plan, review, shadow_diff) and must return True.
             Without it, nothing destructive runs.
    """
    review = risk_mod.review(plan)
    if review["blocked"]:
        names = ", ".join(r["command"] for r in review["blocked"])
        return Outcome(False, f"refusing to run blocked command(s): {names}", review=review)
    if not plan.steps:
        return Outcome(False, "the plan has no steps to run", review=review)

    date = f"{int(time.time())} +0000"
    shadow_steps, shadow_ok, diff = shadow_run(repo, plan.steps, date)
    if not shadow_ok:
        failed = next(s for s in shadow_steps if s.returncode != 0)
        return Outcome(False, f"the plan fails on a copy, so it was not run here: "
                              f"{failed.command} -> {failed.output.splitlines()[0] if failed.output else 'error'}",
                       steps=shadow_steps, review=review, shadow_diff=diff)

    destructive = review["overall"] == risk_mod.DESTRUCTIVE
    if destructive and confirm is None:
        return Outcome(False, "this plan is destructive and no confirmation was given",
                       review=review, shadow_diff=diff)
    if confirm is not None and not confirm(plan, review, diff):
        return Outcome(False, "the user did not confirm", review=review, shadow_diff=diff)

    saved = backup_mod.create(repo, note=plan.diagnosis, root=backup_root) if destructive else None

    before = fingerprint(repo)
    results, ok = _apply(repo, plan.steps, date)
    verified = _diff(before, fingerprint(repo)) == diff

    if not ok:
        return Outcome(False, "a step failed even though the copy succeeded; use `git rescue undo`",
                       steps=results, ran_for_real=True, review=review, shadow_diff=diff, backup=saved, verified=False)
    if not verified:
        return Outcome(False, "the result differs from the preview; use `git rescue undo`",
                       steps=results, ran_for_real=True, review=review, shadow_diff=diff, backup=saved, verified=False)
    return Outcome(True, "plan applied", steps=results, ran_for_real=True, review=review, shadow_diff=diff, backup=saved)