from __future__ import annotations

import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    params: tuple[str, ...]      #names the model may supply
    build: object                #(params) -> argv list


def _run(repo: Path, argv: list[str]) -> str:
    from bench.gitenv import isolated_env  #scenario-safe env; same isolation everywhere

    env = isolated_env(Path(tempfile.gettempdir()) / "git-rescue-tools-home")
    env["GIT_OPTIONAL_LOCKS"] = "0"
    p = subprocess.run(argv, cwd=repo, env=env, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=30)
    return (p.stdout + p.stderr).strip()


def _valid_ref(repo: Path, ref: str) -> bool:
    """Reject anything git cannot resolve, before it reaches a command."""
    if not ref or ref.startswith("-") or any(c in ref for c in " \t\n;|&$`"):
        return False
    argv = ["git", "rev-parse", "--verify", "--quiet", ref]
    from bench.gitenv import isolated_env

    env = isolated_env(Path(tempfile.gettempdir()) / "git-rescue-tools-home")
    env["GIT_OPTIONAL_LOCKS"] = "0"
    return subprocess.run(argv, cwd=repo, env=env, capture_output=True, timeout=30).returncode == 0


def _clamp(value, default: int, lo: int, hi: int) -> int:
    try:
        return max(lo, min(hi, int(value)))
    except (TypeError, ValueError):
        return default


TOOLS: dict[str, Tool] = {}


def tool(name: str, description: str, params: tuple[str, ...] = ()):
    def register(fn):
        TOOLS[name] = Tool(name, description, params, fn)
        return fn
    return register


@tool("status", "Working tree and branch state (porcelain v2).")
def _status(repo, **_):
    return ["git", "status", "--porcelain=v2", "--branch"]


@tool("log", "Recent commits on a ref, as a graph.", ("ref", "count"))
def _log(repo, ref="HEAD", count=15, **_):
    return ["git", "log", "--oneline", "--graph", "--decorate", f"-n{_clamp(count, 15, 1, 50)}", ref]


@tool("reflog", "Where HEAD (or a ref) has pointed recently. Finds lost commits.", ("ref", "count"))
def _reflog(repo, ref="HEAD", count=25, **_):
    return ["git", "reflog", "show", "--date=iso", f"-n{_clamp(count, 25, 1, 50)}", ref]


@tool("branches", "All local and remote branches, with upstream tracking.")
def _branches(repo, **_):
    return ["git", "for-each-ref",
            "--format=%(refname:short) %(objectname:short) %(upstream:short) %(upstream:track)",
            "refs/heads", "refs/remotes"]


@tool("stashes", "The stash list. Empty output means no stashes remain.")
def _stashes(repo, **_):
    return ["git", "stash", "list", "--format=%gd %H %s"]


@tool("divergence", "How far two refs have diverged: 'behind ahead'.", ("a", "b"))
def _divergence(repo, a="HEAD", b="@{upstream}", **_):
    return ["git", "rev-list", "--left-right", "--count", f"{a}...{b}"]


@tool("show", "One commit: its metadata and which files it changed.", ("ref",))
def _show(repo, ref="HEAD", **_):
    return ["git", "show", "--stat", "--format=fuller", "--no-patch", ref]


@tool("dangling", "Commits and blobs no ref points to. Finds dropped stashes "
                  "and work wiped by reset --hard after git add.")
def _dangling(repo, **_):
    return ["git", "fsck", "--unreachable", "--no-reflogs"]


def operation_state(repo: Path) -> str:
    """Whether a rebase, merge, cherry-pick, revert or bisect is in progress.

    Read from .git rather than by running a command, because this is the one
    piece of state that decides whether the problem is "an unfinished
    operation" or something else, and B2 repeatedly misread it.
    """
    git_dir_out = _run(repo, ["git", "rev-parse", "--absolute-git-dir"])
    git_dir = Path(git_dir_out.splitlines()[0]) if git_dir_out else repo / ".git"
    markers = {
        "rebase-merge": "interactive or merge rebase in progress",
        "rebase-apply": "am or rebase in progress",
        "MERGE_HEAD": "merge in progress",
        "CHERRY_PICK_HEAD": "cherry-pick in progress",
        "REVERT_HEAD": "revert in progress",
        "BISECT_LOG": "bisect in progress",
    }
    found = [text for name, text in markers.items() if (git_dir / name).exists()]
    lines = found or ["no operation in progress"]

    rebase_dir = git_dir / "rebase-merge"
    if rebase_dir.is_dir():
        for name, label in (("head-name", "rebasing branch"), ("onto", "onto")):
            f = rebase_dir / name
            if f.exists():
                lines.append(f"{label}: {f.read_text(encoding='utf-8', errors='replace').strip()}")
    detached = _run(repo, ["git", "symbolic-ref", "--quiet", "HEAD"]) == ""
    lines.append("HEAD is detached" if detached else "HEAD is on a branch")
    return "\n".join(lines)


TOOLS["operation_state"] = Tool(
    "operation_state",
    "Whether a rebase/merge/cherry-pick/revert/bisect is unfinished, and whether HEAD is detached.",
    (),
    None,
)


def call(repo: Path, name: str, params: dict) -> str:
    """Run one tool. Returns output, or a message the agent can learn from."""
    if name not in TOOLS:
        return f"ERROR: no such tool '{name}'. Available: {', '.join(sorted(TOOLS))}"
    if name == "operation_state":
        return operation_state(repo)

    clean = {k: v for k, v in (params or {}).items() if k in TOOLS[name].params}
    for key in ("ref", "a", "b"):
        if key in clean and not _valid_ref(repo, str(clean[key])):
            return f"ERROR: '{clean[key]}' is not a ref this repository knows. Use a value you have seen in output."
    argv = TOOLS[name].build(repo, **clean)
    out = _run(repo, argv)
    return out or "(no output)"


def describe() -> str:
    """The tool list, for the system prompt."""
    lines = []
    for name in sorted(TOOLS):
        t = TOOLS[name]
        args = f"  params: {', '.join(t.params)}" if t.params else ""
        lines.append(f"- {name}: {t.description}{args}")
    return "\n".join(lines)
