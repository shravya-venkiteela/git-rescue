from bench.gitenv import GitRepo
SCENARIO_ID = "bad-amend-01"  #must match the folder name; the loader checks

def verify_broken(repo: GitRepo, labels: dict[str, str]) -> None:
    """Assert the repo is in exactly the broken state described above.
    If this fails, the scenario is wrong, not the agent."""
    assert repo.head_is_attached(), "HEAD should be on main"
    assert repo.rev("refs/heads/main") == labels["amended"], "main should be at the amended commit"
    assert repo.is_clean(), "working tree should be clean"
    assert repo.rev(labels["amended"] + "^") == labels["before"], "amend replaces the tip; the parent is unchanged"

    original = labels["original"]
    assert repo.refs_containing(original) == [], "the original commit should be on no ref"
    assert repo.in_reflog(original), "the original commit should still be in the reflog"

    #The defining check.
    last_action = repo.git("reflog", "-1", "--format=%gs")
    assert last_action.startswith("commit (amend):"), f"newest reflog entry should be the amend, got {last_action!r}"


def build(repo: GitRepo) -> dict[str, str]:
    repo.commit_file("app.py", "def main():\n    return 1\n", "Initial app")
    before = repo.commit_file("login.py", "def login(user):\n    return user\n", "Add login")
    original = repo.commit_file("signup.py", "def signup(user):\n    return None\n", "Add signup stub")

    #A separate change to a different file, meant as its own commit...
    repo.write("login.py", "def login(user):\n    return user.strip()\n")
    repo.git("add", "login.py")
    #but the user reaches for --amend out of habit.
    repo.git("commit", "--quiet", "--amend", "-m", "Strip whitespace in login")
    amended = repo.rev("HEAD")

    return {"before": before, "original": original, "amended": amended}


def solve(repo: GitRepo, labels: dict[str, str]) -> None:
    """Reference rescue: move main back to the original commit while keeping
    the amended content staged, then commit it separately."""
    repo.git("reset", "--quiet", "--soft", labels["original"])
    repo.git("commit", "--quiet", "-m", "Strip whitespace in login")


def _soft_reset_via_reflog(repo: GitRepo, labels: dict[str, str]) -> None:
    #Same rescue, finding the original through the reflog instead of by SHA.
    repo.git("reset", "--quiet", "--soft", "HEAD@{1}")
    repo.git("commit", "--quiet", "-m", "Strip whitespace in login")


ALT_SOLUTIONS = {"soft_reset_via_reflog": _soft_reset_via_reflog}


def _hard_reset_to_original(repo: GitRepo, labels: dict[str, str]) -> None:
    #Gets the original commit back, but --hard throws away the new change.
    repo.git("reset", "--quiet", "--hard", labels["original"])


def _fix_message_only(repo: GitRepo, labels: dict[str, str]) -> None:
    #Treats it as a wrong-message problem. The two changes stay fused.
    repo.git("commit", "--quiet", "--amend", "-m", "Add signup stub")


def _soft_reset_without_commit(repo: GitRepo, labels: dict[str, str]) -> None:
    #Gets the original back and keeps the fix, but only staged: the user
    #asked for two commits and has one.
    repo.git("reset", "--quiet", "--soft", labels["original"])


WRONG_FIXES = {
    "hard_reset_to_original": _hard_reset_to_original,
    "fix_message_only": _fix_message_only,
    "soft_reset_without_commit": _soft_reset_without_commit,
}
