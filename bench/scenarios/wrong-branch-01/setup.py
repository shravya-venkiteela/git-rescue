from bench.gitenv import GitRepo

SCENARIO_ID = "wrong-branch-01"  #must match the folder name; the loader checks

def verify_broken(repo: GitRepo, labels: dict[str, str]) -> None:
    """Assert the repo is in exactly the broken state described above.
    If this fails, the scenario is wrong, not the agent."""
    assert repo.head_is_attached(), "HEAD should be on main"
    assert repo.git("symbolic-ref", "--short", "HEAD") == "main", "the user is on main"
    assert repo.rev("refs/heads/main") == labels["wip2"], "main should have the misplaced commits"
    assert repo.rev("refs/heads/feature") == labels["base"], "feature should still be at base"
    assert repo.is_clean(), "working tree should be clean"

    #The defining check: nothing is lost. Unlike every recovery scenario so
    #far, the work is on a branch; it's just the wrong one.
    for label in ("wip1", "wip2"):
        assert "refs/heads/main" in repo.refs_containing(labels[label]), f"{label} should be on main"
        assert "refs/heads/feature" not in repo.refs_containing(labels[label]), f"{label} should not be on feature"


def build(repo: GitRepo) -> dict[str, str]:
    repo.commit_file("app.py", "def main():\n    return 1\n", "Initial app")
    base = repo.commit_file("README.md", "# App\n", "Add readme")

    #The user creates the branch, but `git branch` doesn't switch to it.
    repo.git("branch", "feature")

    wip1 = repo.commit_file("search.py", "def search(q):\n    return []\n", "Add search stub")
    wip2 = repo.commit_file("search.py", "def search(q):\n    return [q]\n", "Return query from search")

    return {"base": base, "wip1": wip1, "wip2": wip2}


def solve(repo: GitRepo, labels: dict[str, str]) -> None:
    """Reference rescue: point feature at the work, then move main back.
    Order matters: move main first and the commits are briefly on no branch."""
    repo.git("branch", "--force", "feature", labels["wip2"])
    repo.git("reset", "--quiet", "--hard", labels["base"])


def _cherry_pick_then_reset(repo: GitRepo, labels: dict[str, str]) -> None:
    #Also correct: copy the commits to feature (new SHAs), then move main back.
    repo.git("checkout", "--quiet", "feature")
    repo.git("cherry-pick", labels["wip1"], labels["wip2"])
    repo.git("checkout", "--quiet", "main")
    repo.git("reset", "--quiet", "--hard", labels["base"])


ALT_SOLUTIONS = {"cherry_pick_then_reset": _cherry_pick_then_reset}


def _move_feature_only(repo: GitRepo, labels: dict[str, str]) -> None:
    #Half a fix: the work is on feature now, but main still has it too.
    repo.git("branch", "--force", "feature", labels["wip2"])


def _reset_main_only(repo: GitRepo, labels: dict[str, str]) -> None:
    #The dangerous half: main is clean, and the work is now on no branch.
    repo.git("reset", "--quiet", "--hard", labels["base"])


def _revert_on_main(repo: GitRepo, labels: dict[str, str]) -> None:
    #The right answer IF main had been pushed. This user hasn't pushed, so
    #rewriting is fine and two extra revert commits are clutter they didn't ask for.
    repo.git("revert", "--no-edit", labels["wip2"], labels["wip1"])


WRONG_FIXES = {
    "move_feature_only": _move_feature_only,
    "reset_main_only": _reset_main_only,
    "revert_on_main": _revert_on_main,
}
