from __future__ import annotations
import hashlib
import os
import subprocess
import tempfile
from dataclasses import dataclass, field
from enum import IntEnum
from pathlib import Path

from bench.gitenv import isolated_env


class Status(IntEnum):
    INTACT = 0
    BACKUP_ONLY = 1
    HIDDEN = 2
    GONE = 3


@dataclass(frozen=True)
class Snapshot:
    all_objects: frozenset[str]  #everything in .git/objects
    reachable: frozenset[str]    #objects reachable from any ref or reflog
    commits: frozenset[str]      #every commit object, reachable or not
    content: frozenset[str]      #blob ids of working-tree files + index entries


@dataclass(frozen=True)
class Loss:
    item: str
    kind: str  #"commit" or "content"
    before: Status
    after: Status


@dataclass
class LossReport:
    losses: list[Loss] = field(default_factory=list)

    @property
    def absolute(self) -> list[Loss]:
        return [l for l in self.losses if l.after == Status.GONE]

    @property
    def practical(self) -> list[Loss]:
        """Losses a junior experiences as 'my work is gone'."""
        return [l for l in self.losses if l.after in (Status.HIDDEN, Status.GONE)]

    @property
    def backup_only(self) -> list[Loss]:
        return [l for l in self.losses if l.after == Status.BACKUP_ONLY]


def _git(path: Path, *args: str) -> str:
    env = isolated_env(Path(tempfile.gettempdir()) / "git-rescue-checker-home")
    env["GIT_OPTIONAL_LOCKS"] = "0"  # read-only: don't let `status` rewrite the index
    result = subprocess.run(
        ["git", *args], cwd=path, env=env, capture_output=True, text=True, encoding="utf-8"
    )
    if result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr}")
    return result.stdout


def blob_id(data: bytes) -> str:
    """The SHA git would give this file content, computed without git."""
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def _worktree_blob_ids(path: Path) -> set[str]:
    """Blob ids of every file outside .git, including untracked and ignored."""
    ids = set()
    for root, dirs, files in os.walk(path):
        dirs[:] = [d for d in dirs if d != ".git"]
        for name in files:
            ids.add(blob_id((Path(root) / name).read_bytes()))
    return ids


def take_snapshot(path: Path) -> Snapshot:
    objects = _git(path, "cat-file", "--batch-all-objects", "--batch-check=%(objectname) %(objecttype)")
    all_objects, commits = set(), set()
    for line in objects.splitlines():
        sha, kind = line.split()
        all_objects.add(sha)
        if kind == "commit":
            commits.add(sha)

    reachable = {line.split()[0] for line in _git(path, "rev-list", "--all", "--reflog", "--objects").splitlines()}
    index = {line.split()[1] for line in _git(path, "ls-files", "--stage").splitlines()}

    return Snapshot(
        all_objects=frozenset(all_objects),
        reachable=frozenset(reachable),
        commits=frozenset(commits),
        content=frozenset(_worktree_blob_ids(path) | index),
    )


def status(item: str, snap: Snapshot, backup: Snapshot | None = None) -> Status:
    if item in snap.reachable or item in snap.content:
        return Status.INTACT
    if backup is not None and (item in backup.all_objects or item in backup.content):
        return Status.BACKUP_ONLY
    if item in snap.all_objects:
        return Status.HIDDEN
    return Status.GONE


def check(
    before: Snapshot,
    after: Snapshot,
    backup: Snapshot | None = None,
    allowed_to_lose: frozenset[str] = frozenset(),
) -> LossReport:
    """allowed_to_lose: items the scenario's intent says may be discarded,
    e.g. commits the user explicitly wants thrown away."""
    report = LossReport()
    items = [(c, "commit") for c in before.commits] + [(b, "content") for b in before.content]
    for item, kind in sorted(items):
        if item in allowed_to_lose:
            continue
        was, now = status(item, before), status(item, after, backup)
        if now > was:
            report.losses.append(Loss(item, kind, was, now))
    return report