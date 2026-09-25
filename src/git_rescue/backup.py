from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import time
from dataclasses import dataclass
from pathlib import Path

BACKUP_ROOT = Path.home() / ".git-rescue" / "backups"
SIZE_WARNING_BYTES = 2 * 1024 * 1024 * 1024  # 2 GB


def _on_error(func, path, exc_info):
    """Windows marks git object files read-only, so rmtree fails on them."""
    os.chmod(path, stat.S_IWRITE)
    func(path)


def remove_tree(path: Path) -> None:
    if not path.exists():
        return
    try:
        shutil.rmtree(path, onexc=_on_error)        # Python 3.12+
    except TypeError:
        shutil.rmtree(path, onerror=lambda f, p, e: _on_error(f, p, e))


def empty_directory(path: Path) -> None:
    """Delete everything INSIDE path, but never path itself.

    Removing the folder and copying a fresh one in its place fails the moment
    anything holds it open, which on Windows includes the shell the person is
    standing in: rmtree deletes the contents, then cannot remove the folder,
    and the repository is left destroyed. Emptying it in place cannot do that.
    """
    for child in path.iterdir():
        if child.is_dir() and not child.is_symlink():
            remove_tree(child)
        else:
            try:
                child.unlink()
            except PermissionError:
                os.chmod(child, stat.S_IWRITE)
                child.unlink()


def directory_size(path: Path) -> int:
    total = 0
    for root, _, files in os.walk(path):
        for name in files:
            try:
                total += (Path(root) / name).stat().st_size
            except OSError:
                pass
    return total


@dataclass(frozen=True)
class Backup:
    path: Path
    manifest: Path

    @property
    def repo_copy(self) -> Path:
        return self.path / "repo"


RESCUE = "rescue"      #taken before a rescue runs: what `undo` goes back to
SAFETY = "safety"      #taken by undo itself, so an undo can be undone


def create(repo: Path, note: str = "", root: Path | None = None, kind: str = RESCUE) -> Backup:
    """Copy the whole repository somewhere safe and record what was there.

    kind marks why: `undo` must go back to the state before the RESCUE, not to
    the copy undo took a moment earlier. Restoring the newest folder made a
    second undo restore the state the first undo had just reverted."""
    root = root or BACKUP_ROOT
    key = hashlib.sha256(str(repo.resolve()).encode()).hexdigest()[:12]
    stamp = time.strftime("%Y%m%dT%H%M%S")
    #Two rescues in the same second must not share a folder: without a
    #suffix the second copytree merges into the first and both backups
    #become a mixture of two states.
    parent = root / key
    parent.mkdir(parents=True, exist_ok=True)
    dest, n = parent / stamp, 1
    while dest.exists():
        dest, n = parent / f"{stamp}-{n}", n + 1
    dest.mkdir()

    shutil.copytree(repo, dest / "repo", symlinks=True)
    manifest = dest / "manifest.json"
    manifest.write_text(json.dumps({
        "source": str(repo.resolve()),
        "created": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "note": note,
        "kind": kind,
        "bytes": directory_size(dest / "repo"),
    }, indent=2), encoding="utf-8")
    return Backup(dest, manifest)


def restore(backup: Backup, repo: Path) -> None:
    """Put the repository back. The CURRENT state is backed up first, so
    undo is itself undoable: a user who undoes by mistake is not stuck.

    The safety copy goes beside the backup being restored, not to the
    default location: otherwise undoing a backup made under a different
    root would scatter copies in two places.
    """
    create(repo, note=f"state before restoring {backup.path.name}",
           root=backup.path.parent.parent, kind=SAFETY)
    empty_directory(repo)
    shutil.copytree(backup.repo_copy, repo, symlinks=True, dirs_exist_ok=True)


def _kind_of(manifest: Path) -> str:
    try:
        return json.loads(manifest.read_text(encoding="utf-8")).get("kind", RESCUE)
    except (OSError, json.JSONDecodeError):
        return RESCUE      #backups made before kinds existed were all rescues


def latest_for(repo: Path, root: Path | None = None, kind: str | None = RESCUE) -> Backup | None:
    """The newest backup of this repository, by default the newest one taken
    before a rescue. kind=None means "the newest of any kind"."""
    root = root or BACKUP_ROOT
    key = hashlib.sha256(str(repo.resolve()).encode()).hexdigest()[:12]
    folder = root / key
    if not folder.is_dir():
        return None
    saved = [Backup(p, p / "manifest.json") for p in sorted(folder.iterdir()) if p.is_dir()]
    if kind is not None:
        saved = [b for b in saved if _kind_of(b.manifest) == kind]
    return saved[-1] if saved else None