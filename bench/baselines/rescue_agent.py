from __future__ import annotations

from git_rescue.plan import split_command
from src.git_rescue import executor
from src.git_rescue.agent import RescueAgent


class RescueAgentSystem:
    uses_oracle = False

    def __init__(self, backend, budget: int = 12, name: str = "rescue_agent"):
        self.agent = RescueAgent(backend, budget=budget)
        self.name = name

    def run(self, session) -> None:
        run = self.agent.investigate(
            session.repo_path, session.user_message,
            ask=session.ask, log=session.events.append,
        )
        session.events.append({
            "type": "investigation",
            "tools": [i["tool"] for i in run.investigations],
            "rejected_plans": run.rejected_plans,
        })

        if run.plan is None:
            session.say(run.gave_up or "I could not produce a plan.")
            return

        plan = run.plan
        session.events.append({
            "type": "plan", "diagnosis": plan.diagnosis, "confidence": plan.confidence,
            "steps": [{"command": s.text, "purpose": s.purpose, "risk": s.claimed_risk} for s in plan.steps],
            "unrecoverable": plan.unrecoverable, "rotate_secrets_first": plan.rotate_secrets_first,
        })

        if not plan.steps:
            session.say(plan.diagnosis)
            return

        backup_root = session.home / "rescue-backups"
        outcome = executor.execute(session.repo_path, plan, confirm=lambda *a: True,
                                   backup_root=backup_root)
        if outcome.backup is not None:
            session.backup_dir = outcome.backup.repo_copy   # the checker reads this

        session.events.append({
            "type": "execution", "ok": outcome.ok, "reason": outcome.reason,
            "risk": outcome.review.get("overall"),
            "risk_disagreements": outcome.review.get("disagreements", []),
            "shadow_diff": outcome.shadow_diff, "verified": outcome.verified,
            "steps": [{"command": s.command, "returncode": s.returncode} for s in outcome.steps],
        })
        #The runner counts commands from Session events, and the executor runs
        #its own subprocesses, so mirror each executed step into the log.
        for step in (outcome.steps if outcome.ok or outcome.backup else []):
            session.events.append({"type": "command", "argv": split_command(step.command),
                                   "returncode": step.returncode, "stdout": "", "stderr": step.output,
                                   "seconds": 0.0, "blocked": None})

        note = plan.diagnosis
        if plan.unrecoverable:
            note += " Cannot be recovered: " + "; ".join(plan.unrecoverable) + "."
        if plan.rotate_secrets_first:
            note += " Rotate the exposed secret first: a committed secret must be treated as leaked."
        session.say(note if outcome.ok else f"{note} ({outcome.reason})")