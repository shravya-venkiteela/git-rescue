import pytest

from bench.baselines.description_only import DescriptionOnlySystem
from bench.harness.llm import ScriptedBackend
from bench.harness.runner import run_scenario
from bench.loader import load_all

SCENARIOS = {s.id: s for s in load_all()}
FEAT2 = "ced977baba6b18af909e0f498199e03705fce144"


def run(scenario_id, replies, **kwargs):
    backend = ScriptedBackend(replies)
    system = DescriptionOnlySystem(backend, **kwargs)
    return run_scenario(SCENARIOS[scenario_id], system), backend


def test_a_correct_literal_command_recovers():
    r, _ = run("deleted-branch-01", [{"commands": [f"git branch feature {FEAT2}"], "explanation": "Recreated it."}])
    assert r.recovered and r.practical_loss == 0 and r.commands == 1


def test_questions_are_answered_by_the_simulated_user():
    r, backend = run("deleted-branch-01", [
        {"questions": ["What was the deleted branch name?"], "commands": []},
        {"commands": [f"git branch feature {FEAT2}"], "explanation": "Recreated it."},
    ])
    assert r.questions == 1 and r.recovered
    assert "feature" in backend.calls[1], "the answer should be fed back to the model"


def test_placeholder_command_fails_and_is_recorded():
    """No one resolves <commit-hash>: resolving it would be the diagnosis
    this baseline is meant to lack. It fails as it would in a real terminal."""
    r, _ = run("deleted-branch-01", [{"commands": ["git branch feature <commit-hash>"], "explanation": "Do this."}])
    assert not r.recovered
    failed = [e for e in r.events if e["type"] == "command" and e["returncode"] != 0]
    assert len(failed) == 1 and "commit-hash" in failed[0]["argv"][-1]


def test_invented_sha_fails_like_any_other_bad_ref():
    r, _ = run("deleted-branch-01", [{"commands": ["git branch feature abc1234"], "explanation": "Do this."}])
    assert not r.recovered
    assert any(e["type"] == "command" and e["returncode"] != 0 for e in r.events)


def test_run_stops_at_the_first_failing_command():
    r, _ = run("deleted-branch-01", [{"commands": [
        "git branch feature <sha>",           # fails
        f"git branch feature2 {FEAT2}",       # would have worked; must not run
    ], "explanation": ""}])
    assert r.commands == 1, "later steps assume the failed one worked"


def test_unparseable_output_is_a_clean_failure():
    r, _ = run("deleted-branch-01", ["I think you should try git reflog!"])
    assert not r.recovered and r.commands == 0 and r.error is None
    assert any(e["type"] == "model_reply" and not e["parsed"] for e in r.events)


def test_dangerous_command_is_blocked_not_run():
    r, _ = run("deleted-branch-01", [{"commands": ["git -c core.pager=evil log"], "explanation": ""}])
    assert r.blocked_commands == 1 and r.commands == 0


def test_no_questions_variant_never_asks():
    r, _ = run("deleted-branch-01", [
        {"questions": ["What was the deleted branch name?"], "commands": []},
    ], allow_questions=False)
    assert r.questions == 0


def test_empty_commands_is_scored_as_no_recovery():
    r, _ = run("deleted-branch-01", [{"commands": [], "explanation": "I can't tell without seeing your repo."}])
    assert not r.recovered and r.commands == 0 and r.error is None


def test_read_only_advice_is_its_own_category():
    """From a real transcript: the model ran `git reflog`, which succeeded,
    but it never sees the output, so it can never act on it. That is a
    structural limit of advice without inspection, not a wrong diagnosis,
    and the results table must distinguish the two."""
    r, _ = run("deleted-branch-01", [{"commands": ["git reflog"], "explanation": "Look here."}])
    assert r.category == "read_only_advice" and not r.recovered


def test_failed_command_is_its_own_category():
    r, _ = run("deleted-branch-01", [{"commands": ["git branch feature <sha>"], "explanation": ""}])
    assert r.category == "command_failed"


def test_clean_but_wrong_fix_is_its_own_category():
    """Commands all succeeded; the intent was still not met."""
    r, _ = run("deleted-branch-01", [{"commands": ["git branch feature main"], "explanation": ""}])
    assert r.category == "wrong_fix" and not r.recovered


