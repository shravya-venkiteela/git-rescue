from bench.gitenv import GitRepo

def verify_broken(repo: GitRepo, labels: dict[str, str]) -> None:
    """Assert the repo is in exactly the broken state described above.
    If this fails, the scenario is wrong, not the agent."""
    assert repo.head_is_attached(), "HEAD should be on main"
    assert repo.rev("refs/heads/main") == labels["reset_to"], "main should be where the reset left it"
    assert repo.is_clean(), "reset --hard leaves a clean working tree"

    for label in ("lost1", "target"):
        sha = labels[label]
        assert repo.refs_containing(sha) == [], f"{label} should not be on any ref"
        assert repo.in_reflog(sha), f"{label} should still be recoverable from the reflog"

    #The defining check: the damage was done by a reset.
    last_action = repo.git("reflog", "-1", "--format=%gs")
    assert last_action.startswith("reset:"), f"newest reflog entry should be the reset, got {last_action!r}"


def build(repo: GitRepo) -> dict[str, str]:
    reset_to = repo.commit_file("app.py", "def main():\n    return 1\n", "Initial app")
    lost1 = repo.commit_file("app.py", "def main():\n    return 2\n", "Add input validation")
    target = repo.commit_file("app.py", "def main():\n    return 3\n", "Add error messages")

    #The user meant to undo something small and reset two commits too far.
    repo.git("reset", "--quiet", "--hard", "HEAD~2")

    #target is where main should end up: the newest lost commit.
    return {"reset_to": reset_to, "lost1": lost1, "target": target}


def solve(repo: GitRepo, labels: dict[str, str]) -> None:
    """Reference rescue: move main back to where it was before the reset.
    Safe here because reset --hard left the working tree clean."""
    repo.git("reset", "--quiet", "--hard", labels["target"])


def _reset_to_wrong_reflog_entry(repo: GitRepo, labels: dict[str, str]) -> None:
    #Off by one in the reflog: HEAD@{2} instead of HEAD@{1}. Recovers
    #one commit and leaves the newest one lost.
    repo.git("reset", "--quiet", "--hard", labels["lost1"])


def _branch_without_moving_main(repo: GitRepo, labels: dict[str, str]) -> None:
    #The detached-HEAD fix applied to the wrong problem: the work is safe
    #on a new branch, but main is still broken, which is not what this
    #user asked for.
    repo.git("branch", "recovered", labels["target"])


WRONG_FIXES = {
    "reset_to_wrong_reflog_entry": _reset_to_wrong_reflog_entry,
    "branch_without_moving_main": _branch_without_moving_main,
}