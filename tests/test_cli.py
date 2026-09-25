"""The command people actually run. Until this existed, `git rescue` printed
"not implemented yet" while the agent worked only inside the benchmark."""
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from bench.harness.llm import ScriptedBackend
from bench.loader import load_all
from src.git_rescue import cli

SCENARIOS = {s.id: s for s in load_all()}
FEAT2 = "ced977baba6b18af909e0f498199e03705fce144"
runner = CliRunner()


def plan_reply(command, risk="reversible", **extra):
    return {"plan": {"diagnosis": "the branch was deleted", "confidence": "high",
                     "steps": [{"command": command, "purpose": "put it back", "risk": risk}], **extra}}


@pytest.fixture
def repo(built, monkeypatch):
    """A broken repository, with the backend scripted instead of a real model."""
    repo, labels = built(SCENARIOS["deleted-branch-01"])
    replies = []
    monkeypatch.setattr(cli, "_backend", lambda *a, **k: ScriptedBackend(replies))
    return repo, labels, replies


def run(repo, *args, stdin=""):
    return runner.invoke(cli.app, ["--repo", str(repo.path), *args], input=stdin)


def branches(repo):
    return subprocess.run(["git", "branch", "--format=%(refname:short)"], cwd=repo.path,
                          capture_output=True, text=True).stdout.split()


def test_a_plan_is_shown_and_applied_after_confirmation(repo):
    r, labels, replies = repo
    replies += [{"tool": "reflog", "params": {"ref": "HEAD"}}, plan_reply(f"git branch feature {FEAT2}")]
    result = run(r, "my branch is gone", stdin="y\n")
    assert result.exit_code == 0, result.output
    assert "git branch feature" in result.output and "reversible" in result.output
    assert "feature" in branches(r)


def test_nothing_runs_without_confirmation(repo):
    r, labels, replies = repo
    replies += [{"tool": "reflog", "params": {"ref": "HEAD"}}, plan_reply(f"git branch feature {FEAT2}")]
    result = run(r, "my branch is gone", stdin="n\n")
    assert result.exit_code != 0 and "feature" not in branches(r)


def test_dry_run_shows_the_plan_and_changes_nothing(repo):
    r, labels, replies = repo
    replies += [{"tool": "reflog", "params": {"ref": "HEAD"}}, plan_reply(f"git branch feature {FEAT2}")]
    #Options come before the problem text: anything after it is read as a
    #subcommand name (the app also has `undo`).
    result = run(r, "--dry-run", "my branch is gone")
    assert result.exit_code == 0 and "nothing was run" in result.output
    assert "feature" not in branches(r)


def test_an_unrecoverable_answer_is_printed_and_nothing_runs(repo):
    r, labels, replies = repo
    replies += [{"tool": "status"},
                {"plan": {"diagnosis": "never committed", "confidence": "high", "steps": [],
                          "unrecoverable": ["the uncommitted edits to login.py"]}}]
    result = run(r, "my edits vanished")
    assert result.exit_code == 0
    assert "Cannot be recovered" in result.output and "uncommitted edits" in result.output


def test_a_blocked_command_is_refused(repo):
    r, labels, replies = repo
    replies += [{"tool": "status"}, plan_reply("git gc --prune=now", risk="safe")]
    result = run(r, "clean up", stdin="y\n")
    assert result.exit_code != 0 and "BLOCKED" in result.output


def test_outside_a_repository_it_says_so(tmp_path):
    result = runner.invoke(cli.app, ["--repo", str(tmp_path), "help"])
    assert result.exit_code != 0 and "not a git repository" in result.output


def test_the_benchmark_environment_is_sealed_by_default():
    """Scenario builds must not depend on the machine's git config."""
    from src.git_rescue import gitenv

    env = gitenv.env_for(Path("/tmp/whatever"))
    assert env["GIT_AUTHOR_NAME"] == "Scenario Author" and env["GIT_CONFIG_NOSYSTEM"] == "1"


def test_the_cli_uses_the_persons_own_git_identity(repo, monkeypatch):
    """A revert this tool makes on someone's repository must carry their name,
    not the benchmark's "Scenario Author"."""
    from src.git_rescue import gitenv

    r, labels, replies = repo
    monkeypatch.setenv("GIT_AUTHOR_NAME", "Real Person")
    replies += [{"tool": "status"}, plan_reply(f"git branch feature {FEAT2}")]
    run(r, "my branch is gone", stdin="y\n")
    env = gitenv.env_for(Path("/tmp/whatever"))
    assert env.get("GIT_AUTHOR_NAME") == "Real Person"


def test_undo_is_a_command_not_a_problem_description(repo, monkeypatch):
    """`git rescue undo` used to be read as "the problem is: undo", and the
    agent started investigating instead of restoring the backup."""
    r, labels, replies = repo
    asked = []
    monkeypatch.setattr(cli.backup_mod, "latest_for", lambda root, **kw: asked.append(root))
    result = run(r, "undo")
    assert asked, "undo should have looked for a backup"
    assert "no backup found" in result.output
    assert "Looking at the repository" not in result.output


def test_a_problem_that_merely_mentions_undo_still_investigates(repo):
    r, labels, replies = repo
    replies += [{"tool": "status"}, plan_reply(f"git branch feature {FEAT2}")]
    result = run(r, "--dry-run", "I want to undo my last commit")
    assert "Looking at the repository" in result.output
