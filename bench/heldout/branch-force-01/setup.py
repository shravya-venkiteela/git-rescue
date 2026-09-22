from bench.gitenv import GitRepo

SCENARIO_ID = "branch-force-01"  #must match the folder name; the loader checks


def verify_broken(repo: GitRepo, labels: dict[str, str]) -> None:
    assert repo.head_is_attached() and repo.git("symbolic-ref", "--short", "HEAD") == "feature"
    assert repo.rev("refs/heads/main") == labels["moved_to"], "main should have been forced back"
    assert repo.rev("refs/heads/feature") == labels["feature_tip"]
    for label in ("stub", "main_tip"):
        assert repo.refs_containing(labels[label]) == [], f"{label} should be on no branch"
    #The defining check: the move is recorded in main's own reflog.
    last = repo.git("reflog", "-1", "--format=%gs", "refs/heads/main")
    assert last.startswith("branch: Reset to"), f"main's newest reflog entry should be the force, got {last!r}"
    assert repo.is_clean()


def build(repo: GitRepo) -> dict[str, str]:
    repo.commit_file("app.py", "def main():\n    pass\n", "Initial app")
    moved_to = repo.commit_file("README.md", "# shop\n", "Add readme")
    repo.git("checkout", "--quiet", "-b", "feature")
    feature_tip = repo.commit_file("cart.py", "class Cart:\n    pass\n", "Start cart")
    repo.git("checkout", "--quiet", "main")
    stub = repo.commit_file("search.py", "def search(query):\n    pass\n", "Add search stub")
    main_tip = repo.commit_file("search.py", "def search(query):\n    return query\n",
                                "Return query from search")
    repo.git("checkout", "--quiet", "feature")
    #Meant for another branch. Git refuses to force-move the checked-out
    #branch, so this only works because the user is on feature.
    repo.git("branch", "-f", "main", moved_to)
    return {"moved_to": moved_to, "feature_tip": feature_tip, "stub": stub, "main_tip": main_tip}


def solve(repo: GitRepo, labels: dict[str, str]) -> None:
    repo.git("branch", "-f", "main", labels["main_tip"])


def _move_main_one_short(repo: GitRepo, labels: dict[str, str]) -> None:
    #Off by one in main's reflog: gets the stub back, not the last commit.
    repo.git("branch", "-f", "main", labels["stub"])


def _reset_the_current_branch(repo: GitRepo, labels: dict[str, str]) -> None:
    #"reset --hard to the lost commit" while on feature: main stays broken
    #and feature's own commit is thrown off it.
    repo.git("reset", "--quiet", "--hard", labels["main_tip"])


WRONG_FIXES = {
    "move_main_one_short": _move_main_one_short,
    "reset_the_current_branch": _reset_the_current_branch,
}
