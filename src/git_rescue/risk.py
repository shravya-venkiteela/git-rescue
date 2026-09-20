from __future__ import annotations

SAFE = "safe"
REVERSIBLE = "reversible"
DESTRUCTIVE = "destructive"
BLOCKED = "blocked"

READ_ONLY = {"status", "log", "reflog", "show", "diff", "describe", "blame", "shortlog",
             "rev-parse", "rev-list", "cat-file", "ls-files", "ls-tree", "for-each-ref",
             "merge-base", "name-rev", "count-objects", "verify-pack", "whatchanged", "grep"}

#Changes state, but nothing it touches becomes unreachable.
REVERSIBLE_SUBCOMMANDS = {"add", "commit", "branch", "tag", "switch", "checkout", "restore",
                          "merge", "rebase", "cherry-pick", "revert", "stash", "apply",
                          "mv", "update-ref", "symbolic-ref", "notes", "fetch", "remote",
                          #reset without --hard/--merge/--keep only moves refs; the
                          # old position stays in the reflog
                          "reset"}

#Never run, whatever the plan says: these execute arbitrary programs, rewrite
#shared history, or reach outside this repository.
BLOCKED_SUBCOMMANDS = {"config", "submodule", "daemon", "credential", "difftool", "mergetool",
                       "instaweb", "filter-branch", "filter-repo", "push", "send-email",
                       "request-pull", "svn", "p4", "archive", "bundle", "clone", "init"}

#Global options that can point git elsewhere or run programs.
BLOCKED_GLOBAL = {"-c", "-C", "--git-dir", "--work-tree", "--exec-path", "--namespace", "--config-env"}
GLOBAL_WITH_VALUE = {"-c", "-C", "--git-dir", "--work-tree", "--namespace", "--config-env"}

#A rescue never needs these, and each one deletes the only copy of lost work:
#the reflog and unreachable objects are exactly what recovery reads. gpt-oss
#appended "git reflog expire --expire=now --all && git gc --prune=now" as an
#optional clean-up to a correct plan. (subcommand, flags); None = always.
BLOCKED_RULES: dict[str, set[str] | None] = {
    "gc": None,
    "prune": None,
    "reflog": {"expire", "delete"},
}

#(subcommand, flags that make it destructive). None means always destructive.
DESTRUCTIVE_RULES: dict[str, set[str] | None] = {
    "reset": {"--hard", "--merge", "--keep"},
    "clean": None,
    "gc": None,
    "prune": None,
    "repack": None,
    "checkout": {"-f", "--force", "--ours", "--theirs"},
    "restore": {"--worktree", "-W", "--staged", "-S", "--source"},
    "switch": {"-f", "--force", "--discard-changes"},
    "branch": {"-D", "-M", "--delete", "--force", "-f"},
    "tag": {"-d", "--delete", "-f", "--force"},
    "stash": {"drop", "clear", "pop"},          # pop removes the stash entry
    "update-ref": {"-d", "--delete", "--stdin"},
    "reflog": {"expire", "delete"},
    "notes": {"prune", "remove"},
    "worktree": {"remove", "prune"},
    "am": {"--abort"},
    "rebase": {"--abort"},                      # discards in-progress work
    "merge": {"--abort"},
    "cherry-pick": {"--abort"},
    "revert": {"--abort"},
}


def classify(argv: list[str]) -> tuple[str, str]:
    """Return (level, why). Never raises: unknown input is DESTRUCTIVE."""
    if not argv or argv[0] != "git":
        return BLOCKED, "only git commands may run"

    args = argv[1:]
    i = 0
    while i < len(args) and args[i].startswith("-"):
        name = args[i].split("=", 1)[0]
        if name in BLOCKED_GLOBAL:
            return BLOCKED, f"the global option {name} can escape this repository or run programs"
        i += 2 if (name in GLOBAL_WITH_VALUE and "=" not in args[i]) else 1
    if i >= len(args):
        return SAFE, "no subcommand"

    sub, rest = args[i], args[i + 1:]
    if sub == "stash" and rest[:1] in (["list"], ["show"]):
        return SAFE, "reads the stash without changing it"
    if sub in BLOCKED_SUBCOMMANDS:
        return BLOCKED, f"git {sub} is not allowed: it affects things outside this repository"
    if sub == "rebase" and any(a in ("-x", "--exec") or a.startswith("--exec=") for a in rest):
        return BLOCKED, "rebase --exec runs arbitrary commands"
    if sub == "bisect":
        return (BLOCKED, "bisect run executes arbitrary commands") if rest[:1] == ["run"] \
            else (REVERSIBLE, "bisect moves HEAD")

    block = BLOCKED_RULES.get(sub, "missing")
    if block is None or (block != "missing" and set(rest[:1]) & block):
        return BLOCKED, (f"git {' '.join([sub] + rest[:1]) if block else sub} deletes the reflog "
                         "or unreachable objects, which is what recovery depends on")

    rule = DESTRUCTIVE_RULES.get(sub, "missing")
    if rule is None:
        return DESTRUCTIVE, f"git {sub} can permanently remove objects or files"
    if rule != "missing":
        hit = sorted(set(rest) & rule)
        if hit:
            return DESTRUCTIVE, f"git {sub} {' '.join(hit)} can make work unreachable"

    #`git checkout <sha> -- path` overwrites a file in place, with no copy kept.
    if sub in ("checkout", "restore") and "--" in rest:
        return DESTRUCTIVE, f"git {sub} -- <path> overwrites files in the working tree"

    if sub in READ_ONLY:
        return SAFE, "reads only"
    if sub in REVERSIBLE_SUBCOMMANDS:
        return REVERSIBLE, f"git {sub} changes state but leaves work reachable"
    return DESTRUCTIVE, f"git {sub} is not in the risk table; treating it as destructive"


def worst(levels) -> str:
    order = [SAFE, REVERSIBLE, DESTRUCTIVE, BLOCKED]
    return max(levels, key=order.index, default=SAFE)


def review(plan) -> dict:
    """Classify every step and note where the model's label disagreed."""
    rows, disagreements = [], []
    for step in plan.steps:
        level, why = classify(step.argv)
        rows.append({"command": step.text, "claimed": step.claimed_risk, "actual": level, "why": why})
        if step.claimed_risk != level and level != BLOCKED:
            disagreements.append(f"{step.text}: model said {step.claimed_risk}, table says {level}")
    return {
        "steps": rows,
        "overall": worst([r["actual"] for r in rows]),
        "blocked": [r for r in rows if r["actual"] == BLOCKED],
        "disagreements": disagreements,
    }