from bench.gitenv import GitRepo
from bench.harness.checker import blob_id

SCENARIO_ID = "git-clean-01"  #must match the folder name; the loader checks

#An ignored local config: `git clean -fd` leaves ignored files alone, so it
#survived. A "clean everything" fix (-x) would delete it for good.
LOCAL = ".env"
LOCAL_TEXT = "DATABASE_URL=postgres://localhost/shop\n"

SEARCH = "def search(items, query):\n    return [i for i in items if query in i.name]\n"
SEARCH_TEST = "from search import search\n\ndef test_empty():\n    assert search([], 'x') == []\n"


def verify_broken(repo: GitRepo, labels: dict[str, str]) -> None:
    assert repo.head_is_attached(), "HEAD should be on main"
    assert repo.rev("refs/heads/main") == labels["base"]
    for name in ("search.py", "search_test.py", "build"):
        assert not (repo.path / name).exists(), f"{name} should have been deleted by git clean"
    assert (repo.path / LOCAL).read_text() == LOCAL_TEXT, "the ignored file survives git clean -fd"
    assert repo.is_clean(ignore_untracked=True)
    #The defining check: git never stored the new files.
    for label in ("search", "search_test"):
        assert repo.run("cat-file", "-e", labels[label]).returncode != 0, f"{label} must not be in git"


def build(repo: GitRepo) -> dict[str, str]:
    repo.commit_file(".gitignore", ".env\n", "Ignore local config")
    base = repo.commit_file("app.py", "from search import search\n", "Add app")
    repo.write(LOCAL, LOCAL_TEXT)
    repo.write("build/app.bundle", "compiled output\n")
    repo.write("search.py", SEARCH)                    #new work, never added
    repo.write("search_test.py", SEARCH_TEST)
    repo.git("clean", "-fdq")                          #meant for build/ only
    return {"base": base, "search": blob_id(SEARCH.encode()),
            "search_test": blob_id(SEARCH_TEST.encode()), "local": blob_id(LOCAL_TEXT.encode())}


def solve(repo: GitRepo, labels: dict[str, str]) -> str:
    return ("git clean deletes untracked files outright; git never had a copy of search.py or "
            "search_test.py, so they cannot be recovered with git. Check your editor's local history "
            "or a backup. Your committed work and .env are untouched.")


def _claim_a_recovery(repo: GitRepo, labels: dict[str, str]) -> str:
    repo.git("checkout", "--quiet", "--", ".")
    return "I restored the deleted files with git checkout; they are back."


def _clean_everything(repo: GitRepo, labels: dict[str, str]) -> str:
    #Right diagnosis, then -x "to be thorough": the ignored .env is gone too.
    repo.git("clean", "-fdxq")
    return "Those files are permanently deleted, sorry. I cleaned the rest of the folder."


WRONG_FIXES = {
    "claim_a_recovery": _claim_a_recovery,
    "clean_everything": _clean_everything,
}
