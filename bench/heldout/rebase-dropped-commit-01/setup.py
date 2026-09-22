from bench.gitenv import GitRepo

SCENARIO_ID = "rebase-dropped-commit-01"  #must match the folder name; the loader checks

MODEL = "class Cart:\n    def __init__(self):\n        self.items = []\n"
TOTAL = MODEL + "\n    def total(self):\n        return sum(i.price for i in self.items)\n"
TESTS = "from cart import Cart\n\ndef test_empty_cart():\n    assert Cart().items == []\n"


def verify_broken(repo: GitRepo, labels: dict[str, str]) -> None:
    assert repo.head_is_attached() and repo.git("symbolic-ref", "--short", "HEAD") == "feature"
    assert repo.rev("refs/heads/main") == labels["main_new"], "main must be untouched"
    assert repo.run("merge-base", "--is-ancestor", labels["main_new"], "feature").returncode == 0, \
        "feature should be rebased onto the new main"
    subjects = repo.git("log", "--format=%s", "main..feature").splitlines()
    assert subjects == ["Add cart tests", "Add cart model"], f"one commit should be missing, got {subjects}"
    assert "def total" not in (repo.path / "cart.py").read_text()
    assert repo.refs_containing(labels["total"]) == [], "the dropped commit is on no branch"
    assert repo.in_reflog(labels["total"]), "it is still in the reflog (the old feature tip's history)"
    assert repo.is_clean() and not (repo.path / ".git" / "rebase-merge").exists()


def build(repo: GitRepo) -> dict[str, str]:
    repo.commit_file("README.md", "# shop\n", "Initial commit")
    repo.git("branch", "feature")
    main_new = repo.commit_file("README.md", "# shop\n\nRun with: python app.py\n", "Document how to run")
    repo.git("checkout", "--quiet", "feature")
    model = repo.commit_file("cart.py", MODEL, "Add cart model")
    total = repo.commit_file("cart.py", TOTAL, "Add cart total")
    tests = repo.commit_file("test_cart.py", TESTS, "Add cart tests")

    #`git rebase -i main`, with the "Add cart total" line deleted from the todo
    #list by mistake. The edited list is written out and used as the editor's
    #result, which is exactly what deleting the line in an editor produces.
    todo = repo.home / "edited-todo"
    todo.write_bytes(f"pick {model} Add cart model\npick {tests} Add cart tests\n".encode())
    repo.git("-c", f"sequence.editor=cp '{todo.as_posix()}'", "rebase", "-i", "--quiet", "main")
    return {"main_new": main_new, "model": model, "total": total, "tests": tests}


def solve(repo: GitRepo, labels: dict[str, str]) -> None:
    """Put the dropped change back on top of the rebased branch."""
    repo.git("cherry-pick", labels["total"])


def _undo_the_whole_rebase(repo: GitRepo, labels: dict[str, str]) -> None:
    #Gets the commit back by throwing away the rebase the user wanted.
    repo.git("reset", "--quiet", "--hard", labels["tests"])


def _check_out_the_lost_commit(repo: GitRepo, labels: dict[str, str]) -> None:
    #The change is visible again, but on a detached HEAD, not on feature.
    repo.git("checkout", "--quiet", labels["total"])


WRONG_FIXES = {
    "undo_the_whole_rebase": _undo_the_whole_rebase,
    "check_out_the_lost_commit": _check_out_the_lost_commit,
}
