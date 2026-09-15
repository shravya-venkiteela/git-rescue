from __future__ import annotations
import json
from dataclasses import dataclass, field
from src.git_rescue import plan as plan_mod
from src.git_rescue import tools as tools_mod

SYSTEM_PROMPT = """You are git rescue. A developer's repository is in a bad state.

You investigate with read-only tools, then submit ONE plan. You cannot run
git commands yourself during investigation.

Reply with JSON only, either:
  {"tool": "<name>", "params": {...}, "why": "what you expect to learn"}
or:
  {"plan": PLAN}
or:
  {"ask": "a question only the user can answer"}

The plan looks like:
PLAN_SCHEMA

Rules that matter:
- Investigate before planning. Check operation_state first: an unfinished
  rebase or merge is a different problem from lost commits, and treating
  one as the other makes things worse.
- Every SHA or branch name in your plan must be one you have SEEN in tool
  output. Never invent one, and never use a placeholder.
- Say what is unrecoverable. Work that was never committed or staged cannot
  be recovered by any command. Saying so is the correct answer, not a
  failure; claiming to recover it is a lie.
- Mark each step safe, reversible or destructive. Your label is recorded but
  a separate table decides what actually happens, so be honest.
- Do not repeat a tool call you have already made; it returns the same thing.

Available tools:
TOOL_LIST"""


@dataclass
class AgentRun:
    plan: object = None
    investigations: list[dict] = field(default_factory=list)
    questions: list[str] = field(default_factory=list)
    rejected_plans: list[str] = field(default_factory=list)
    gave_up: str = ""


def _prompt() -> str:
    return SYSTEM_PROMPT.replace("PLAN_SCHEMA", plan_mod.SCHEMA_HELP).replace(
        "TOOL_LIST", tools_mod.describe())


class RescueAgent:
    """Produces a plan. Execution is someone else's job (executor.execute)."""

    def __init__(self, backend, budget: int = 12, max_plan_retries: int = 2,
                 max_iterations: int | None = None):
        self.backend = backend
        self.budget = budget
        self.max_plan_retries = max_plan_retries
        # Replies that are neither a tool call nor a plan (or repeats) do not
        # spend budget, so without this a confused model loops forever.
        self.max_iterations = max_iterations or (budget * 2 + 8)

    def investigate(self, repo, user_message: str, ask=None, log=None) -> AgentRun:
        run = AgentRun()
        history = [f"The user says: {user_message}"]
        used, seen_tools, retries = 0, set(), 0

        for iteration in range(self.max_iterations):
            left = self.budget - used
            if left <= 0:
                history.append("Your investigation budget is used up. Submit a plan now, "
                               "using only what you have already seen.")
            reply = self.backend.json_reply("\n\n".join(history), _prompt())
            if log is not None:
                log({"type": "model_reply", "parsed": reply.parsed is not None,
                     "attempts": reply.attempts, "seconds": round(reply.seconds, 2),
                     "text": reply.text, "transport_error": reply.transport_error})

            if reply.parsed is None:
                run.gave_up = (f"could not reach the model: {reply.transport_error}"
                               if reply.transport_error else "the model did not return usable JSON")
                return run

            if "plan" in reply.parsed:
                try:
                    run.plan = plan_mod.parse(reply.parsed["plan"])
                except plan_mod.PlanError as e:
                    retries += 1
                    run.rejected_plans.append(str(e))
                    if retries > self.max_plan_retries:
                        run.gave_up = f"the plan was malformed {retries} times: {e}"
                        return run
                    history.append(f"That plan was rejected: {e}\nFix it and submit again.")
                    continue
                if run.plan.is_question_only and ask is not None:
                    answers = [f"Q: {q}\nA: {ask(q)}" for q in run.plan.questions[:3]]
                    run.questions.extend(run.plan.questions[:3])
                    history.append("You asked:\n" + "\n".join(answers) + "\n\nNow submit a plan.")
                    run.plan = None
                    continue
                return run

            if "ask" in reply.parsed and ask is not None:
                question = str(reply.parsed["ask"])
                run.questions.append(question)
                history.append(f"You asked: {question}\nThe user replied: {ask(question)}")
                continue

            name = str(reply.parsed.get("tool", "")).strip()
            params = reply.parsed.get("params") or {}
            if not name:
                history.append("Reply with a tool call, a plan, or a question.")
                continue

            key = name + json.dumps(params, sort_keys=True)
            if key in seen_tools:
                history.append(f"You already called {name} with those parameters. "
                               f"It returns the same thing. Try something else or submit a plan.")
                continue
            seen_tools.add(key)

            if left <= 0:
                history.append("No budget left for tools. Submit a plan.")
                continue

            output = tools_mod.call(repo, name, params)
            used += 1
            run.investigations.append({"tool": name, "params": params, "output": output})
            if log is not None:
                log({"type": "tool_call", "tool": name, "params": params, "output": output})
            history.append(f"You ran the {name} tool.\nOutput:\n{output[:2000]}")

        run.gave_up = f"no plan after {self.max_iterations} exchanges"
        return run
