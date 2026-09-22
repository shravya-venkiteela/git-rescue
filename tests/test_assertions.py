from pathlib import Path
import pytest
from bench.harness.assertions import content_reachable_from_local_branch, worktree_file_matches_commit
from bench.loader import SCENARIOS_DIR, load

def copy_of(name, built):
    scenario = load(SCENARIOS_DIR / name)
    return (scenario, *built(scenario))


def test_cherry_picked_copy_counts_as_recovered(built):
    """An agent that cherry-picks the fixes onto main creates new SHAs.
    That is a correct rescue and must be recognized as one."""
    _, repo, labels = copy_of("detached-head-01", built)
    repo.git("cherry-pick", labels["fix1"], labels["fix2"])
    assert content_reachable_from_local_branch(repo.path, labels["fix1"])
    assert content_reachable_from_local_branch(repo.path, labels["fix2"])


def test_unrelated_commit_does_not_count_as_recovered(built):
    _, repo, labels = copy_of("detached-head-01", built)
    repo.commit_file("other.py", "unrelated\n", "Unrelated work")
    assert not content_reachable_from_local_branch(repo.path, labels["fix1"])


def test_crlf_checkout_still_matches(built):
    """A user whose git converts line endings still got their work back."""
    scenario, repo, labels = copy_of("dropped-stash-01", built)
    scenario.module.solve(repo, labels)
    f = repo.path / "login.py"
    f.write_bytes(f.read_bytes().replace(b"\n", b"\r\n"))
    assert worktree_file_matches_commit(repo.path, labels["stash"], "login.py")


@pytest.mark.parametrize("message,expected", [
    ("Those edits were never committed, so they cannot be recovered.", True),
    ("Cannot be recovered: uncommitted changes to login.py.", True),
    ("Unfortunately the files are permanently deleted.", True),
    ("git clean removed them; they are gone for good.", True),
    ("There's no way to get those changes back.", True),
    ("Your commits can be recovered from the reflog.", False),
    ("Run git branch feature ced977b to restore it.", False),
    ("", False),
])
def test_says_unrecoverable(message, expected):
    from bench.harness.assertions import says_unrecoverable
    assert says_unrecoverable(Path("."), message) is expected


@pytest.mark.parametrize("message,expected", [
    ("Rotate the exposed secret first: a committed secret must be treated as leaked.", True),
    ("Revoke that API key in your provider's dashboard now.", True),
    ("The token should be regenerated before anything else.", True),
    ("I removed .env from the commit and added it to .gitignore.", False),
])
def test_says_to_rotate_secret(message, expected):
    from bench.harness.assertions import says_to_rotate_secret
    assert says_to_rotate_secret(Path("."), message) is expected


def test_message_assertions_validate_and_receive_the_message():
    from bench.harness.assertions import evaluate, validate
    specs = [{"type": "says_unrecoverable"}]
    assert validate(specs) == []
    assert evaluate(Path("."), specs, {}, message="it is lost")[0].passed
    assert not evaluate(Path("."), specs, {}, message="")[0].passed
