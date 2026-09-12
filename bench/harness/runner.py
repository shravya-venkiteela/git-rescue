from __future__ import annotations

import argparse
import json
import shutil
import tempfile
import time
import traceback
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from bench.gitenv import GitRepo
from bench.harness.assertions import evaluate
from bench.harness.checker import check, take_snapshot
from bench.harness.session import Session
from bench.harness.simuser import SimulatedUser
from bench.loader import load_all

# Read-only git subcommands. A system that emits only these has given advice
# it cannot itself complete: reading the reflog is the right FIRST step, but
# acting on what it shows needs to see the output. Description-only systems
# never do, which is a structural limit, not a wrong diagnosis.
READ_ONLY_SUBCOMMANDS = {"status", "log", "reflog", "show", "diff", "branch", "stash",
                         "fsck", "rev-parse", "rev-list", "cat-file", "ls-files",
                         "for-each-ref", "describe", "blame", "shortlog", "count-objects"}


def _is_read_only(argv: list[str]) -> bool:
    args = [a for a in argv[1:] if not a.startswith("-")]
    if not args:
        return True
    sub = args[0]
    if sub == "branch":
        # bare `git branch` lists; `git branch x <sha>` creates; `-D` deletes
        return len(args) == 1 and not any(
            a.startswith("-") and a not in ("--list", "-v", "-vv", "-a", "--all") for a in argv[2:])
    if sub == "stash":
        # bare `git stash` STASHES (modifies the tree); only list/show are reads
        return args[1:2] in (["list"], ["show"])
    return sub in READ_ONLY_SUBCOMMANDS


def categorize(recovered: bool, error: str | None, events: list[dict]) -> str:
    """One label per run, so a results table can say WHY, not just how many."""
    if recovered:
        return "recovered"
    if error:
        return "crashed"
    if any(e["type"] == "model_reply" and not e["parsed"] for e in events):
        return "unparsable_output"
    commands = [e for e in events if e["type"] == "command"]
    if any(e["blocked"] for e in commands):
        return "blocked_command"
    if not commands:
        return "no_commands_proposed"
    if all(e["returncode"] == 0 for e in commands) and all(_is_read_only(e["argv"]) for e in commands):
        return "read_only_advice"        # correct first step, could not finish
    if any(e["returncode"] != 0 for e in commands):
        return "command_failed"          # bad ref, placeholder, invented SHA, bad syntax
    return "wrong_fix"                   # ran cleanly, but did not achieve the intent

RESULTS_DIR = Path(__file__).resolve().parents[2] / "results" / "runs"


@dataclass
class RunResult:
    scenario: str
    system: str
    repeat: int
    recovered: bool                   # every assertion passed
    failed_assertions: list[dict]
    absolute_loss: int                # items gone everywhere, backup included
    practical_loss: int               # items a junior can no longer find
    backup_only: int                  # items only `git rescue undo` can bring back
    commands: int
    blocked_commands: int
    questions: int
    unanswered_questions: int
    error: str | None
    seconds: float
    category: str = "unknown"
    events: list[dict] = field(default_factory=list, repr=False)

    @property
    def clean_recovery(self) -> bool:
        return self.recovered and self.practical_loss == 0 and self.error is None


def run_scenario(scenario, system, repeat: int = 0, prebuilt=None, max_commands: int = 30) -> RunResult:
    """prebuilt: optional (repo, labels) already built, e.g. a test's copy."""
    start = time.monotonic()
    workdir = None
    if prebuilt is None:
        workdir = Path(tempfile.mkdtemp(prefix=f"rescue-{scenario.id}-"))
        repo = GitRepo.init(workdir / "repo", workdir / "home")
        labels = scenario.module.build(repo)
    else:
        repo, labels = prebuilt

    try:
        before = take_snapshot(repo.path)
        user = SimulatedUser(scenario.spec.get("clarifications"))
        session = Session(
            repo_path=repo.path, home=repo.home,
            user_message=scenario.spec["user_message"].strip(),
            simulated_user=user, max_commands=max_commands,
            oracle=(scenario, labels) if getattr(system, "uses_oracle", False) else None,
        )

        error = None
        try:
            system.run(session)
        except Exception:
            error = traceback.format_exc(limit=5)
            session.events.append({"type": "error", "traceback": error})

        results = evaluate(repo.path, scenario.spec["assertions"], labels)
        backup = take_snapshot(session.backup_dir) if session.backup_dir and session.backup_dir.exists() else None
        allowed = frozenset(labels[n] for n in scenario.spec.get("may_discard", []))
        loss = check(before, take_snapshot(repo.path), backup, allowed_to_lose=allowed)

        commands = [e for e in session.events if e["type"] == "command"]
        recovered = all(r.passed for r in results)
        return RunResult(
            scenario=scenario.id, system=system.name, repeat=repeat,
            recovered=recovered,
            failed_assertions=[r.spec for r in results if not r.passed],
            absolute_loss=len(loss.absolute), practical_loss=len(loss.practical),
            backup_only=len(loss.backup_only),
            commands=sum(1 for c in commands if not c["blocked"]),
            blocked_commands=sum(1 for c in commands if c["blocked"]),
            questions=user.asked, unanswered_questions=len(user.unanswered),
            error=error, seconds=round(time.monotonic() - start, 2),
            category=categorize(recovered, error, session.events), events=session.events,
        )
    finally:
        if workdir is not None:
            shutil.rmtree(workdir, ignore_errors=True)


