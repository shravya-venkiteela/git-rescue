from bench.gitenv import GitRepo

SCENARIO_ID = "deleted-file-committed-01"  #must match the folder name; the loader checks

CONFIG = "DEBUG = False\nDATABASE = 'shop.db'\n"


def verify_broken(repo: GitRepo, labels: dict[str, str]) -> None:
    assert repo.head_is_attached() and repo.rev("refs/heads/main") == labels["readme"]
    assert not (repo.path / "config.py").exists(), "config.py should be deleted"
    assert repo.git("log", "-1", "--format=%s", labels["removed"]) == "Remove unused config"
    assert repo.run("cat-file", "-e", f"{labels['with_config']}:config.py").returncode == 0, \
        "an earlier commit still has config.py"
    assert repo.is_clean()


def build(repo: GitRepo) -> dict[str, str]:
    repo.commit_file("app.py", "import config\n\nprint(config.DATABASE)\n", "Add app")
    with_config = repo.commit_file("config.py", CONFIG, "Add config")
    repo.git("rm", "--quiet", "config.py")
    repo.git("commit", "--quiet", "-m", "Remove unused config")
    removed = repo.rev("HEAD")
    readme = repo.commit_file("README.md", "# shop\n\nA small shop app.\n", "Update README")
    return {"with_config": with_config, "removed": removed, "readme": readme}


def solve(repo: GitRepo, labels: dict[str, str]) -> None:
    repo.git("revert", "--no-edit", labels["removed"])


def _restore_file_from_history(repo: GitRepo, labels: dict[str, str]) -> None:
    #Equally right: the file is back (staged), nothing else touched.
    repo.git("checkout", labels["with_config"], "--", "config.py")


ALT_SOLUTIONS = {"restore_file_from_history": _restore_file_from_history}


def _reset_to_before_the_deletion(repo: GitRepo, labels: dict[str, str]) -> None:
    #config.py is back, and the README commit is gone with it.
    repo.git("reset", "--quiet", "--hard", labels["with_config"])


def _revert_the_latest_commit(repo: GitRepo, labels: dict[str, str]) -> None:
    #"Undo the last commit" undoes the wrong one.
    repo.git("revert", "--no-edit", "HEAD")


def _check_out_the_old_commit(repo: GitRepo, labels: dict[str, str]) -> None:
    repo.git("checkout", "--quiet", labels["with_config"])


WRONG_FIXES = {
    "reset_to_before_the_deletion": _reset_to_before_the_deletion,
    "revert_the_latest_commit": _revert_the_latest_commit,
    "check_out_the_old_commit": _check_out_the_old_commit,
}
