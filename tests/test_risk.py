"""The risk table is the safety layer. It must never depend on the model's
own judgement, and an unfamiliar command must be treated as dangerous."""
import pytest

from src.git_rescue.plan import parse
from src.git_rescue.risk import BLOCKED, DESTRUCTIVE, REVERSIBLE, SAFE, classify, review


@pytest.mark.parametrize("command,expected", [
    ("git status", SAFE),
    ("git reflog show -n 20", SAFE),
    ("git log --oneline", SAFE),
    ("git stash list", SAFE),
    ("git branch feature abc123", REVERSIBLE),
    ("git reset --soft HEAD~1", REVERSIBLE),      # old position stays in the reflog
    ("git reset HEAD~1", REVERSIBLE),
    ("git checkout main", REVERSIBLE),
    ("git cherry-pick abc123", REVERSIBLE),
    ("git stash", REVERSIBLE),
    ("git reset --hard HEAD~1", DESTRUCTIVE),
    ("git clean -fd", DESTRUCTIVE),
    ("git branch -D feature", DESTRUCTIVE),
    ("git stash drop", DESTRUCTIVE),
    ("git stash pop", DESTRUCTIVE),               # removes the stash entry
    # erasing the reflog or pruning objects deletes what recovery reads
    ("git gc --prune=now", BLOCKED),
    ("git gc", BLOCKED),
    ("git prune", BLOCKED),
    ("git reflog expire --expire=now --all", BLOCKED),
    ("git reflog delete HEAD@{1}", BLOCKED),
    ("git reflog show HEAD", SAFE),
    ("git reflog", SAFE),
    ("git checkout abc123 -- app.py", DESTRUCTIVE),
    ("git restore --staged app.py", DESTRUCTIVE),
    ("git rebase --abort", DESTRUCTIVE),          # discards in-progress work
    ("git push --force origin main", BLOCKED),
    ("git config alias.x !sh", BLOCKED),
    ("git -c core.sshCommand=evil fetch", BLOCKED),
    ("git -C /somewhere status", BLOCKED),
    ("git rebase -x 'rm -rf .' main", BLOCKED),
    ("git bisect run make", BLOCKED),
    ("git filter-branch --all", BLOCKED),
    ("rm -rf .", BLOCKED),
])
def test_commands_are_classified_correctly(command, expected):
    assert classify(command.split())[0] == expected, command


@pytest.mark.parametrize("command", ["git frobnicate", "git experimental-thing --yes", "git reincarnate x"])
def test_unknown_commands_default_to_destructive(command):
    """A command the table has never seen has unknown consequences."""
    level, why = classify(command.split())
    assert level == DESTRUCTIVE and "not in the risk table" in why


def test_the_models_own_label_is_recorded_but_not_used():
    """A model calling reset --hard 'safe' must not make it safe."""
    plan = parse({"diagnosis": "d", "confidence": "high", "steps": [
        {"command": "git reset --hard HEAD~3", "purpose": "p", "risk": "safe"}]})
    result = review(plan)
    assert result["overall"] == DESTRUCTIVE
    assert result["disagreements"] and "model said safe" in result["disagreements"][0]


def test_review_reports_the_worst_step_not_the_average():
    plan = parse({"diagnosis": "d", "confidence": "high", "steps": [
        {"command": "git status", "purpose": "look", "risk": "safe"},
        {"command": "git clean -fd", "purpose": "tidy", "risk": "safe"}]})
    assert review(plan)["overall"] == DESTRUCTIVE


def test_a_blocked_step_is_listed_separately():
    plan = parse({"diagnosis": "d", "confidence": "high", "steps": [
        {"command": "git push --force", "purpose": "publish", "risk": "safe"}]})
    assert len(review(plan)["blocked"]) == 1
