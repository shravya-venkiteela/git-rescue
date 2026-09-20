import pytest

from bench.baselines.rescue_agent import RescueAgentSystem
from bench.harness.llm import ScriptedBackend
from bench.harness.runner import run_scenario
from bench.harness.simuser import SimulatedUser
from bench.loader import load_all
from src.git_rescue.agent import RescueAgent

SCENARIOS = {s.id: s for s in load_all()}
FEAT2 = "ced977baba6b18af909e0f498199e03705fce144"


def plan_reply(command, risk="reversible", **extra):
    return {"plan": {"diagnosis": "d", "confidence": "high",
                     "steps": [{"command": command, "purpose": "p", "risk": risk}], **extra}}


def agent_run(scenario_id, replies, **kwargs):
    """min_investigations defaults to 0 here: these tests are about planning
    and execution. The investigate-first rule has its own tests."""
    kwargs.setdefault("min_investigations", 0)
    backend = ScriptedBackend(replies)
    system = RescueAgentSystem(backend, **{k: v for k, v in kwargs.items() if k == "budget"})
    system.agent.min_investigations = kwargs["min_investigations"]
    return run_scenario(SCENARIOS[scenario_id], system), backend


def investigate(scenario_id, replies, built, ask=None, **kwargs):
    """ask defaults to the scenario's own simulated user, so question
    handling is exercised the same way the benchmark exercises it."""
    kwargs.setdefault("min_investigations", 0)
    scenario = SCENARIOS[scenario_id]
    repo, labels = built(scenario)
    if ask is None:
        ask = SimulatedUser(scenario.spec.get("clarifications")).answer
    backend = ScriptedBackend(replies)
    return RescueAgent(backend, **kwargs).investigate(repo.path, "help", ask=ask), backend, labels


def test_the_agent_investigates_then_recovers():
    r, _ = agent_run("deleted-branch-01", [
        {"tool": "operation_state", "why": "is something unfinished?"},
        {"tool": "reflog", "params": {"count": 10}, "why": "find the lost commits"},
        plan_reply(f"git branch feature {FEAT2}"),
    ])
    assert r.recovered and r.practical_loss == 0 and r.category == "recovered"


def test_tool_output_reaches_the_model(built):
    """B1's structural limit was never seeing output. This is the fix."""
    _, backend, labels = investigate("deleted-branch-01", [
        {"tool": "reflog", "params": {"count": 10}, "why": "look"},
        plan_reply(f"git branch feature {FEAT2}"),
    ], built)
    assert labels["feat2"][:7] in backend.calls[1]


def test_a_malformed_plan_is_rejected_with_a_reason_and_retried(built):
    run, backend, _ = investigate("deleted-branch-01", [
        plan_reply("git branch feature <sha>"),      # placeholder
        plan_reply(f"git branch feature {FEAT2}"),
    ], built)
    assert run.rejected_plans and "placeholder" in run.rejected_plans[0]
    assert run.plan is not None and "feature" in run.plan.steps[0].text
    assert "rejected" in backend.calls[1]


def test_the_agent_gives_up_rather_than_submitting_junk(built):
    run, _, _ = investigate("deleted-branch-01",
                            [plan_reply("git branch feature <sha>")] * 5, built, max_plan_retries=2)
    assert run.plan is None and "malformed" in run.gave_up


def test_the_investigation_budget_is_enforced(built):
    tools = [{"tool": "log", "params": {"count": n}, "why": "look"} for n in range(1, 10)]
    run, _, _ = investigate("deleted-branch-01", tools + [plan_reply(f"git branch feature {FEAT2}")],
                            built, budget=3)
    assert len(run.investigations) == 3


def test_a_repeated_tool_call_is_refused(built):
    """B2 spent 47% of its budget repeating commands."""
    run, _, _ = investigate("deleted-branch-01", [
        {"tool": "status", "why": "look"},
        {"tool": "status", "why": "look again"},
        plan_reply(f"git branch feature {FEAT2}"),
    ], built)
    assert len(run.investigations) == 1


def test_an_invented_sha_is_caught_before_execution():
    """B2 read the right SHA and used a different one. The shadow run
    catches that here, and the repository is never touched."""
    r, _ = agent_run("deleted-branch-01", [plan_reply("git branch feature 1234567890" * 4)])
    assert not r.recovered and r.practical_loss == 0
    execution = [e for e in r.events if e["type"] == "execution"][0]
    assert "fails on a copy" in execution["reason"]


