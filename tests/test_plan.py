"""The plan schema is the agent's commitment device: if it can be vague,
it can repeat B2's failure of acting without a stated target."""
import pytest

from src.git_rescue.plan import PlanError, parse

GOOD = {"diagnosis": "branch deleted", "confidence": "high",
        "steps": [{"command": "git branch feature abc123", "purpose": "recreate", "risk": "reversible"}]}


def test_a_well_formed_plan_parses():
    plan = parse(GOOD)
    assert plan.steps[0].argv == ["git", "branch", "feature", "abc123"]
    assert plan.confidence == "high" and not plan.is_question_only


def test_questions_without_steps_are_allowed():
    plan = parse({"diagnosis": "unclear", "confidence": "low", "questions": ["which branch?"]})
    assert plan.is_question_only


@pytest.mark.parametrize("data,expected", [
    ({"confidence": "high", "steps": [{"command": "git status", "purpose": "p", "risk": "safe"}]}, "diagnosis"),
    ({"diagnosis": "d", "steps": [{"command": "git status", "purpose": "p", "risk": "safe"}]}, "confidence"),
    ({"diagnosis": "d", "confidence": "very sure",
      "steps": [{"command": "git status", "purpose": "p", "risk": "safe"}]}, "confidence"),
    ({"diagnosis": "d", "confidence": "high"}, "steps, or questions"),
    ({"diagnosis": "d", "confidence": "high", "steps": [{"command": "rm -rf .", "purpose": "p", "risk": "safe"}]}, "start with 'git'"),
    ({"diagnosis": "d", "confidence": "high", "steps": [{"command": "git reset --hard <sha>", "purpose": "p", "risk": "safe"}]}, "placeholder"),
    ({"diagnosis": "d", "confidence": "high", "steps": [{"command": "git status", "purpose": "p"}]}, "risk"),
    ({"diagnosis": "d", "confidence": "high", "steps": [{"command": "git status", "risk": "safe"}]}, "purpose"),
    ({"diagnosis": "d", "confidence": "high", "steps": [{"command": "", "purpose": "p", "risk": "safe"}]}, "no command"),
])
def test_malformed_plans_are_rejected_with_a_usable_message(data, expected):
    with pytest.raises(PlanError) as e:
        parse(data)
    assert expected in str(e.value)


def test_placeholders_are_rejected_because_b2_used_them():
    """B1 and B2 both emitted <sha>. A plan that cannot be executed as
    written is not a plan."""
    with pytest.raises(PlanError):
        parse({"diagnosis": "d", "confidence": "high",
               "steps": [{"command": "git checkout {branch}", "purpose": "p", "risk": "safe"}]})


def test_unrecoverable_and_secret_fields_survive_parsing():
    plan = parse({**GOOD, "unrecoverable": ["unstaged edits to app.py"], "rotate_secrets_first": True})
    assert plan.unrecoverable == ["unstaged edits to app.py"] and plan.rotate_secrets_first
