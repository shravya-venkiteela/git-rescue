from __future__ import annotations

import argparse
import json
import shutil
import tempfile
import time
import traceback
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from bench.gitenv import GitRepo
from bench.harness.assertions import evaluate
from bench.harness.checker import check, take_snapshot
from bench.harness.session import Session
from bench.harness.simuser import SimulatedUser
from bench.loader import load_all

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
        return RunResult(
            scenario=scenario.id, system=system.name, repeat=repeat,
            recovered=all(r.passed for r in results),
            failed_assertions=[r.spec for r in results if not r.passed],
            absolute_loss=len(loss.absolute), practical_loss=len(loss.practical),
            backup_only=len(loss.backup_only),
            commands=sum(1 for c in commands if not c["blocked"]),
            blocked_commands=sum(1 for c in commands if c["blocked"]),
            questions=user.asked, unanswered_questions=len(user.unanswered),
            error=error, seconds=round(time.monotonic() - start, 2), events=session.events,
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
    lines = [f"{'system':14} {'recovered':>10} {'clean':>7} {'practical loss':>15} {'absolute loss':>14} {'errors':>7}"]
    for name in sorted({r.system for r in results}):
        rs = [r for r in results if r.system == name]
        n = len(rs)
        lines.append(
            f"{name:14} {sum(r.recovered for r in rs):>6}/{n:<3} {sum(r.clean_recovery for r in rs):>3}/{n:<3}"
            f" {sum(r.practical_loss > 0 for r in rs):>11}/{n:<3} {sum(r.absolute_loss > 0 for r in rs):>10}/{n:<3}"
            f" {sum(r.error is not None for r in rs):>7}"
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> None:
    from bench.harness.fake_systems import SYSTEMS

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--system", action="append", required=True, choices=sorted(SYSTEMS))
    parser.add_argument("--scenario", action="append", help="scenario id (default: all)")
    parser.add_argument("--repeats", type=int, default=1)
    args = parser.parse_args(argv)

    scenarios = [s for s in load_all() if not args.scenario or s.id in args.scenario]
    results = []
    for system_name in args.system:
        system = SYSTEMS[system_name]()
        for scenario in scenarios:
            for i in range(args.repeats):
                r = run_scenario(scenario, system, repeat=i)
                results.append(r)
                status = "RECOVERED" if r.recovered else "failed"
                print(f"{system_name:12} {scenario.id:28} {status:9} loss={r.practical_loss} {r.seconds}s")

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + "-".join(args.system)
    out_dir = RESULTS_DIR / run_id
    save(results, out_dir)
    print()
    print(summarize(results))
    print(f"\nwrote {out_dir}")


if __name__ == "__main__":
    main()