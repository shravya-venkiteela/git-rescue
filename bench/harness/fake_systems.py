from __future__ import annotations
import subprocess
from bench.gitenv import GitError
class SessionRepo:
    """Looks like GitRepo to scenario code; every command goes through the Session."""

    def __init__(self, session):
        self.session = session
        self.path = session.repo_path

    def run(self, *args: str) -> subprocess.CompletedProcess:
        r = self.session.run(["git", *args])
        if r.blocked:
            raise PermissionError(r.blocked)
        return subprocess.CompletedProcess(r.argv, r.returncode, r.stdout, r.stderr)

    def git(self, *args: str) -> str:
        result = self.run(*args)
        if result.returncode != 0:
            raise GitError(args, result)
        return result.stdout.strip()

    def rev(self, ref: str) -> str:
        return self.git("rev-parse", "--verify", ref)

    def write(self, relpath: str, content: str) -> None:
        self.session.write_file(relpath, content)


class ReferenceSystem:
    name = "reference"
    uses_oracle = True

    def run(self, session) -> None:
        scenario, labels = session.oracle
        scenario.module.solve(SessionRepo(session), labels)
        session.say("Applied the scenario's reference solution.")


class WrongFixSystem:
    name = "wrong_fix"
    uses_oracle = True

    def run(self, session) -> None:
        scenario, labels = session.oracle
        fix_name = sorted(scenario.module.WRONG_FIXES)[0]
        scenario.module.WRONG_FIXES[fix_name](SessionRepo(session), labels)
        session.say(f"Applied wrong fix '{fix_name}'.")


class DoNothingSystem:
    name = "do_nothing"
    uses_oracle = False

    def run(self, session) -> None:
        session.say("I didn't change anything.")

SYSTEMS = {s.name: s for s in (ReferenceSystem, WrongFixSystem, DoNothingSystem)}