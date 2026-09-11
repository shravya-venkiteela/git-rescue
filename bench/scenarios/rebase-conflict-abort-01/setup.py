import shutil
from bench.gitenv import GitRepo

SCENARIO_ID = "rebase-conflict-abort-01"  #must match the folder name; the loader checks


def verify_broken(repo: GitRepo, labels: dict[str, str]) -> None:
    """Assert the repo is in exactly the broken state described above.
    If this fails, the scenario is wrong, not the agent."""
    rebase_dir = repo.path / ".git" / "rebase-merge"
    assert rebase_dir.is_dir(), "a rebase should be in progress"
    assert (rebase_dir / "head-name").read_text().strip() == "refs/heads/feature", "it should be rebasing feature"
    assert not repo.head_is_attached(), "HEAD is detached during a rebase"

    assert repo.rev("refs/heads/feature") == labels["feature_tip"], "feature has not moved yet"
    assert repo.rev("refs/heads/main") == labels["main_tip"], "main is unchanged"

    conflicted = repo.git("diff", "--name-only", "--diff-filter=U")
    assert conflicted == "a.txt", f"a.txt should be the one conflicted file, got {conflicted!r}"
    assert "<<<<<<<" in (repo.path / "a.txt").read_text(), "a.txt should contain conflict markers"


def build(repo: GitRepo) -> dict[str, str]:
    base = repo.commit_file("a.txt", "base\n", "Base")

    repo.git("checkout", "--quiet", "-b", "feature")
    feature_tip = repo.commit_file("a.txt", "feature version\n", "Feature change")

    repo.git("checkout", "--quiet", "main")
    main_tip = repo.commit_file("a.txt", "main version\n", "Main change")

    #The user updates their branch with the latest main and hits a conflict.
    repo.git("checkout", "--quiet", "feature")
    result = repo.run("rebase", "main")
    assert result.returncode != 0, "the rebase should stop on a conflict"

    #The file git wrote with conflict markers. Aborting discards it, which
    #is correct here because the user never edited it. See may_discard.
    conflict_file = repo.git("hash-object", "a.txt")

    return {"base": base, "feature_tip": feature_tip, "main_tip": main_tip, "conflict_file": conflict_file}


def solve(repo: GitRepo, labels: dict[str, str]) -> None:
    """Reference rescue: abort the rebase, restoring feature as it was."""
    repo.git("rebase", "--abort")


def _skip_the_commit(repo: GitRepo, labels: dict[str, str]) -> None:
     #git's own hint suggests `git rebase --skip`. It ends the rebase, but
    #by dropping the user's commit: feature ends up identical to main.
    repo.git("rebase", "--skip")


def _branch_off_detached_head(repo: GitRepo, labels: dict[str, str]) -> None:
    #The detached-HEAD fix applied to the wrong problem. `git branch`
    #shows "(no branch, rebasing feature)", so an agent makes a branch,
    #and leaves the rebase half-done.
    #Plain form on purpose: `checkout --quiet -b` refuses mid-rebase, but
    #plain `checkout -b` takes a shortcut that skips the index check.
    repo.git("checkout", "-b", "rescued")


def _delete_rebase_folder(repo: GitRepo, labels: dict[str, str]) -> None:
    #A real answer found online: delete .git/rebase-merge to "get out".
    #git stops reporting a rebase, but HEAD stays detached and the
    #conflict markers stay in the file.
    shutil.rmtree(repo.path / ".git" / "rebase-merge")


WRONG_FIXES = {
    "skip_the_commit": _skip_the_commit,
    "branch_off_detached_head": _branch_off_detached_head,
    "delete_rebase_folder": _delete_rebase_folder,
}
