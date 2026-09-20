import sys
import time

import pytest

from bench.harness.fake_systems import DoNothingSystem, ReferenceSystem, WrongFixSystem
from bench.harness.runner import run_scenario
from bench.harness.session import Session, blocked_reason
from bench.harness.simuser import IDK, SimulatedUser
from bench.loader import load_all

SCENARIOS = load_all()


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda s: s.id)
def test_reference_system_recovers_cleanly(scenario, built):
    r = run_scenario(scenario, ReferenceSystem(), prebuilt=built(scenario))
    assert r.error is None, r.error
    assert r.recovered, f"reference failed: {r.failed_assertions}"
    assert r.clean_recovery and r.practical_loss == 0
    assert r.commands > 0, "the reference solution should have run commands through the session"


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda s: s.id)
def test_wrong_fix_system_does_not_recover(scenario, built):
    r = run_scenario(scenario, WrongFixSystem(), prebuilt=built(scenario))
    assert r.error is None, r.error
    assert not r.recovered


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda s: s.id)
def test_do_nothing_system_does_not_recover(scenario, built):
    r = run_scenario(scenario, DoNothingSystem(), prebuilt=built(scenario))
    assert not r.recovered and r.commands == 0


def test_system_exception_is_recorded_not_raised(built):
    class Crashes:
        name, uses_oracle = "crashes", False
        def run(self, session):
            raise RuntimeError("model returned garbage")
    r = run_scenario(SCENARIOS[0], Crashes(), prebuilt=built(SCENARIOS[0]))
    assert "model returned garbage" in r.error and not r.recovered


def test_oracle_is_withheld_from_real_systems(built):
    seen = {}
    class Peeks:
        name, uses_oracle = "peeks", False
        def run(self, session):
            seen["oracle"] = session.oracle
    run_scenario(SCENARIOS[0], Peeks(), prebuilt=built(SCENARIOS[0]))
    assert seen["oracle"] is None


@pytest.mark.parametrize("argv", [
    ["rm", "-rf", "."],
    ["git", "-c", "core.pager=evil", "log"],
    ["git", "-C", "..", "status"],
    ["git", "--git-dir=/tmp/other", "status"],
    ["git", "config", "alias.x", "!rm -rf ."],
    ["git", "rebase", "--exec", "rm -rf .", "main"],
    ["git", "rebase", "-x", "echo hi", "main"],
    ["git", "bisect", "run", "make"],
    ["git", "submodule", "update"],
])
def test_dangerous_commands_are_blocked(argv):
    assert blocked_reason(argv) is not None


@pytest.mark.parametrize("argv", [
    ["git", "switch", "-c", "rescued"],      # -c after the subcommand is a normal flag
    ["git", "commit", "-c", "HEAD"],
    ["git", "reset", "--hard", "HEAD~1"],     # destructive, but that is what we measure
    ["git", "branch", "-D", "feature"],
    ["git", "--no-pager", "log", "--oneline"],
    ["git", "--version"],
])
def test_legitimate_commands_are_allowed(argv):
    assert blocked_reason(argv) is None


def test_blocked_command_never_runs(built, tmp_path):
    repo, _ = built(SCENARIOS[0])
    marker = tmp_path / "pwned"
    s = Session(repo.path, repo.home, "msg", SimulatedUser({}))
    r = s.run(["git", "-c", f"core.pager=touch {marker}", "log"])
    assert r.blocked and not marker.exists()
    assert s.events[-1]["blocked"]


def test_command_budget_is_enforced(built):
    repo, _ = built(SCENARIOS[0])
    s = Session(repo.path, repo.home, "msg", SimulatedUser({}), max_commands=2)
    s.run(["git", "status"]); s.run(["git", "status"])
    assert "budget" in s.run(["git", "status"]).blocked


def test_editor_can_never_hang_a_run(built, monkeypatch):
    """A commit with no -m opens an editor. Plant one that hangs for 20s:
    the Session must override it, or this run would stall."""
    hang = f'"{sys.executable}" -c "import time; time.sleep(20)"'
    monkeypatch.setenv("EDITOR", hang)
    monkeypatch.setenv("VISUAL", hang)
    repo, _ = built(SCENARIOS[0])
    s = Session(repo.path, repo.home, "msg", SimulatedUser({}))
    start = time.monotonic()
    r = s.run(["git", "commit", "--allow-empty"])
    assert time.monotonic() - start < 10 and r.returncode != 0


@pytest.mark.parametrize("path", ["../outside.txt", ".git/config", ".git/hooks/pre-commit"])
def test_write_file_stays_in_the_working_tree(built, path):
    repo, _ = built(SCENARIOS[0])
    s = Session(repo.path, repo.home, "msg", SimulatedUser({}))
    with pytest.raises(PermissionError):
        s.write_file(path, "x")


def test_simulated_user_answers_from_clarifications():
    u = SimulatedUser({"pushed_to_remote": "No, nothing is pushed.",
                       "deleted_branch_name": "It's called feature."})
    assert u.answer("Have you pushed these commits to a remote?") == "No, nothing is pushed."
    assert u.answer("What was the name of the deleted branch?") == "It's called feature."
    assert u.answer("Do you like cats?") == IDK
    assert u.unanswered == ["Do you like cats?"]


def test_one_shared_word_is_not_enough_to_answer():
    """A real transcript: this question shares only "changes" with the key,
    and answering it produced a wrong reply that corrupted the model's next
    command. A wrong answer is worse than no answer."""
    u = SimulatedUser({"which_file_changed": "It was my work on login.py."})
    assert u.answer("Did you run any other git commands between stashing and dropping the changes?") == IDK
    assert u.answer("Which file had the changes you lost?") == "It was my work on login.py."


def test_word_endings_do_not_break_matching():
    u = SimulatedUser({"pushed_to_remote": "No."})
    assert u.answer("Are you pushing this to a remote?") == "No."


def test_simulated_user_stops_after_max_questions():
    u = SimulatedUser({"pushed": "No."}, max_questions=1)
    u.answer("pushed?")
    assert "enough" in u.answer("pushed?")


def test_a_tied_question_is_not_answered_with_a_guess():
    """Both keys share "branch" and "name" with this question. Alphabetical
    order used to pick current_branch_name, so the user said "I'm on main."
    when asked what the feature branch was called."""
    u = SimulatedUser({"current_branch_name": "I'm on main.",
                       "deleted_branch_name": "It was called feature."})
    assert u.answer("What is the branch name?") == IDK


def test_the_more_specific_key_wins():
    u = SimulatedUser({"current_branch_name": "I'm on main.",
                       "feature_branch_name": "The branch is called feature."})
    assert u.answer("What is the name of the feature branch you created?") == "The branch is called feature."
