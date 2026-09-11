from bench.gitenv import GitRepo

def build(repo: GitRepo) -> dict[str, str]:
    repo.commit_file("app.py", "def main():\n    return 1\n", "Initial app")
    main_tip = repo.commit_file("app.py", "def main():\n    return 2\n", "Add config loading")

    #The user starts a feature branch and commits real work on it.
    repo.git("checkout", "--quiet", "-b", "feature")
    feat1 = repo.commit_file("search.py", "def search(q):\n    return []\n", "Add search stub")
    feat2 = repo.commit_file("search.py", "def search(q):\n    return [q]\n", "Return query from search")

    #Back to main, then "cleaning up old branches". -D rather than -d:
    #-d refuses to delete an unmerged branch, and that refusal is the
    #safety net the user bypassed.
    repo.git("checkout", "--quiet", "main")
    repo.git("branch", "-D", "feature")

    return {"main_tip": main_tip, "feat1": feat1, "feat2": feat2}


def verify_broken(repo: GitRepo, labels: dict[str, str]) -> None:
    """Assert the repo is in exactly the broken state described above.
    If this fails, the scenario is wrong, not the agent."""
    assert repo.head_is_attached(), "HEAD should be on main"
    assert repo.rev("HEAD") == labels["main_tip"], "main should be unchanged"
    assert repo.is_clean(), "working tree should be clean"

    #The defining feature of this scenario: the branch is gone.
    gone = repo.run("rev-parse", "--verify", "--quiet", "refs/heads/feature")
    assert gone.returncode != 0, "feature branch should be deleted"
    branch_reflog = repo.path / ".git" / "logs" / "refs" / "heads" / "feature"
    assert not branch_reflog.exists(), "git branch -D should have removed the branch's reflog"

    for label in ("feat1", "feat2"):
        sha = labels[label]
        assert repo.refs_containing(sha) == [], f"{label} should not be on any ref"
        assert repo.in_reflog(sha), f"{label} should still be recoverable from HEAD's reflog"


def solve(repo: GitRepo, labels: dict[str, str]) -> None:
    """Reference rescue: recreate the branch at its last commit."""
    repo.git("branch", "feature", labels["feat2"])


def _merge_into_main(repo: GitRepo, labels: dict[str, str]) -> None:
    #Recovers the work, but puts unfinished code on main, which the user
    #explicitly said not to do.
    repo.git("merge", "--quiet", labels["feat2"])


def _restore_first_commit_only(repo: GitRepo, labels: dict[str, str]) -> None:
    # Picks the wrong line from the reflog: recovers one day of work, not two.
    repo.git("branch", "feature", labels["feat1"])


WRONG_FIXES = {
    "merge_into_main": _merge_into_main,
    "restore_first_commit_only": _restore_first_commit_only,
}
