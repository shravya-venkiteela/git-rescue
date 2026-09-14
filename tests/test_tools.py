"""The read-only tools are the agent's only view of the repository.
Two properties matter: they must never change anything, and they must
reject values the model invented rather than read."""
import pytest

from bench.harness.checker import take_snapshot
from bench.loader import load_all
from src.git_rescue import tools

SCENARIOS = {s.id: s for s in load_all()}
ALL = sorted(tools.TOOLS)


@pytest.mark.parametrize("name", ALL)
def test_every_tool_leaves_the_repository_unchanged(name, built):
    repo, _ = built(SCENARIOS["deleted-branch-01"])
    before = take_snapshot(repo.path)
    tools.call(repo.path, name, {})
    assert take_snapshot(repo.path) == before, f"{name} modified the repository"


def test_status_does_not_rewrite_the_index(built):
    """Without GIT_OPTIONAL_LOCKS=0, `git status` refreshes and rewrites
    .git/index, so 'read-only' would be false. Verified against a scenario
    where plain `git status` does rewrite it."""
    repo, _ = built(SCENARIOS["deleted-branch-01"])
    index = repo.path / ".git" / "index"
    before = index.stat().st_mtime_ns
    tools.call(repo.path, "status", {})
    assert index.stat().st_mtime_ns == before


def test_operation_state_detects_an_unfinished_rebase(built):
    repo, _ = built(SCENARIOS["rebase-conflict-abort-01"])
    out = tools.call(repo.path, "operation_state", {})
    assert "rebase in progress" in out and "HEAD is detached" in out
    assert "refs/heads/feature" in out


def test_operation_state_is_quiet_when_nothing_is_running(built):
    repo, _ = built(SCENARIOS["deleted-branch-01"])
    out = tools.call(repo.path, "operation_state", {})
    assert "no operation in progress" in out and "HEAD is on a branch" in out


def test_dangling_finds_a_dropped_stash(built):
    """The dropped stash is in no reflog; only fsck can see it."""
    repo, labels = built(SCENARIOS["dropped-stash-01"])
    assert labels["stash"] in tools.call(repo.path, "dangling", {})


def test_reflog_finds_commits_from_a_deleted_branch(built):
    repo, labels = built(SCENARIOS["deleted-branch-01"])
    out = tools.call(repo.path, "reflog", {"count": 25})
    assert labels["feat2"][:7] in out


@pytest.mark.parametrize("ref", ["<sha>", "abc1234", "{branch}", "--upload-pack=evil", "a; rm -rf ."])
def test_invented_refs_are_refused_with_an_explanation(built, ref):
    repo, _ = built(SCENARIOS["deleted-branch-01"])
    out = tools.call(repo.path, "show", {"ref": ref})
    assert out.startswith("ERROR:") and "not a ref" in out


def test_unknown_tool_lists_the_real_ones(built):
    repo, _ = built(SCENARIOS["deleted-branch-01"])
    out = tools.call(repo.path, "run_shell", {})
    assert out.startswith("ERROR:") and "reflog" in out


def test_unexpected_parameters_are_ignored(built):
    """A model that invents a parameter should not crash the run."""
    repo, _ = built(SCENARIOS["deleted-branch-01"])
    assert not tools.call(repo.path, "status", {"force": True, "ref": "HEAD"}).startswith("ERROR")


def test_count_is_clamped_not_trusted(built):
    repo, _ = built(SCENARIOS["deleted-branch-01"])
    for bad in (0, -5, 10_000, "lots", None):
        assert not tools.call(repo.path, "log", {"count": bad}).startswith("ERROR")


def test_describe_lists_every_tool():
    text = tools.describe()
    assert all(name in text for name in ALL)