def test_a_destructive_plan_is_backed_up_so_nothing_is_lost():
    """detached-head has an untracked notes.txt that clean -fd destroys.
    With a backup the checker must report no practical loss."""
    r, _ = agent_run("detached-head-01", [
        {"plan": {"diagnosis": "start clean", "confidence": "high", "steps": [
            {"command": "git reset --hard HEAD~1", "purpose": "p", "risk": "safe"},
            {"command": "git clean -fdq", "purpose": "p", "risk": "safe"}]}},
    ])
    assert r.practical_loss == 0 and r.absolute_loss == 0, "the backup should cover the damage"
    assert r.backup_only > 0, "and the checker should say it is only in the backup"


def test_a_blocked_command_stops_the_plan():
    r, _ = agent_run("wrong-branch-01", [plan_reply("git push --force origin main")])
    execution = [e for e in r.events if e["type"] == "execution"][0]
    assert not execution["ok"] and "blocked" in execution["reason"]


def test_the_models_risk_label_is_overridden_and_recorded():
    r, _ = agent_run("detached-head-01", [plan_reply("git reset --hard HEAD~1", risk="safe")])
    execution = [e for e in r.events if e["type"] == "execution"][0]
    assert execution["risk"] == "destructive"
    assert any("model said safe" in d for d in execution["risk_disagreements"])


def test_unrecoverable_work_is_reported_not_hidden():
    """Saying work is gone is the correct answer, not a failure."""
    r, _ = agent_run("deleted-branch-01", [
        plan_reply(f"git branch feature {FEAT2}", unrecoverable=["the uncommitted edits to app.py"]),
    ])
    said = [e for e in r.events if e["type"] == "say"][0]["message"]
    assert "Cannot be recovered" in said and "app.py" in said


def test_a_secret_prompts_rotation_first():
    r, _ = agent_run("deleted-branch-01", [
        plan_reply(f"git branch feature {FEAT2}", rotate_secrets_first=True),
    ])
    said = [e for e in r.events if e["type"] == "say"][0]["message"]
    assert "Rotate the exposed secret first" in said


def test_questions_are_answered_and_then_a_plan_follows():
    r, backend = agent_run("deleted-branch-01", [
        {"ask": "What was the deleted branch name?"},
        plan_reply(f"git branch feature {FEAT2}"),
    ])
    assert r.questions == 1 and r.recovered
    assert "feature" in backend.calls[1]


def test_unparsable_output_is_a_clean_failure():
    r, _ = agent_run("deleted-branch-01", ["here is some prose"])
    assert not r.recovered and r.error is None and r.category == "unparsable_output"

@pytest.mark.parametrize("params", ["count=10", ["count", 10], 10, None])
def test_params_of_any_shape_do_not_crash_the_run(built, params):
    """A real model sent params as a string and crashed the agent. Any
    shape the model invents must be tolerated, not trusted."""
    run, _, _ = investigate("deleted-branch-01", [
        {"tool": "reflog", "params": params, "why": "look"},
        plan_reply(f"git branch feature {FEAT2}"),
    ], built)
    assert run.plan is not None, f"params={params!r} broke the run"


def test_the_agent_stops_instead_of_looping_forever(built):
    """Replies that are neither a tool call nor a plan do not spend the tool
    budget, so a separate cap is what actually ends the run."""
    run, backend, _ = investigate("deleted-branch-01", [{"why": "thinking"}] * 200, built, budget=4)
    assert run.plan is None and "no plan after" in run.gave_up
    assert len(backend.calls) <= 4 * 2 + 8


def test_an_unreachable_backend_is_not_blamed_on_the_model():
    """A dead Ollama server produced 'unparsable_output', which reads as a
    bad model. It is a different failure and must be labelled as one."""
    class Dead:
        name = "dead"
        def json_reply(self, prompt, system=None):
            from bench.harness.llm import Reply
            return Reply("", None, 3, 0.0, ["<request failed>"], transport_error="connection refused")
    r = run_scenario(SCENARIOS["deleted-branch-01"], RescueAgentSystem(Dead()))
    assert r.category == "backend_unavailable"
    assert "could not reach the model" in [e for e in r.events if e["type"] == "say"][0]["message"]


