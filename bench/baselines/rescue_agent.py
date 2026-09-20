from __future__ import annotations

from src.git_rescue.plan import split_command
from src.git_rescue import executor
from src.git_rescue.agent import RescueAgent


class RescueAgentSystem:
    uses_oracle = False

    def __init__(self, backend, budget: int = 12, name: str = "rescue_agent", max_replans: int = 1):
        self.agent = RescueAgent(backend, budget=budget)
        self.name = name
        #When a plan fails on the COPY, nothing real has changed, and the error
        #says exactly what was wrong. Stopping there threw away plans that
        #needed one fix (a wrong dangling SHA, a needless clean-up step).
        #Replans are logged, so results can say which recoveries needed one.
        self.max_replans = max_replans

    def run(self, session) -> None:
        run = self.agent.investigate(
            session.repo_path, session.user_message,
            ask=session.ask, log=session.events.append,
        )
        while True:
            outcome = self._attempt(session, run)
            retryable = outcome is not None and not outcome.ok and not outcome.ran_for_real
            if not retryable or run.replans >= self.max_replans:
                return
            session.events.append({"type": "replan", "reason": outcome.reason})
            run = self.agent.investigate(
                session.repo_path, session.user_message,
                ask=session.ask, log=session.events.append, resume=run,
                feedback=(f"Your plan was tried on a COPY of the repository and failed, so "
                          f"nothing real was changed:\n{outcome.reason}\n"
                          f"Give a corrected plan."),
            )

    def _attempt(self, session, run):
        """Record and execute one plan. Returns the executor's outcome, or
        None when there was nothing to execute."""
        session.events.append({
            "type": "investigation",
            "tools": [i["tool"] for i in run.investigations],
            "rejected_plans": run.rejected_plans,
        })

        if run.plan is None:
            session.say(run.gave_up or "I could not produce a plan.")
            return None

        plan = run.plan
        session.events.append({
            "type": "plan", "diagnosis": plan.diagnosis, "confidence": plan.confidence,
            "steps": [{"command": s.text, "purpose": s.purpose, "risk": s.claimed_risk} for s in plan.steps],
            "unrecoverable": plan.unrecoverable, "rotate_secrets_first": plan.rotate_secrets_first,
        })

        if not plan.steps:
            session.say(plan.diagnosis)
            return None

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
        return outcome