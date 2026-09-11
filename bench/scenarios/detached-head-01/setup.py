"""Detached HEAD: commits made on an old commit, then abandoned by
switching back to main.

Broken state after build():
  - HEAD is back on main, and main is unchanged.
  - fix1 and fix2 exist but no branch, tag, or other ref contains them.
  - They are still in the reflog (HEAD@{n}), which is how they're recovered.
"""
from bench.gitenv import GitRepo

SCENARIO_ID = "detached-head-01"  # must match the folder name; the loader checks


def build(repo: GitRepo) -> dict[str, str]:
    base = repo.commit_file("app.py", "def main():\n    return 1\n", "Initial app")
    repo.commit_file("app.py", "def main():\n    return 2\n", "Add feature")
    main_tip = repo.commit_file("app.py", "def main():\n    return 3\n", "Refactor main")

    # The user checks out an old commit "to test something".
    repo.git("checkout", "--quiet", "--detach", base)

    # ...and commits real work while detached.
    fix1 = repo.commit_file("login.py", "def login(user):\n    return user.strip()\n", "Fix login whitespace bug")
    fix2 = repo.commit_file("login.py", "def login(user):\n    return user.strip().lower()\n", "Fix login case bug")

    # Then goes back to main. Git prints a warning, which juniors miss.
    repo.git("checkout", "--quiet", "main")

    return {"base": base, "main_tip": main_tip, "fix1": fix1, "fix2": fix2}


def verify_broken(repo: GitRepo, labels: dict[str, str]) -> None:
    """Assert the repo is in exactly the broken state described above.
    If this fails, the scenario is wrong, not the agent."""
    assert repo.head_is_attached(), "HEAD should be back on a branch"
    assert repo.rev("HEAD") == labels["main_tip"], "main should be unchanged"
    assert repo.is_clean(), "working tree should be clean"

    for label in ("fix1", "fix2"):
        sha = labels[label]
        assert repo.refs_containing(sha) == [], f"{label} should not be on any ref"
        assert repo.in_reflog(sha), f"{label} should still be recoverable from the reflog"


def solve(repo: GitRepo, labels: dict[str, str]) -> None:
    """Reference rescue: put a branch on the last detached commit."""
    repo.git("branch", "fixes", labels["fix2"])


def _reset_main_to_fixes(repo: GitRepo, labels: dict[str, str]) -> None:
    # A common copy-pasted answer. Gets the fixes onto main, but throws
    # away main's own commits in the process.
    repo.git("reset", "--hard", labels["fix2"])


WRONG_FIXES = {"reset_main_to_fixes": _reset_main_to_fixes}
