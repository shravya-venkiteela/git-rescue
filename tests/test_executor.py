"""Executing a plan must be safe before it is useful: nothing destructive
runs unconfirmed, nothing runs at all if it fails on a copy, and the real
result is checked against the preview."""
import pytest

from bench.harness.checker import check, take_snapshot
from bench.loader import load_all
from src.git_rescue import backup as backup_mod
from src.git_rescue import executor
from src.git_rescue.plan import parse

SCENARIOS = {s.id: s for s in load_all()}
YES = lambda *a: True
NO = lambda *a: False


def plan_of(*commands, risk="reversible", diagnosis="d"):
    return parse({"diagnosis": diagnosis, "confidence": "high",
                  "steps": [{"command": c, "purpose": "p", "risk": risk} for c in commands]})


def test_a_good_plan_applies_and_verifies(built):
    repo, labels = built(SCENARIOS["deleted-branch-01"])
    out = executor.execute(repo.path, plan_of(f"git branch feature {labels['feat2']}"),
                           confirm=YES, backup_root=repo.path.parent / "bk")
    assert out.ok and out.verified
    assert repo.rev("refs/heads/feature") == labels["feat2"]


def test_the_shadow_run_previews_changes_without_making_them(built):
    repo, labels = built(SCENARIOS["deleted-branch-01"])
    before = take_snapshot(repo.path)
    steps, ok, diff = executor.shadow_run(repo.path, plan_of(f"git branch feature {labels['feat2']}").steps)
    assert ok and "refs/heads/feature" in diff
    assert take_snapshot(repo.path) == before, "the shadow run must not touch the real repository"


def test_a_plan_that_fails_on_the_copy_never_touches_the_real_repo(built):
    repo, _ = built(SCENARIOS["deleted-branch-01"])
    before = take_snapshot(repo.path)
    out = executor.execute(repo.path, plan_of("git branch feature 0000000000000000000000000000000000000000"),
                           confirm=YES, backup_root=repo.path.parent / "bk")
    assert not out.ok and "fails on a copy" in out.reason
    assert take_snapshot(repo.path) == before


def test_destructive_plans_do_not_run_without_confirmation(built):
    repo, _ = built(SCENARIOS["detached-head-01"])
    before = take_snapshot(repo.path)
    out = executor.execute(repo.path, plan_of("git reset --hard HEAD~1", risk="safe"),
                           backup_root=repo.path.parent / "bk")
    assert not out.ok and "no confirmation" in out.reason
    assert take_snapshot(repo.path) == before


def test_declining_confirmation_changes_nothing(built):
    repo, _ = built(SCENARIOS["detached-head-01"])
    before = take_snapshot(repo.path)
    out = executor.execute(repo.path, plan_of("git reset --hard HEAD~1"), confirm=NO,
                           backup_root=repo.path.parent / "bk")
    assert not out.ok and "did not confirm" in out.reason
    assert take_snapshot(repo.path) == before


def test_a_blocked_step_stops_the_whole_plan(built):
    repo, labels = built(SCENARIOS["deleted-branch-01"])
    before = take_snapshot(repo.path)
    out = executor.execute(repo.path, plan_of(f"git branch feature {labels['feat2']}", "git push --force"),
                           confirm=YES, backup_root=repo.path.parent / "bk")
    assert not out.ok and "blocked" in out.reason
    assert take_snapshot(repo.path) == before, "not even the safe first step should run"


def test_destructive_work_is_backed_up_and_can_be_undone(built):
    """The claim the whole project rests on: destructive steps are survivable."""
    repo, _ = built(SCENARIOS["detached-head-01"])
    before = take_snapshot(repo.path)
    root = repo.path.parent / "bk"
    out = executor.execute(repo.path, plan_of("git reset --hard HEAD~1"), confirm=YES, backup_root=root)
    assert out.ok and out.backup is not None

    lost = check(before, take_snapshot(repo.path))
    assert lost.practical, "the reset should have cost something"
    saved = check(before, take_snapshot(repo.path), backup=take_snapshot(out.backup.repo_copy))
    assert not saved.practical and not saved.absolute, "the backup should cover every loss"

    backup_mod.restore(out.backup, repo.path)
    assert take_snapshot(repo.path) == before, "undo should put everything back"


def test_undo_is_itself_undoable(built):
    """A user who undoes by mistake must not be stuck."""
    repo, _ = built(SCENARIOS["detached-head-01"])
    root = repo.path.parent / "bk"
    out = executor.execute(repo.path, plan_of("git reset --hard HEAD~1"), confirm=YES, backup_root=root)
    after_reset = take_snapshot(repo.path)
    backup_mod.restore(out.backup, repo.path)
    newest = backup_mod.latest_for(repo.path, root=root)
    assert take_snapshot(newest.repo_copy) == after_reset


def test_safe_plans_need_no_backup(built):
    repo, labels = built(SCENARIOS["deleted-branch-01"])
    out = executor.execute(repo.path, plan_of(f"git branch feature {labels['feat2']}"),
                           confirm=YES, backup_root=repo.path.parent / "bk")
    assert out.ok and out.backup is None, "nothing was at risk, so nothing was copied"


def test_backup_keeps_untracked_files_that_git_would_not(built):
    """A stash would not save these; a directory copy does."""
    repo, _ = built(SCENARIOS["detached-head-01"])
    saved = backup_mod.create(repo.path, root=repo.path.parent / "bk")
    assert (saved.repo_copy / "notes.txt").read_text() == (repo.path / "notes.txt").read_text()


def test_two_backups_in_the_same_second_do_not_collide(built):
    """Second-resolution folder names collided, and copytree merged the two
    states into one folder, so both backups were corrupt."""
    repo, _ = built(SCENARIOS["detached-head-01"])
    root = repo.path.parent / "bk"
    first = backup_mod.create(repo.path, note="first", root=root)
    (repo.path / "notes.txt").write_text("changed after the first backup\n")
    second = backup_mod.create(repo.path, note="second", root=root)

    assert first.path != second.path
    assert (first.repo_copy / "notes.txt").read_text() != (second.repo_copy / "notes.txt").read_text()


def test_the_undo_safety_copy_is_stored_beside_the_original(built):
    """restore() defaulted to ~/.git-rescue regardless of where the backup
    it was restoring lived, so the safety copy went somewhere else."""
    repo, _ = built(SCENARIOS["detached-head-01"])
    root = repo.path.parent / "bk"
    saved = backup_mod.create(repo.path, root=root)
    backup_mod.restore(saved, repo.path)
    assert len(list((root / saved.path.parent.name).iterdir())) == 2
