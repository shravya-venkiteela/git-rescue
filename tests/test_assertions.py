from pathlib import Path
from bench.gitenv import GitRepo
from bench.harness.assertions import content_reachable_from_local_branch, worktree_file_matches_commit
from bench.loader import SCENARIOS_DIR, load
def built(name, tmp_path):
    scenario = load(SCENARIOS_DIR / name)
    repo = GitRepo.init(tmp_path / "repo", tmp_path / "home")
    return scenario, repo, scenario.module.build(repo)


def test_cherry_picked_copy_counts_as_recovered(tmp_path):
    """An agent that cherry-picks the fixes onto main creates new SHAs.
    That is a correct rescue and must be recognized as one."""
    _, repo, labels = built("detached-head-01", tmp_path)
    repo.git("cherry-pick", labels["fix1"], labels["fix2"])
    assert content_reachable_from_local_branch(repo.path, labels["fix1"])
    assert content_reachable_from_local_branch(repo.path, labels["fix2"])


def test_unrelated_commit_does_not_count_as_recovered(tmp_path):
    _, repo, labels = built("detached-head-01", tmp_path)
    repo.commit_file("other.py", "unrelated\n", "Unrelated work")
    assert not content_reachable_from_local_branch(repo.path, labels["fix1"])


def test_crlf_checkout_still_matches(tmp_path):
    """A user whose git converts line endings still got their work back."""
    scenario, repo, labels = built("dropped-stash-01", tmp_path)
    scenario.module.solve(repo, labels)
    f = repo.path / "login.py"
    f.write_bytes(f.read_bytes().replace(b"\n", b"\r\n"))
    assert worktree_file_matches_commit(repo.path, labels["stash"], "login.py")