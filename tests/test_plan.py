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


@pytest.mark.parametrize("command", [
    "git reflog expire --expire=now --all && git gc --prune=now",
    "git log | head",
    "git status; git log",
    "git show HEAD > out.txt",
])
def test_shell_operators_are_rejected_with_a_reason(command):
    """Steps run without a shell. A chained clean-up once failed only by
    accident because git received '&&' as an argument."""
    with pytest.raises(PlanError, match="own step"):
        parse({"diagnosis": "d", "confidence": "high",
               "steps": [{"command": command, "purpose": "p", "risk": "safe"}]})


def test_step_text_keeps_quotes_so_it_splits_back_the_same():
    from src.git_rescue.plan import split_command
    plan = parse({"diagnosis": "d", "confidence": "high", "steps": [
        {"command": 'git stash store -m "recovered stash" abc123', "purpose": "p", "risk": "reversible"}]})
    step = plan.steps[0]
    assert step.argv == ["git", "stash", "store", "-m", "recovered stash", "abc123"]
    assert split_command(step.text) == step.argv