def test_a_plan_submitted_without_looking_is_refused(built):
    """A real run: asked for a plan on turn one, the model declared the
    commits unrecoverable while they sat in the reflog. An agent that does
    not look is B1 with extra steps."""
    run, _, _ = investigate("deleted-branch-01", [
        plan_reply(f"git branch feature {FEAT2}"),          #no investigation yet
        {"tool": "reflog", "params": {"count": 10}},
        plan_reply(f"git branch feature {FEAT2}"),
    ], built, min_investigations=1)
    assert "before investigating" in run.rejected_plans[0]
    assert run.plan is not None and len(run.investigations) == 1


def test_ready_switches_to_the_planning_prompt(built):
    """Investigation replies are short and cheap; only the final plan pays
    for the long schema."""
    run, backend, _ = investigate("deleted-branch-01", [
        {"tool": "reflog", "params": {"count": 5}},
        {"ready": True},
        plan_reply(f"git branch feature {FEAT2}"),
    ], built, min_investigations=1)
    assert run.plan is not None and len(backend.calls) == 3


def test_the_budget_forces_a_plan_even_without_ready(built):
    run, _, _ = investigate("deleted-branch-01", [
        {"tool": "status"},
        plan_reply(f"git branch feature {FEAT2}"),
    ], built, budget=1, min_investigations=1)
    assert run.plan is not None and len(run.investigations) == 1


def test_a_repeated_question_is_refused(built):
    """A real run spent all 20 exchanges asking the same question. Every
    channel the model has needs a repeat guard, not just tool calls."""
    run, backend, _ = investigate("deleted-branch-01", [
        {"ask": "Did you use --force or --delete?"},
        {"ask": "Did you use --force or --delete?"},
        {"tool": "reflog", "params": {"count": 10}},
        plan_reply(f"git branch feature {FEAT2}"),
    ], built, min_investigations=1)
    assert len(run.questions) == 1 and run.plan is not None
    assert "already asked" in backend.calls[2]


def test_questions_are_budgeted(built):
    replies = [{"ask": f"question number {n}?"} for n in range(1, 8)]
    run, backend, _ = investigate("deleted-branch-01",
                                  replies + [{"tool": "status"}, plan_reply(f"git branch feature {FEAT2}")],
                                  built, max_questions=2, min_investigations=1)
    assert len(run.questions) == 2
    assert "asked enough questions" in backend.calls[3]


def test_an_unanswerable_question_points_the_model_at_the_tools(built):
    """'I don't know' teaches nothing, so the model must be told to look."""
    run, backend, _ = investigate("deleted-branch-01", [
        {"ask": "What colour is your terminal?"},          #no clarification matches
        {"tool": "reflog", "params": {"count": 10}},
        plan_reply(f"git branch feature {FEAT2}"),
    ], built, min_investigations=1)
    assert "Look in the repository instead" in backend.calls[1]


def test_a_failed_tool_call_can_be_retried_with_different_parameters(built):
    """A real run called reflog on a DELETED branch, which errors. The repeat
    guard then refused all 11 retries, including the corrected one, and the
    run died with no plan. A call that failed teaches nothing, so it must
    not be remembered as tried."""
    run, _, _ = investigate("deleted-branch-01", [
        {"tool": "reflog", "params": {"ref": "feature", "count": 10}},   #fails: branch is gone
        {"tool": "reflog", "params": {"ref": "HEAD", "count": 10}},      #the correct call
        plan_reply(f"git branch feature {FEAT2}"),
    ], built, min_investigations=1)
    assert run.plan is not None
    assert len(run.investigations) == 1, "only the successful call should count against the budget"


def test_a_failed_call_does_not_spend_the_budget(built):
    replies = [{"tool": "show", "params": {"ref": f"nosuchref{n}"}} for n in range(1, 6)]
    run, _, _ = investigate("deleted-branch-01",
                            replies + [{"tool": "status"}, plan_reply(f"git branch feature {FEAT2}")],
                            built, budget=2, min_investigations=1)
    assert run.plan is not None and len(run.investigations) == 1


def test_repeating_a_successful_call_is_still_refused_with_a_suggestion(built):
    run, backend, _ = investigate("deleted-branch-01", [
        {"tool": "status"},
        {"tool": "status"},
        plan_reply(f"git branch feature {FEAT2}"),
    ], built, min_investigations=1)
    assert len(run.investigations) == 1
    assert "Not tried yet" in backend.calls[2]


