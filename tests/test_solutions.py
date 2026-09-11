import pytest

from bench.gitenv import GitRepo
from bench.harness.assertions import evaluate, validate
from bench.harness.checker import check, take_snapshot
from bench.loader import load_all

SCENARIOS = load_all()
WRONG = [(s, name) for s in SCENARIOS for name in getattr(s.module, "WRONG_FIXES", {})]


def fresh(scenario, root):
    repo = GitRepo.init(root / "repo", root / "home")
    return repo, scenario.module.build(repo)


def may_discard(scenario, labels):
    """SHAs/blob ids the scenario says the user doesn't mind losing."""
    return frozenset(labels[name] for name in scenario.spec.get("may_discard", []))


def failing(scenario, repo, labels):
    return [r.spec for r in evaluate(repo.path, scenario.spec["assertions"], labels) if not r.passed]


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda s: s.id)
def test_assertions_are_valid(scenario):
    assert validate(scenario.spec["assertions"]) == []


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda s: s.id)
def test_may_discard_labels_exist(scenario, tmp_path):
    _, labels = fresh(scenario, tmp_path)
    unknown = set(scenario.spec.get("may_discard", [])) - set(labels)
    assert not unknown, f"may_discard names {sorted(unknown)}, but build() only returned {sorted(labels)}"


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda s: s.id)
def test_scenario_defines_solve_and_wrong_fixes(scenario):
    assert callable(getattr(scenario.module, "solve", None)), "setup.py needs solve()"
    assert getattr(scenario.module, "WRONG_FIXES", None), "setup.py needs at least one WRONG_FIXES entry"


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda s: s.id)
def test_reference_solution_passes_with_no_loss(scenario, tmp_path):
    repo, labels = fresh(scenario, tmp_path)
    before = take_snapshot(repo.path)
    scenario.module.solve(repo, labels)
    assert failing(scenario, repo, labels) == [], "the reference solution fails these assertions"
    report = check(before, take_snapshot(repo.path), allowed_to_lose=may_discard(scenario, labels))
    assert report.losses == [], f"the reference solution lost data: {report.losses}"


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda s: s.id)
def test_doing_nothing_fails(scenario, tmp_path):
    repo, labels = fresh(scenario, tmp_path)
    assert failing(scenario, repo, labels), "the broken state already passes every assertion"


@pytest.mark.parametrize("scenario,fix_name", WRONG, ids=lambda x: x if isinstance(x, str) else x.id)
def test_wrong_fix_fails(scenario, fix_name, tmp_path):
    repo, labels = fresh(scenario, tmp_path)
    scenario.module.WRONG_FIXES[fix_name](repo, labels)
    assert failing(scenario, repo, labels), (
        f"wrong fix '{fix_name}' passes every assertion: the assertions don't capture the intent"
    )
