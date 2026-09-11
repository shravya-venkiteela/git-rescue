from bench.gitenv import GitRepo

SCENARIO_ID = "reset-hard-staged-01"  #must match the folder name; the loader checks

EDIT = "def checkout(cart):\n    return sum(item.price for item in cart)\n"


def _unreachable_blobs(repo: GitRepo) -> set[str]:
    out = repo.git("fsck", "--unreachable", "--no-reflogs")
    return {line.split()[2] for line in out.splitlines() if line.startswith("unreachable blob ")}


def verify_broken(repo: GitRepo, labels: dict[str, str]) -> None:
    """Assert the repo is in exactly the broken state described above.
    If this fails, the scenario is wrong, not the agent."""
    assert repo.head_is_attached(), "HEAD should be on main"
    assert repo.rev("refs/heads/main") == labels["main_tip"], "reset --hard HEAD does not move main"
    assert repo.is_clean(), "the staged edit should be gone from the working tree and index"
    assert (repo.path / "cart.py").read_text() != EDIT, "the file should be back to its committed version"

    #The defining check: the work exists only as a dangling blob. This is
    #what separates it from the dropped stash, where fsck finds a commit.
    assert labels["staged_blob"] in _unreachable_blobs(repo), "the staged edit should survive as an unreachable blob"
    assert repo.unreachable_commits() == set(), "no commit ever held this work"


def build(repo: GitRepo) -> dict[str, str]:
    repo.commit_file("README.md", "# Shop\n", "Add readme")
    main_tip = repo.commit_file("cart.py", "def checkout(cart):\n    return 0\n", "Stub checkout")

    #Real work, staged but never committed.
    repo.write("cart.py", EDIT)
    repo.git("add", "cart.py")
    staged_blob = repo.git("rev-parse", ":cart.py")

    #"Cleaning up" something else, the user wipes everything uncommitted.
    repo.git("reset", "--quiet", "--hard")

    return {"main_tip": main_tip, "staged_blob": staged_blob}


def solve(repo: GitRepo, labels: dict[str, str]) -> None:
    """Reference rescue: write the dangling blob's content back to the file."""
    content = repo.run("cat-file", "blob", labels["staged_blob"]).stdout
    repo.write("cart.py", content)


def _restore_via_index(repo: GitRepo, labels: dict[str, str]) -> None:
    #Pure-git alternative: put the blob back in the index, then check it out.
    repo.git("update-index", "--cacheinfo", f"100644,{labels['staged_blob']},cart.py")
    repo.git("checkout", "--", "cart.py")


ALT_SOLUTIONS = {"restore_via_index": _restore_via_index}


def _reflog_reset(repo: GitRepo, labels: dict[str, str]) -> None:
    #The reset-over-commits fix applied to the wrong problem. HEAD@{1} is
    #the same commit HEAD is on, so this changes nothing: the work was never
    #in any commit the reflog could point at.
    repo.git("reset", "--quiet", "--hard", "HEAD@{1}")


WRONG_FIXES = {"reflog_reset": _reflog_reset}
