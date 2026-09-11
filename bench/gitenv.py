from __future__ import annotations
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

BASE_EPOCH = 1_700_000_000
class GitError(RuntimeError):
    def __init__(self, args: tuple[str, ...], result: subprocess.CompletedProcess):
        self.result = result
        super().__init__(
            f"git {' '.join(args)} failed with exit code {result.returncode}\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
def isolated_env(home: Path) -> dict[str, str]:
        """Env for git with every source of outside config removed."""
        env = {k:v for k,v in os.environ.items() if not k.startswith("GIT_")}
        env.update(
            {
                "HOME": str(home),
                "USERPROFILE": str(home),
                "XDG_CONFIG_HOME": str(home / ".config"),
                "GIT_CONFIG_NOSYSTEM": "1",
                "GIT_CONFIG_GLOBAL": os.devnull,
                "GIT_AUTHOR_NAME": "Scenario Author",
                "GIT_AUTHOR_EMAIL": "author@example.com",
                "GIT_COMMITTER_NAME": "Scenario Author",
                "GIT_COMMITTER_EMAIL": "author@example.com",
                "GIT_TERMINAL_PROMPT": "0",
                "LC_ALL": "C",

            }
        )
        return env

@dataclass
class GitRepo:
    path: Path
    home: Path
    _tick: int = 0

    @classmethod
    def init(cls, path: Path, home: Path) -> GitRepo:
        """Initialize a new git repo at path."""
        path.mkdir(parents=True, exist_ok=True)
        home.mkdir(parents=True, exist_ok=True)
        repo = cls(path=path, home=home)
        repo.git("init", "--quiet")
        repo.git("symbolic-ref", "HEAD", "refs/heads/main")
        return repo

    def run(self, *args:str) -> subprocess.CompletedProcess:
        """Run git and return the result without raising. Use this when a command is expected to fail. e.g a rebase that stops on a conflict.""" 
        self._tick += 1
        stamp = f'{BASE_EPOCH + self._tick*60} +0000'
        env = isolated_env(self.home)
        env["GIT_AUTHOR_DATE"] = stamp
        env["GIT_COMMITTER_DATE"] = stamp
        return subprocess.run(
            ["git", *args],
            cwd=self.path,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )

    def  git(self, *args:str) -> str:
        """Run git, raise GitError on failure, return stripped stdout."""
        result = self.run(*args)
        if result.returncode != 0:
            raise GitError(args, result)
        return result.stdout.strip()

    def write(self, relpath: str, content: str) -> None:
        """Write a file in the working tree. Uses bytes so Windows never converts \\n to \\r\\n behind your back."""
        target = self.path / relpath
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content.encode("utf-8"))

    def commit_file(self, relpath: str, content: str, message: str) -> str:
        """Write a file, stage it, commit it and return the new SHA."""
        self.write(relpath, content)
        self.git("add","--", relpath)
        self.git("commit","--quiet", "-m", message)
        return self.rev("HEAD")

    def rev(self, ref:str) -> str:
        return self.git("rev-parse","--verify", ref)

    def head_is_attached(self) -> bool:
        """Return True if HEAD is attached to a branch, False if detached."""
        return self.run("symbolic-ref", "--quiet", "HEAD").returncode == 0
    def refs_containing(self, sha:str) -> list[str]:
        """Every ref branches, tags, remotes, stash whose history includes sha."""
        out = self.git("for-each-ref","--contains", sha,  "--format=%(refname)")
        return out.splitlines()

    def in_reflog(self, sha: str) -> bool:
        """True if sha is reachable from any reflog entry, i.e. a user could
        still find it with `git reflog`."""
        return sha in self.git("rev-list", "--reflog").split()
 
    def is_clean(self) -> bool:
        return self.git("status", "--porcelain", "--untracked-files=all") == ""