def test_reflog_on_a_deleted_branch_says_where_to_look_instead(built):
    """git branch -D removes the branch's reflog too, so HEAD's is the only
    record left. The error message has to teach that, or the model is stuck."""
    from src.git_rescue import tools
    repo, _ = built(SCENARIOS["deleted-branch-01"])
    out = tools.call(repo.path, "reflog", {"ref": "feature"})
    assert out.startswith("ERROR:") and "HEAD's reflog" in out


def test_a_bare_plan_is_accepted_as_a_plan(built):
    """The planning prompt shows the schema without a {"plan": ...} wrapper.
    Gemini followed it exactly and its correct plan was ignored 12 times."""
    bare = plan_reply(f"git branch feature {FEAT2}")["plan"]
    run, _, _ = investigate("deleted-branch-01", [
        {"tool": "reflog", "params": {"ref": "HEAD", "count": 10}},
        {"ready": True},
        bare,
    ], built, min_investigations=1)
    assert run.plan is not None and "feature" in run.plan.steps[0].text


def test_a_bare_plan_still_has_to_follow_the_rules(built):
    """Unwrapping must not bypass validation: placeholders are still refused."""
    bare = plan_reply("git branch feature <sha>")["plan"]
    run, _, _ = investigate("deleted-branch-01", [
        {"tool": "reflog", "params": {"ref": "HEAD"}}, bare, bare, bare, bare,
    ], built, min_investigations=1)
    assert run.plan is None and any("placeholder" in r for r in run.rejected_plans)


def test_a_tool_named_as_the_key_is_accepted(built):
    """gpt-oss replied {"reflog": {...}} on its first turn."""
    run, _, _ = investigate("deleted-branch-01", [
        {"reflog": {"ref": "HEAD", "count": 10}},
        plan_reply(f"git branch feature {FEAT2}"),
    ], built, min_investigations=1)
    assert run.plan is not None and run.investigations[0]["tool"] == "reflog"


def test_an_unknown_single_key_is_not_mistaken_for_a_tool(built):
    run, _, _ = investigate("deleted-branch-01", [
        {"delete_everything": {}},
        {"tool": "status"},
        plan_reply(f"git branch feature {FEAT2}"),
    ], built, min_investigations=1)
    assert [i["tool"] for i in run.investigations] == ["status"]


def test_a_plan_that_fails_on_the_copy_gets_one_corrected_retry():
    """The shadow run's error is fed back. A real run lost dropped-stash by
    choosing the wrong dangling commit; the error said exactly that."""
    r, backend = agent_run("deleted-branch-01", [
        plan_reply("git branch -d no-such-branch"),
        plan_reply(f"git branch feature {FEAT2}"),
    ])
    assert r.recovered and r.practical_loss == 0
    assert "COPY" in backend.calls[1] and "no-such-branch" in backend.calls[1]


def test_replanning_is_capped():
    r, backend = agent_run("deleted-branch-01", [
        plan_reply("git branch -d no-such-branch"),
        plan_reply("git branch -d still-not-a-branch"),
        plan_reply(f"git branch feature {FEAT2}"),
    ])
    assert not r.recovered and len(backend.calls) == 2


def test_a_blocked_step_is_fed_back_and_can_be_dropped():
    """gpt-oss added "reflog expire ... gc --prune=now" as optional clean-up."""
    r, backend = agent_run("deleted-branch-01", [
        {"plan": {"diagnosis": "d", "confidence": "high", "steps": [
            {"command": f"git branch feature {FEAT2}", "purpose": "p", "risk": "reversible"},
            {"command": "git gc --prune=now", "purpose": "tidy up", "risk": "safe"}]}},
        plan_reply(f"git branch feature {FEAT2}"),
    ])
    assert r.recovered and "gc" in backend.calls[1]


def test_ready_before_looking_is_refused_without_wasting_a_plan(built):
    run, backend, _ = investigate("deleted-branch-01", [
        {"ready": True},
        {"tool": "reflog", "params": {"ref": "HEAD", "count": 10}},
        {"ready": True},
        plan_reply(f"git branch feature {FEAT2}"),
    ], built, min_investigations=1)
    assert run.plan is not None and run.rejected_plans == []
    assert "not looked" in backend.calls[1]
