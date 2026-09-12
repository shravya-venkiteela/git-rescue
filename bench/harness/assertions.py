from __future__ import annotations
import inspect
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from bench.gitenv import isolated_env

REGISTRY: dict[str, Callable[..., bool]] = {}

def assertion(fn: Callable[..., bool]) -> Callable[..., bool]:
    """Register fn under its own name, so YAML `type:` values map to it."""
    REGISTRY[fn.__name__] = fn
    return fn


def _run(repo: Path, *args: str, stdin: bytes | None = None) -> subprocess.CompletedProcess:
    env = isolated_env(Path(tempfile.gettempdir()) / "git-rescue-assert-home")
    env["GIT_OPTIONAL_LOCKS"] = "0"
    return subprocess.run(["git", *args], cwd=repo, env=env, input=stdin, capture_output=True)


def _patch_ids(repo: Path, *log_args: str) -> set[str]:
    """Patch ids identify a change by its diff, not its SHA. A cherry-picked
    or rebased copy of a commit gets a new SHA but keeps its patch id."""
    log = _run(repo, "log", "-p", "--no-color", "--no-ext-diff", *log_args)
    out = _run(repo, "patch-id", "--stable", stdin=log.stdout)
    return {line.split()[0] for line in out.stdout.decode().splitlines()}


def _normalize(data: bytes) -> bytes:
    #A user's git may check files out with CRLF. The question is whether
    #the work came back, not which line endings it came back with.
    return data.replace(b"\r\n", b"\n")


@assertion
def head_attached(repo: Path) -> bool:
    return _run(repo, "symbolic-ref", "--quiet", "HEAD").returncode == 0


@assertion
def no_operation_in_progress(repo: Path) -> bool:
    git_dir = Path(_run(repo, "rev-parse", "--absolute-git-dir").stdout.decode().strip())
    markers = ["rebase-merge", "rebase-apply", "MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD", "BISECT_LOG"]
    return not any((git_dir / m).exists() for m in markers)


@assertion
def commit_reachable_from_branch(repo: Path, sha: str, branch: str) -> bool:
    """sha is in branch's history. The branch may have moved on past it."""
    return _run(repo, "merge-base", "--is-ancestor", sha, f"refs/heads/{branch}").returncode == 0


@assertion
def branch_at_commit(repo: Path, sha: str, branch: str) -> bool:
    """branch points at exactly sha: use when the user wants it unchanged."""
    result = _run(repo, "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}")
    return result.returncode == 0 and result.stdout.decode().strip() == sha


def _content_on(repo: Path, sha: str, *where: str) -> bool:
    """True if the change made in sha appears, by patch id, in the history
    named by `where` (e.g. "--branches" or "refs/heads/feature")."""
    target = _patch_ids(repo, "-1", sha)
    return bool(target) and target <= _patch_ids(repo, *where)


@assertion
def content_reachable_from_local_branch(repo: Path, sha: str) -> bool:
    """The change made in sha is on some local branch, either as sha itself
    or as a copy with a new SHA (cherry-pick, rebase)."""
    if _run(repo, "for-each-ref", "--contains", sha, "--format=x", "refs/heads").stdout.strip():
        return True
    return _content_on(repo, sha, "--branches")


@assertion
def content_reachable_from_branch(repo: Path, sha: str, branch: str) -> bool:
    """Like content_reachable_from_local_branch, but on one specific branch."""
    ref = f"refs/heads/{branch}"
    if _run(repo, "rev-parse", "--verify", "--quiet", ref).returncode != 0:
        return False
    if _run(repo, "merge-base", "--is-ancestor", sha, ref).returncode == 0:
        return True
    return _content_on(repo, sha, ref)


@assertion
def worktree_file_matches_commit(repo: Path, sha: str, path: str) -> bool:
    """The file in the working folder has the content it has in sha."""
    file = repo / path
    expected = _run(repo, "show", f"{sha}:{path}")
    if not file.exists() or expected.returncode != 0:
        return False
    return _normalize(file.read_bytes()) == _normalize(expected.stdout)


@assertion
def worktree_file_has_blob(repo: Path, sha: str, path: str) -> bool:
    """The file in the working folder has exactly the content of blob sha.
    For work that only ever existed as a blob, e.g. staged but never committed."""
    file = repo / path
    expected = _run(repo, "cat-file", "blob", sha)
    if not file.exists() or expected.returncode != 0:
        return False
    return _normalize(file.read_bytes()) == _normalize(expected.stdout)


@assertion
def branch_file_matches_commit(repo: Path, sha: str, branch: str, path: str) -> bool:
    """The file as committed on branch's tip equals the file in sha. Unlike
    the worktree checks, uncommitted edits don't count."""
    actual = _run(repo, "show", f"refs/heads/{branch}:{path}")
    expected = _run(repo, "show", f"{sha}:{path}")
    if actual.returncode != 0 or expected.returncode != 0:
        return False
    return _normalize(actual.stdout) == _normalize(expected.stdout)


@assertion
def untracked_file_preserved(repo: Path, sha: str, path: str) -> bool:
    """A file that exists only in the working tree still has its content.
    Nothing in git holds a copy of an untracked file, so if a rescue deletes
    it, it is gone for good. `sha` is its blob id, recorded at build time."""
    from bench.harness.checker import blob_id

    file = repo / path
    return file.exists() and blob_id(_normalize(file.read_bytes())) == sha


@dataclass(frozen=True)
class Result:
    spec: dict
    passed: bool


def _params(spec: dict, labels: dict[str, str]) -> tuple[str, dict]:
    params = dict(spec)
    kind = params.pop("type")
    if "label" in params:
        params["sha"] = labels[params.pop("label")]
    return kind, params


def evaluate(repo: Path, assertions: list[dict], labels: dict[str, str]) -> list[Result]:
    results = []
    for spec in assertions:
        kind, params = _params(spec, labels)
        if kind not in REGISTRY:
            raise ValueError(f"unknown assertion type '{kind}'")
        results.append(Result(spec, bool(REGISTRY[kind](repo, **params))))
    return results


def validate(assertions: list[dict]) -> list[str]:
    """Problems in a scenario's assertion list: unknown types, or keys
    that don't match the function's parameters. Empty list = valid."""
    problems = []
    for spec in assertions:
        kind, params = _params(spec, {spec.get("label", ""): "0" * 40})
        if kind not in REGISTRY:
            problems.append(f"unknown type '{kind}' (known: {sorted(REGISTRY)})")
            continue
        try:
            inspect.signature(REGISTRY[kind]).bind(Path("."), **params)
        except TypeError as e:
            problems.append(f"{kind}: {e}")
    return problems