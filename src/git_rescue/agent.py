from __future__ import annotations

import json
from dataclasses import dataclass, field

from src.git_rescue import plan as plan_mod
from src.git_rescue import tools as tools_mod

INVESTIGATE_PROMPT = """You are git rescue. A developer's repository is broken.
You are still INVESTIGATING. Look before you conclude: commits are often
recoverable from the reflog or from dangling objects even when they seem gone.

Reply with JSON only, and keep it short:
  {"tool": "<name>", "params": {...}}
or {"ask": "a question only the user can answer"}
or {"ready": true} once you have seen enough to fix it.

Start with operation_state: an unfinished rebase or merge is a different
problem from lost commits. Do not repeat a tool call.

Tools:
TOOL_LIST"""

PLAN_PROMPT = """You are git rescue. You have finished investigating and must
now give the plan that fixes this repository.

Reply with JSON only:
PLAN_SCHEMA

Rules:
- Every SHA and branch name must be one you SAW in the tool output above.
  Never invent one, and never use a placeholder like <sha>.
- Say what is unrecoverable. Work never committed or staged cannot be
  recovered by any command, and saying so is the correct answer; claiming
  to recover it is a lie.
- Mark each step safe, reversible or destructive. Your label is recorded, but
  a separate table decides what actually happens, so be honest."""


@dataclass
class AgentRun:
    plan: object = None
    investigations: list[dict] = field(default_factory=list)
    questions: list[str] = field(default_factory=list)
    rejected_plans: list[str] = field(default_factory=list)
    gave_up: str = ""


def _investigate_prompt() -> str:
    return INVESTIGATE_PROMPT.replace("TOOL_LIST", tools_mod.describe())


def _plan_prompt() -> str:
    return PLAN_PROMPT.replace("PLAN_SCHEMA", plan_mod.SCHEMA_HELP)


def _prompt() -> str:            #kept for callers that want the whole thing
    return _investigate_prompt() + "\n\n" + _plan_prompt()


class RescueAgent:
    """Produces a plan. Execution is someone else's job (executor.execute)."""

    def __init__(self, backend, budget: int = 12, max_plan_retries: int = 2,
                 max_iterations: int | None = None, min_investigations: int = 1,
                 max_questions: int = 3):
        self.backend = backend
        self.budget = budget
        self.max_plan_retries = max_plan_retries
        #Replies that are neither a tool call nor a plan (or repeats) do not
        #spend budget, so without this a confused model loops forever.
        self.max_iterations = max_iterations or (budget * 2 + 8)
        #A model asked for a plan on turn one produced a confident WRONG
        #diagnosis ("the commits are unrecoverable") while they sat in the
        #reflog. An agent that does not look is just B1 with extra steps.
        self.min_investigations = min_investigations
        #Questions need a budget for the same reason tools do.
        self.max_questions = max_questions

    def investigate(self, repo, user_message: str, ask=None, log=None) -> AgentRun:
        run = AgentRun()
        history = [f"The user says: {user_message}"]
        used, seen_tools, retries, ready = 0, set(), 0, False
        asked: dict[str, str] = {}

        for iteration in range(self.max_iterations):
            planning = used >= self.budget or ready
            if planning:
                prompt = _plan_prompt()
                ask_for = ("Your investigation budget is used up. " if used >= self.budget else "")
                history.append(ask_for + "Give the plan now, using only what you have seen above.")
            else:
                prompt = _investigate_prompt()
            reply = self.backend.json_reply("\n\n".join(history), prompt)
            if planning:
                history.pop()
            if log is not None:
                log({"type": "model_reply", "planning": planning, "parsed": reply.parsed is not None,
                     "attempts": reply.attempts, "seconds": round(reply.seconds, 2),
                     "text": reply.text, "transport_error": reply.transport_error})

            if reply.parsed is None:
                run.gave_up = (f"could not reach the model: {reply.transport_error}"
                               if reply.transport_error else "the model did not return usable JSON")
                return run

            if reply.parsed.get("ready"):
                ready = True
                continue

            if "plan" in reply.parsed:
                if used < self.min_investigations:
                    #Looking is not optional: a plan made without evidence is
                    #a guess, and this scenario set is full of problems that
                    #look unrecoverable until you check the reflog.
                    history.append(f"You have not investigated yet. Use the tools first "
                                   f"(at least {self.min_investigations}), then give a plan.")
                    run.rejected_plans.append("submitted a plan before investigating")
                    ready = False
                    continue
                try:
                    run.plan = plan_mod.parse(reply.parsed["plan"])
                except plan_mod.PlanError as e:
                    retries += 1
                    run.rejected_plans.append(str(e))
                    if retries > self.max_plan_retries:
                        run.gave_up = f"the plan was malformed {retries} times: {e}"
                        return run
                    history.append(f"That plan was rejected: {e}\nFix it and submit again.")
                    ready = True
                    continue
                if run.plan.is_question_only and ask is not None:
                    answers = [f"Q: {q}\nA: {ask(q)}" for q in run.plan.questions[:3]]
                    run.questions.extend(run.plan.questions[:3])
                    history.append("You asked:\n" + "\n".join(answers))
                    run.plan = None
                    ready = True
                    continue
                return run

            if "ask" in reply.parsed and ask is not None:
                question = str(reply.parsed["ask"]).strip()
                if question in asked:
                    history.append(f"You already asked that. The answer was still: "
                                   f"{asked[question]}\nUse a tool instead.")
                    continue
                if len(asked) >= self.max_questions:
                    history.append("You have asked enough questions. The repository itself "
                                   "has the answers: use the tools.")
                    continue
                answer = ask(question)
                asked[question] = answer
                run.questions.append(question)
                history.append(f"You asked: {question}\nThe user replied: {answer}")
                #An answer that teaches nothing must not invite the same
                #question again in different words.
                if "don't know" in answer.lower():
                    history.append("The user cannot answer that. Look in the repository instead.")
                continue

            name = str(reply.parsed.get("tool", "")).strip()
            params = reply.parsed.get("params") or {}
            if not name:
                history.append("Reply with a tool call, or {\"ready\": true} to give your plan.")
                continue

            key = name + json.dumps(params, sort_keys=True, default=str)
            if key in seen_tools:
                untried = sorted(set(tools_mod.TOOLS) - {t["tool"] for t in run.investigations})
                suggestion = f" Not tried yet: {', '.join(untried[:5])}." if untried else ""
                history.append(f"You already called {name} with those parameters and it gave the "
                               f"same answer.{suggestion} Or reply {{\"ready\": true}} to plan.")
                continue
            if used >= self.budget:
                history.append("No investigation budget left. Give the plan now.")
                ready = True
                continue
            output = tools_mod.call(repo, name, params)
            #A call that FAILED teaches nothing, so it must not be locked out:
            #a real run wasted 11 exchanges after `reflog ref=feature` errored
            #(the branch was deleted) because the repeat guard then refused
            #every retry, including the corrected one.
            failed = output.startswith("ERROR:")
            if not failed:
                seen_tools.add(key)
                used += 1
            if not failed:
                run.investigations.append({"tool": name, "params": params, "output": output})
            if log is not None:
                log({"type": "tool_call", "tool": name, "params": params,
                     "output": output, "failed": failed})
            history.append(f"{name} says:\n{output[:2000]}")

        run.gave_up = f"no plan after {self.max_iterations} exchanges"
        return run
