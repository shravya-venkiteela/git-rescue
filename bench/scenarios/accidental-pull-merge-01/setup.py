from bench.gitenv import GitRepo

SCENARIO_ID = "accidental-pull-merge-01"  #must match the folder name; the loader checks

def verify_broken(repo: GitRepo, labels: dict[str, str]) -> None:
    """Assert the repo is in exactly the broken state described above.
    If this fails, the scenario is wrong, not the agent."""
    assert repo.head_is_attached(), "HEAD should be on main"
    assert repo.is_clean(), "working tree should be clean"

    assert repo.rev("refs/heads/main") == labels["merge"], "main should be at the merge commit"
    parents = repo.git("rev-list", "--parents", "-1", labels["merge"]).split()[1:]
    assert parents == [labels["local_tip"], labels["upstream_tip"]], "main should be a merge of local and upstream work"

    #The defining check: a pull made it, not a deliberate merge.
    last_action = repo.git("reflog", "-1", "--format=%gs")
    assert last_action.startswith("pull"), f"newest reflog entry should be the pull, got {last_action!r}"


def build(repo: GitRepo) -> dict[str, str]:
    base = repo.commit_file("app.py", "def main():\n    return 1\n", "Initial app")

    #The "remote": a sibling repo that starts as a copy of this one.
    upstream = GitRepo(path=repo.path.parent / "upstream", home=repo.home)
    repo.git("clone", "--quiet", ".", str(upstream.path))
    upstream.git("checkout", "--quiet", "main")
    repo.git("remote", "add", "origin", "../upstream")

    #A teammate pushes work upstream.
    upstream_tip = upstream.commit_file("docs.md", "# Docs\n", "Add docs")

    #while the user commits locally, then pulls without --rebase.
    local_tip = repo.commit_file("api.py", "def api():\n    return {}\n", "Add api stub")
    repo.git("pull", "--quiet", "--no-rebase", "--no-edit", "origin", "main")
    #Recorded so golden.json covers the merge commit too: its message
    #contains the remote URL, the most platform-sensitive part of this build.
    merge = repo.rev("HEAD")

    return {"base": base, "local_tip": local_tip, "upstream_tip": upstream_tip, "merge": merge}


def solve(repo: GitRepo, labels: dict[str, str]) -> None:
    """Reference rescue: move main back to the user's own commit."""
    repo.git("reset", "--quiet", "--hard", labels["local_tip"])


def _reset_to_first_parent(repo: GitRepo, labels: dict[str, str]) -> None:
    repo.git("reset", "--quiet", "--hard", "HEAD~1")


def _reset_to_orig_head(repo: GitRepo, labels: dict[str, str]) -> None:
    #Correct here because nothing has moved ORIG_HEAD since the pull.
    repo.git("reset", "--quiet", "--hard", "ORIG_HEAD")


ALT_SOLUTIONS = {
    "reset_to_first_parent": _reset_to_first_parent,
    "reset_to_orig_head": _reset_to_orig_head,
}


def _reset_to_remote(repo: GitRepo, labels: dict[str, str]) -> None:
    #"Make my branch match the remote": removes the merge and the user's own commit.
    repo.git("reset", "--quiet", "--hard", "origin/main")


def _revert_the_merge(repo: GitRepo, labels: dict[str, str]) -> None:
    #Right if the merge had been pushed. It wasn't, and a revert leaves the
    #merge in history plus a second commit the user didn't ask for.
    repo.git("revert", "--no-edit", "-m", "1", "HEAD")


WRONG_FIXES = {
    "reset_to_remote": _reset_to_remote,
    "revert_the_merge": _revert_the_merge,
}
