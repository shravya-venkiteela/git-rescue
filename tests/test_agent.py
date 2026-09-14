import pytest

from bench.baselines.rescue_agent import RescueAgentSystem
from bench.harness.llm import ScriptedBackend
from bench.harness.runner import run_scenario
from bench.loader import load_all
from src.git_rescue.agent import RescueAgent

SCENARIOS = {s.id: s for s in load_all()}
FEAT2 = "ced977baba6b18af909e0f498199e03705fce144"


def plan_reply(command, risk="reversible", **extra):
    return {"plan": {"diagnosis": "d", "confidence": "high",
                     "steps": [{"command": command, "purpose": "p", "risk": risk}], **extra}}


def agent_run(scenario_id, replies, **kwargs):
    backend = ScriptedBackend(replies)
    return run_scenario(SCENARIOS[scenario_id], RescueAgentSystem(backend, **kwargs)), backend


def investigate(scenario_id, replies, built, **kwargs):
    repo, labels = built(SCENARIOS[scenario_id])
    backend = ScriptedBackend(replies)
    return RescueAgent(backend, **kwargs).investigate(repo.path, "help"), backend, labels


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