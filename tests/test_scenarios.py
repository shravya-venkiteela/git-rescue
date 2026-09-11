"""Checks every scenario in bench/scenarios/. New scenarios are picked up
automatically; you never need to edit this file."""
import pytest
import json
from bench.gitenv import BASE_EPOCH, GitRepo
from bench.loader import load_all

SCENARIOS = load_all()

def build_fresh(scenario, root):
    repo = GitRepo.init(root / "repo", root / "home")
    labels = scenario.module.build(repo)
    return repo, labels

@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda s: s.id)
def test_builds_into_intended_broken_state(scenario, tmp_path):
    repo, labels = build_fresh(scenario, tmp_path)
    scenario.module.verify_broken(repo, labels)

@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda s: s.id)
def test_build_is_deterministic(scenario, tmp_path):
    repo, first = build_fresh(scenario, tmp_path / "a")
    _, second = build_fresh(scenario, tmp_path / "b")
    assert first == second, "same setup script must produce the same SHAs"

    #Comparing two builds alone isn't enough: if dates weren't pinned, two
    #builds within the same second would still match by coincidence.
    #So check every commit and reflog timestamp comes from the fixed clock.
    stamps = repo.git("log", "--all", "--reflog", "--format=%at %ct").split()
    assert stamps, "scenario produced no commits"
    upper = BASE_EPOCH + 10_000_000
    unpinned = [s for s in stamps if not BASE_EPOCH <= int(s) < upper]
    assert not unpinned, f"unpinned timestamps {unpinned}: are all git calls going through GitRepo?"


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda s: s.id)
def test_assertion_labels_exist(scenario, tmp_path):
    _, labels = build_fresh(scenario, tmp_path)
    for assertion in scenario.spec["assertions"]:
        if "label" in assertion:
            assert assertion["label"] in labels, (
                f"assertion refers to '{assertion['label']}', "
                f"but build() only returned {sorted(labels)}"
            )
@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda s: s.id)
def test_matches_golden_shas(scenario, tmp_path):
    """Same SHAs on every machine and OS. If this fails, something
    platform-specific (line endings, config, clock) leaked into the build."""
    golden = scenario.dir / "golden.json"
    assert golden.exists(), f"{scenario.id} has no golden.json; generate it and commit it"
    _, labels = build_fresh(scenario, tmp_path)
    assert labels == json.loads(golden.read_text(encoding="utf-8")), (
        "SHAs differ from golden.json: something platform-specific leaked into the build"
    )

def test_at_least_one_scenario_found():
    assert SCENARIOS, "no scenarios found under bench/scenarios/"