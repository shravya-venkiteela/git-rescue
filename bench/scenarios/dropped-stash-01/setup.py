"""Dropped stash: uncommitted work stashed, then the stash dropped.

Broken state after build():
  - HEAD is on main, main is unchanged, working tree is clean.
  - The stash list is empty.
  - The stash commit is in NO reflog (drop removed it from refs/stash's
    reflog), so `git reflog` can't find it. It still exists as an
    unreachable commit, findable only with `git fsck --unreachable`.
"""
from bench.gitenv import GitRepo


def build(repo: GitRepo) -> dict[str, str]:
    repo.commit_file("login.py", "def login(user):\n    return user\n", "Add login")
    main_tip = repo.commit_file("app.py", "def main():\n    return 1\n", "Add app")

    # Uncommitted work in progress: the thing the user will lose.
    repo.write("login.py", "def login(user):\n    return user.strip().lower()\n")

    # The user stashes it to switch tasks...
    repo.git("stash")
    stash = repo.rev("refs/stash")

    # ...and later drops it, thinking it was already applied.
    repo.git("stash", "drop")

    return {"main_tip": main_tip, "stash": stash}


def verify_broken(repo: GitRepo, labels: dict[str, str]) -> None:
    """Assert the repo is in exactly the broken state described above.
    If this fails, the scenario is wrong, not the agent."""
    assert repo.head_is_attached(), "HEAD should be on main"
    assert repo.rev("HEAD") == labels["main_tip"], "main should be unchanged"
    assert repo.is_clean(), "the stashed edits should no longer be in the working tree"
    assert repo.git("stash", "list") == "", "stash list should be empty"

    # The defining feature: the reflog can't find it, but fsck can.
    sha = labels["stash"]
    assert not repo.in_reflog(sha), "a dropped stash should be in no reflog"
    assert sha in repo.unreachable_commits(), "the stash commit should still exist, findable by fsck"