def test_no_commands_is_its_own_category():
    r, _ = run("deleted-branch-01", [{"commands": [], "explanation": "Can't tell without seeing the repo."}])
    assert r.category == "no_commands_proposed"


def test_unparsable_is_its_own_category():
    r, _ = run("deleted-branch-01", ["sorry, here is some prose"])
    assert r.category == "unparsable_output"


def test_recovered_runs_are_categorized_as_recovered():
    r, _ = run("deleted-branch-01", [{"commands": [f"git branch feature {FEAT2}"], "explanation": ""}])
    assert r.category == "recovered"


# --- B2: unrestricted shell -------------------------------------------------

def run_shell(scenario_id, replies, **kwargs):
    from bench.baselines.unrestricted_shell import UnrestrictedShellSystem
    backend = ScriptedBackend(replies)
    return run_scenario(SCENARIOS[scenario_id], UnrestrictedShellSystem(backend, **kwargs)), backend


def test_shell_system_sees_command_output():
    """The whole point of B2: it can read what a command printed and use it."""
    _, backend = run_shell("deleted-branch-01", [
        {"command": "git reflog", "reason": "look for the lost commits"},
        {"done": True, "explanation": "Saw the reflog."},
    ])
    assert "You ran: git reflog" in backend.calls[1]
    assert "exit code 0" in backend.calls[1] and "commit:" in backend.calls[1]


def test_shell_system_can_recover_by_investigating_then_acting():
    r, _ = run_shell("deleted-branch-01", [
        {"command": "git reflog", "reason": "find the lost commits"},
        {"command": f"git branch feature {FEAT2}", "reason": "recreate the branch"},
        {"done": True, "explanation": "Recreated feature."},
    ])
    assert r.recovered and r.category == "recovered" and r.commands == 2


def test_shell_system_can_destroy_work_with_no_guardrails():
    """B2 has no backup and no confirmation, so the checker must see the loss.
    Without this, 'zero data loss' would be untestable against the baseline."""
    r, _ = run_shell("detached-head-01", [
        {"command": "git reset --hard HEAD~2", "reason": "clean slate"},
        {"done": True, "explanation": "Reset."},
    ])
    assert r.practical_loss > 0 and not r.recovered


def test_shell_system_stops_when_done():
    r, _ = run_shell("deleted-branch-01", [{"done": True, "explanation": "Nothing to do."}])
    assert r.commands == 0 and r.category == "no_commands_proposed"


def test_shell_system_runs_out_of_turns_gracefully():
    # Distinct commands, or repeat suppression would collapse them into one.
    replies = [{"command": f"git log -{n}", "reason": "look"} for n in range(1, 5)]
    r, _ = run_shell("deleted-branch-01", replies, max_turns=3)
    assert r.commands == 3 and r.error is None and "turns" in [e for e in r.events if e["type"] == "say"][0]["message"]


def test_shell_system_is_told_when_a_command_is_blocked():
    _, backend = run_shell("deleted-branch-01", [
        {"command": "git -c core.pager=evil log", "reason": "peek"},
        {"done": True, "explanation": "stopped"},
    ])
    assert "BLOCKED" in backend.calls[1]


def test_repeated_command_is_refused_not_re_run():
    """Every B2 run hit its turn cap, and on average only 8 of 15 commands
    were distinct: the model repeats itself instead of progressing. A repeat
    gives the same result, so the turn is spent telling it that."""
    r, backend = run_shell("deleted-branch-01", [
        {"command": "git status", "reason": "look"},
        {"command": "git status", "reason": "look again"},
        {"done": True, "explanation": "done"},
    ])
    assert r.commands == 1, "the duplicate must not reach git"
    assert "already ran" in backend.calls[2]


def test_distinct_command_count_is_recorded():
    r, _ = run_shell("deleted-branch-01", [
        {"command": "git status", "reason": "a"},
        {"command": "git reflog", "reason": "b"},
        {"done": True, "explanation": ""},
    ])
    assert r.commands == 2 and r.distinct_commands == 2


def test_model_is_told_how_many_turns_remain():
    _, backend = run_shell("deleted-branch-01", [{"done": True, "explanation": ""}], max_turns=7)
    assert "7 turns left" in backend.calls[0]
