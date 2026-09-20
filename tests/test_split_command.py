"""Commands are split like a shell would split them. str.split() turned
git stash push -m "recovered stash" into two stray pathspecs, and the
dropped-stash run failed on that rather than on anything the model did."""
from pathlib import Path

import pytest

from git_rescue.plan import split_command


@pytest.mark.parametrize("command,argv", [
    ('git stash push -m "recovered stash"', ["git", "stash", "push", "-m", "recovered stash"]),
    ("git commit -m 'fix: keep both'", ["git", "commit", "-m", "fix: keep both"]),
    ("git branch feature ced977b", ["git", "branch", "feature", "ced977b"]),
    ('git commit -m "unbalanced', ["git", "commit", "-m", '"unbalanced']),
])
def test_split_command(command, argv):
    assert split_command(command) == argv


@pytest.mark.parametrize("rel", [
    "src/git_rescue/plan.py",
    "bench/baselines/description_only.py",
    "bench/baselines/unrestricted_shell.py",
    "bench/baselines/rescue_agent.py",
])
def test_no_system_splits_commands_on_whitespace(rel):
    source = (Path(__file__).resolve().parents[1] / rel).read_text(encoding="utf-8")
    for old in ("argv = command.split()", "session.run(command.split())", "step.command.split()"):
        assert old not in source
