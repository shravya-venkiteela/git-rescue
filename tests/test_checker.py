"""Mutation tests for the data-loss checker: deliberately destroy work
and confirm the checker notices, at the right severity."""
import shutil

import pytest

from bench.gitenv import GitRepo
from bench.harness.checker import Status, check, take_snapshot


@pytest.fixture
def repo(tmp_path):
    r = GitRepo.init(tmp_path / "repo", tmp_path / "home")
    r.commit_file(".gitignore", "*.log\n", "Ignore logs")
    r.commit_file("app.py", "v1\n", "First")
    return r


def losses(repo, mutate, backup=None):
    before = take_snapshot(repo.path)
    mutate(repo)
    return check(before, take_snapshot(repo.path), backup)


def test_noop_reports_nothing(repo):
    assert losses(repo, lambda r: None).losses == []


def test_reset_hard_over_unstaged_edit_is_absolute_loss(repo):
    repo.write("app.py", "unsaved work\n")  # never staged: git has no copy
    report = losses(repo, lambda r: r.git("reset", "--hard"))
    assert len(report.absolute) == 1 and report.absolute[0].kind == "content"


def test_reset_hard_over_staged_edit_is_hidden_not_gone(repo):
    repo.write("app.py", "staged work\n")
    repo.git("add", "app.py")  # staging writes a blob, so it survives as dangling
    report = losses(repo, lambda r: r.git("reset", "--hard"))
    assert report.absolute == []
    assert [l.after for l in report.practical] == [Status.HIDDEN]


def test_stash_drop_is_practical_loss(repo):
    repo.write("app.py", "stashed work\n")
    repo.git("stash")
    report = losses(repo, lambda r: r.git("stash", "drop"))
    assert report.practical and report.absolute == []


def test_branch_delete_plus_gc_is_absolute_loss(repo):
    repo.git("checkout", "--quiet", "-b", "feature")
    repo.commit_file("feature.py", "work\n", "Feature work")
    repo.git("checkout", "--quiet", "main")

    def destroy(r):
        r.git("branch", "-D", "feature")
        r.git("reflog", "expire", "--expire=now", "--all")
        r.git("gc", "--prune=now", "--quiet")

    report = losses(repo, destroy)
    assert any(l.kind == "commit" and l.after == Status.GONE for l in report.absolute)


def test_clean_fdx_loses_untracked_and_ignored_files(repo):
    repo.write("notes.txt", "untracked notes\n")
    repo.write("debug.log", "ignored log\n")
    report = losses(repo, lambda r: r.git("clean", "-fdx", "--quiet"))
    assert len(report.absolute) == 2


def test_backup_downgrades_loss_to_backup_only(repo, tmp_path):
    repo.write("app.py", "unsaved work\n")
    backup_dir = tmp_path / "backup"
    shutil.copytree(repo.path, backup_dir)
    report = losses(repo, lambda r: r.git("reset", "--hard"), backup=take_snapshot(backup_dir))
    assert report.absolute == [] and report.practical == []
    assert len(report.backup_only) == 1


def test_recovering_hidden_work_is_not_a_loss(repo):
    """A dropped stash starts HIDDEN. Recovering it is an improvement, and
    leaving it hidden is not a *new* loss."""
    repo.write("app.py", "stashed work\n")
    repo.git("stash")
    stash = repo.rev("refs/stash")
    repo.git("stash", "drop")
    assert losses(repo, lambda r: None).losses == []
    assert losses(repo, lambda r: r.git("stash", "apply", stash)).losses == []


def test_allowed_to_lose_is_respected(repo):
    repo.git("checkout", "--quiet", "--detach")
    throwaway = repo.commit_file("scratch.py", "experiment\n", "Throwaway")
    repo.git("checkout", "--quiet", "main")
    before = take_snapshot(repo.path)
    repo.git("reflog", "expire", "--expire=now", "--all")
    after = take_snapshot(repo.path)
    assert check(before, after).practical
    assert check(before, after, allowed_to_lose=frozenset({throwaway})).losses == []


def test_commit_knocked_off_a_branch_is_practical_loss(repo):
    """Work still in the reflog is NOT safe: juniors don't know to look, and
    git expires reflog entries after 30-90 days."""
    dropped = repo.commit_file("app.py", "v2\n", "Second")
    report = losses(repo, lambda r: r.git("reset", "--hard", "HEAD~1"))
    lost = [l for l in report.practical if l.item == dropped]
    assert [l.after for l in lost] == [Status.REFLOG_ONLY]
    assert report.absolute == []


def test_rewriting_history_is_not_losing(repo):
    """Amend/rebase/cherry-pick abandon the old SHA, but the work survives in
    the new commit. Identical content on a branch means nothing was lost."""
    original = repo.rev("HEAD")
    repo.write("app.py", "v2\n")
    repo.git("add", "app.py")
    losses(repo, lambda r: r.git("commit", "--quiet", "--amend", "-m", "First, amended"))
    #A message-only rewrite keeps the same tree, so nothing is lost.
    repo.git("reset", "--quiet", "--hard", original)
    after = losses(repo, lambda r: r.git("commit", "--quiet", "--amend", "-m", "Reworded only"))
    assert after.losses == [], "a message-only rewrite keeps the same tree; nothing is lost"


def test_rewriting_that_drops_content_is_still_loss(repo):
    """The tree rule must not excuse a rewrite that actually throws work away."""
    keeper = repo.commit_file("keeper.py", "important\n", "Add keeper")
    report = losses(repo, lambda r: r.git("reset", "--hard", "HEAD~1"))
    assert any(l.item == keeper for l in report.practical)
