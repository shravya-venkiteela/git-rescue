from __future__ import annotations

from src.git_rescue.plan import split_command

SYSTEM_PROMPT = """You are fixing a broken git repository for a developer.

Each turn, reply with JSON only:
{"command": "git ...", "reason": "...", "done": false, "explanation": ""}

- "command": ONE git command to run now. You will see its output next turn.
  Investigate first (status, reflog, log, fsck, stash list), then act.
  Use literal values from output you have actually seen. Never use
  placeholders like <sha>.
- "reason": one short line on why this command.
- "done": set this to true AS SOON AS the repository is fixed. Do not keep
  running commands afterwards. When done is true, "command" is ignored and
  "explanation" tells the user what you did.
- "question": optional, to ask the user something instead of running a command.

Never repeat a command you have already run: it will give the same result
and waste a turn. If a command did not change anything, try something
different or set done to true."""


class UnrestrictedShellSystem:
    uses_oracle = False
    name = "unrestricted_shell"

    def __init__(self, backend, max_turns: int = 15):
        self.backend = backend
        self.max_turns = max_turns

    def run(self, session) -> None:
        history = [f"The user says: {session.user_message}"]
        ran: set[str] = set()

        for turn in range(self.max_turns):
            left = self.max_turns - turn
            history.append(f"({left} turn{'s' if left != 1 else ''} left. Set done to true once fixed.)")
            reply = self.backend.json_reply("\n\n".join(history), SYSTEM_PROMPT)
            history.pop()  #the turn counter is for this turn only
            session.events.append({
                "type": "model_reply", "turn": turn, "attempts": reply.attempts,
                "seconds": round(reply.seconds, 2), "parsed": reply.parsed is not None,
                "text": reply.text, "transport_error": reply.transport_error,
            })
            if reply.parsed is None:
                session.say("The model did not return usable JSON.")
                return

            if reply.parsed.get("done"):
                session.say(str(reply.parsed.get("explanation", "")))
                return

            question = reply.parsed.get("question")
            if question and not reply.parsed.get("command"):
                history.append(f"You asked: {question}\nThe user replied: {session.ask(str(question))}")
                continue

            command = str(reply.parsed.get("command", "")).strip()
            if not command:
                history.append("You gave no command. Reply with a command, or set done to true.")
                continue

            if command in ran:
                history.append(f"You already ran: {command}\nIt gives the same result. "
                               f"Do something different, or set done to true.")
                continue
            ran.add(command)
            result = session.run(split_command(command))
            if result.blocked:
                outcome = f"BLOCKED: {result.blocked}"
            else:
                #Trim: a long log would otherwise crowd out the system prompt.
                out = (result.stdout + result.stderr).strip()[:2000]
                outcome = f"exit code {result.returncode}\n{out or '(no output)'}"
            history.append(f"You ran: {command}\n{outcome}")

        session.say("Ran out of turns.")
