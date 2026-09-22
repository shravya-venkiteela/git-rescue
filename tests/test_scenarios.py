import json
import pytest
from bench.gitenv import BASE_EPOCH, GitRepo
from bench.loader import HELDOUT_DIR, load_all

SCENARIOS = load_all() + load_all(HELDOUT_DIR)


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda s: s.id)
def test_builds_into_intended_broken_state(scenario, built):
    repo, labels = built(scenario)
    scenario.module.verify_broken(repo, labels)


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda s: s.id)
def test_build_is_deterministic(scenario, template, tmp_path):
    #The one test that must build for real: it compares an independent
    #second build against the session's template build.
    _, first = template(scenario)
    repo = GitRepo.init(tmp_path / "repo", tmp_path / "home")
    second = scenario.module.build(repo)
    assert first == second, "same setup script must produce the same SHAs"

    #Two builds in the same second would match even without pinned dates,
    #so also check every timestamp comes from the fixed clock.
    stamps = repo.git("log", "--all", "--reflog", "--format=%at %ct").split()
    assert stamps, "scenario produced no commits"
    upper = BASE_EPOCH + 10_000_000
    unpinned = [s for s in stamps if not BASE_EPOCH <= int(s) < upper]
    assert not unpinned, f"unpinned timestamps {unpinned}: are all git calls going through GitRepo?"


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda s: s.id)
def test_assertion_labels_exist(scenario, template):
    _, labels = template(scenario)
    for assertion in scenario.spec["assertions"]:
        if "label" in assertion:
            assert assertion["label"] in labels, (
                f"assertion refers to '{assertion['label']}', "
                f"but build() only returned {sorted(labels)}"
            )


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda s: s.id)
def test_matches_golden_shas(scenario, template):
    """Same SHAs on every machine and OS. If this fails, something
    platform-specific (line endings, config, clock) leaked into the build."""
    golden = scenario.dir / "golden.json"
    assert golden.exists(), f"{scenario.id} has no golden.json; generate it and commit it"
    _, labels = template(scenario)
    assert labels == json.loads(golden.read_text(encoding="utf-8")), (
        "SHAs differ from golden.json: something platform-specific leaked into the build"
    )


def test_at_least_one_scenario_found():
    assert SCENARIOS, "no scenarios found under bench/scenarios/"
