from __future__ import annotations
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from bench.gitenv import isolated_env

COMMAND_TIMEOUT_SECONDS = 30

#Global git options that point git at another repo or run other programs.
BLOCKED_GLOBAL_OPTIONS = {"-C", "-c", "--git-dir", "--work-tree", "--exec-path", "--namespace", "--config-env"}
GLOBAL_OPTIONS_WITH_VALUE = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--config-env"}
#Subcommands that change config (aliases, hooks, sshCommand), launch external
#programs, or reach outside the repo.
BLOCKED_SUBCOMMANDS = {"config", "submodule", "daemon", "credential", "difftool", "mergetool", "instaweb", "web--browse"}


@dataclass
class CommandResult:
    argv: list[str]
    returncode: int
    stdout: str
    stderr: str
    seconds: float = 0.0
    blocked: str | None = None  #reason, if the Session refused to run it


def blocked_reason(argv: list[str]) -> str | None:
    """Why the Session won't run argv, or None if it will."""
    if not argv or argv[0] != "git":
        return "only git commands can run in this harness"
    args = argv[1:]
    i = 0
    while i < len(args) and args[i].startswith("-"):
        name = args[i].split("=", 1)[0]
        if name in BLOCKED_GLOBAL_OPTIONS:
            return f"global option {name} is not allowed (it can escape the repo or run programs)"
        i += 2 if (name in GLOBAL_OPTIONS_WITH_VALUE and "=" not in args[i]) else 1
    if i == len(args):
        return None  #e.g. `git --version`
    sub, rest = args[i], args[i + 1:]
    if sub in BLOCKED_SUBCOMMANDS:
        return f"git {sub} is not allowed in this harness"
    if sub == "rebase" and any(a in ("-x", "--exec") or a.startswith("--exec=") for a in rest):
        return "rebase --exec runs arbitrary commands"
    if sub == "bisect" and rest[:1] == ["run"]:
        return "bisect run executes arbitrary commands"
    return None


@dataclass
class Session:
    repo_path: Path
    home: Path
    user_message: str
    simulated_user: Any  #anything with .answer(question) -> str
    max_commands: int = 30
    oracle: Any = None  #scenario + labels; ONLY for harness-validation systems
    backup_dir: Path | None = None  # a system that makes a backup records it here
    events: list[dict] = field(default_factory=list)
    final_message: str = ""
    _commands_run: int = 0

    def _env(self) -> dict[str, str]:
        env = isolated_env(self.home)
        env["GIT_EDITOR"] = ":"            #git treats ":" as "accept the default text"
        env["GIT_SEQUENCE_EDITOR"] = ":"   #never open an editor for rebase -i
        env["GIT_PAGER"] = "cat"
        env["GIT_MERGE_AUTOEDIT"] = "no"
        return env

    def run(self, argv: list[str]) -> CommandResult:
        reason = blocked_reason(argv)
        if reason is None and self._commands_run >= self.max_commands:
            reason = f"command budget of {self.max_commands} exhausted"
        if reason:
            result = CommandResult(list(argv), -1, "", "", blocked=reason)
        else:
            self._commands_run += 1
            start = time.monotonic()
            try:
                p = subprocess.run(
                    argv, cwd=self.repo_path, env=self._env(), stdin=subprocess.DEVNULL,
                    capture_output=True, timeout=COMMAND_TIMEOUT_SECONDS,
                )
                result = CommandResult(
                    list(argv), p.returncode,
                    p.stdout.decode("utf-8", "replace"), p.stderr.decode("utf-8", "replace"),
                    time.monotonic() - start,
                )
            except subprocess.TimeoutExpired:
                result = CommandResult(list(argv), -1, "", f"timed out after {COMMAND_TIMEOUT_SECONDS}s",
                                       time.monotonic() - start)
        self.events.append({"type": "command", "argv": result.argv, "returncode": result.returncode,
                            "stdout": result.stdout, "stderr": result.stderr,
                            "seconds": round(result.seconds, 3), "blocked": result.blocked})
        return result

    def write_file(self, relpath: str, content: str) -> None:
        """Write a file inside the working tree (never inside .git, never outside)."""
        target = (self.repo_path / relpath).resolve()
        root = self.repo_path.resolve()
        if root not in target.parents or (root / ".git") in (target, *target.parents):
            self.events.append({"type": "write_file", "path": relpath, "blocked": "outside the working tree"})
            raise PermissionError(f"write_file refused: {relpath} is outside the working tree")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content.encode("utf-8"))
        self.events.append({"type": "write_file", "path": relpath, "bytes": len(content.encode("utf-8"))})

    def ask(self, question: str) -> str:
        answer = self.simulated_user.answer(question)
        self.events.append({"type": "question", "question": question, "answer": answer})
        return answer

    def say(self, message: str) -> None:
        """The system's final explanation to the user."""
        self.final_message = message
        self.events.append({"type": "say", "message": message})
