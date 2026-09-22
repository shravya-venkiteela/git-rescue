import pytest
from bench.harness.assertions import evaluate, validate
from bench.harness.checker import check, take_snapshot
from bench.loader import HELDOUT_DIR, load_all

#Held-out scenarios are checked here too: this runs their reference and
#wrong solutions, never a model, so it reveals nothing about any system.
SCENARIOS = load_all() + load_all(HELDOUT_DIR)
WRONG = [(s, name) for s in SCENARIOS for name in getattr(s.module, "WRONG_FIXES", {})]
ALT = [(s, name) for s in SCENARIOS for name in getattr(s.module, "ALT_SOLUTIONS", {})]


def may_discard(scenario, labels):
    """SHAs/blob ids the scenario says the user doesn't mind losing."""
    return frozenset(labels[name] for name in scenario.spec.get("may_discard", []))


def failing(scenario, repo, labels, said=""):
    return [r.spec for r in evaluate(repo.path, scenario.spec["assertions"], labels, message=said or "")
            if not r.passed]


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda s: s.id)
def test_assertions_are_valid(scenario):
    assert validate(scenario.spec["assertions"]) == []


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda s: s.id)
def test_may_discard_labels_exist(scenario, template):
    _, labels = template(scenario)
    unknown = set(scenario.spec.get("may_discard", [])) - set(labels)
    assert not unknown, f"may_discard names {sorted(unknown)}, but build() only returned {sorted(labels)}"


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda s: s.id)
def test_scenario_defines_solve_and_wrong_fixes(scenario):
    assert callable(getattr(scenario.module, "solve", None)), "setup.py needs solve()"
    assert getattr(scenario.module, "WRONG_FIXES", None), "setup.py needs at least one WRONG_FIXES entry"


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda s: s.id)
def test_reference_solution_passes_with_no_loss(scenario, built):
    repo, labels = built(scenario)
    before = take_snapshot(repo.path)
    said = scenario.module.solve(repo, labels)
    assert failing(scenario, repo, labels, said) == [], "the reference solution fails these assertions"
    report = check(before, take_snapshot(repo.path), allowed_to_lose=may_discard(scenario, labels))
    assert report.losses == [], f"the reference solution lost data: {report.losses}"


@pytest.mark.parametrize("scenario,alt_name", ALT, ids=lambda x: x if isinstance(x, str) else x.id)
def test_alternative_solution_passes_with_no_loss(scenario, alt_name, built):
    repo, labels = built(scenario)
    before = take_snapshot(repo.path)
    said = scenario.module.ALT_SOLUTIONS[alt_name](repo, labels)
    assert failing(scenario, repo, labels, said) == [], f"correct alternative '{alt_name}' fails these assertions"
    report = check(before, take_snapshot(repo.path), allowed_to_lose=may_discard(scenario, labels))
    assert report.losses == [], f"alternative '{alt_name}' lost data: {report.losses}"


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda s: s.id)
def test_doing_nothing_fails(scenario, built):
    repo, labels = built(scenario)
    assert failing(scenario, repo, labels), "the broken state already passes every assertion"


@pytest.mark.parametrize("scenario,fix_name", WRONG, ids=lambda x: x if isinstance(x, str) else x.id)
def test_wrong_fix_fails(scenario, fix_name, built):
    repo, labels = built(scenario)
    said = scenario.module.WRONG_FIXES[fix_name](repo, labels)
    assert failing(scenario, repo, labels, said), (
        f"wrong fix '{fix_name}' passes every assertion: the assertions don't capture the intent"
    )