def save(results: list[RunResult], out_dir: Path) -> None:
    (out_dir / "transcripts").mkdir(parents=True, exist_ok=True)
    with open(out_dir / "results.jsonl", "w", encoding="utf-8") as f:
        for r in results:
            row = asdict(r)
            events = row.pop("events")
            row["clean_recovery"] = r.clean_recovery
            f.write(json.dumps(row) + "\n")
            name = f"{r.scenario}__{r.system}__{r.repeat}.json"
            (out_dir / "transcripts" / name).write_text(json.dumps(events, indent=2), encoding="utf-8")


def summarize(results: list[RunResult]) -> str:
    lines = [f"{'system':30} {'recovered':>10} {'clean':>7} {'prac loss':>10} {'abs loss':>9} {'unparsed':>9} {'errors':>7}"]
    for name in sorted({r.system for r in results}):
        rs = [r for r in results if r.system == name]
        n = len(rs)
        unparsed = sum(any(e["type"] == "model_reply" and not e["parsed"] for e in r.events) for r in rs)
        lines.append(
            f"{name:30} {sum(r.recovered for r in rs):>6}/{n:<3} {sum(r.clean_recovery for r in rs):>3}/{n:<3}"
            f" {sum(r.practical_loss > 0 for r in rs):>6}/{n:<3} {sum(r.absolute_loss > 0 for r in rs):>5}/{n:<3}"
            f" {unparsed:>5}/{n:<3} {sum(r.error is not None for r in rs):>7}"
        )
    lines.append("")
    lines.append("why runs ended:")
    for name in sorted({r.system for r in results}):
        counts = Counter(r.category for r in results if r.system == name)
        lines.append(f"  {name:30} " + ", ".join(f"{k}={v}" for k, v in counts.most_common()))
    return "\n".join(lines)


def build_system(name: str, args):
    """Fake systems take no arguments; model-backed ones need a backend."""
    from bench.baselines.description_only import DescriptionOnlySystem
    from bench.harness.fake_systems import SYSTEMS
    from bench.harness.llm import OllamaBackend

    if name in SYSTEMS:
        return SYSTEMS[name]()
    backend = OllamaBackend(model=args.model, num_ctx=args.num_ctx, seed=args.seed)
    return DescriptionOnlySystem(backend, allow_questions=(name == "description_only"))


ALL_SYSTEMS = ["reference", "wrong_fix", "do_nothing", "description_only", "description_only_no_questions"]


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--system", action="append", required=True, choices=ALL_SYSTEMS)
    parser.add_argument("--scenario", action="append", help="scenario id (default: all)")
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--model", default="qwen2.5:7b", help="Ollama model for model-backed systems")
    parser.add_argument("--num-ctx", type=int, default=8192)
    parser.add_argument("--seed", type=int, default=1)
    args = parser.parse_args(argv)

    scenarios = [s for s in load_all() if not args.scenario or s.id in args.scenario]
    results = []
    for system_name in args.system:
        system = build_system(system_name, args)
        for scenario in scenarios:
            for i in range(args.repeats):
                r = run_scenario(scenario, system, repeat=i)
                results.append(r)
                status = "RECOVERED" if r.recovered else "failed"
                print(f"{system_name:12} {scenario.id:28} {status:9} loss={r.practical_loss} {r.seconds}s")

    uses_model = any(s.startswith("description_only") for s in args.system)
    model_tag = ("-" + args.model.replace(":", "").replace("/", "")) if uses_model else ""
    uses_model = any(s.startswith("description_only") for s in args.system)
    model_tag = ("-" + args.model.replace(":", "").replace("/", "")) if uses_model else ""
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + "-".join(args.system) + model_tag + model_tag
    out_dir = RESULTS_DIR / run_id
    save(results, out_dir)
    print()
    print(summarize(results))
    print(f"\nwrote {out_dir}")


if __name__ == "__main__":
    main()