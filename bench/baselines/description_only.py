from __future__ import annotations

from src.git_rescue.plan import split_command

SYSTEM_PROMPT = """You are helping a developer recover from a git problem.
You cannot see their repository. You cannot run commands to inspect it.

Reply with JSON only, in this shape:
{"questions": ["..."], "commands": ["git ...", "git ..."], "explanation": "..."}

- "questions": things you need the user to tell you. Leave empty if none.
- "commands": the exact git commands to run, in order. Every command must be
  literal and runnable as typed. Never use placeholders like <branch>,
  <commit-hash> or {sha}: the user will run these exactly as written.
  If you do not know a value and cannot ask for it, leave commands empty.
- "explanation": one or two sentences for the user.

Ask questions first if you need them; you will get answers and another turn."""


class DescriptionOnlySystem:
    uses_oracle = False

    def __init__(self, backend, allow_questions: bool = True, max_turns: int = 3):
        self.backend = backend
        self.allow_questions = allow_questions
        self.max_turns = max_turns
        self.name = "description_only" + ("" if allow_questions else "_no_questions")

    def run(self, session) -> None:
        transcript = [f"The user says: {session.user_message}"]
        commands, explanation = [], ""

        for _ in range(self.max_turns):
            reply = self.backend.json_reply("\n\n".join(transcript), SYSTEM_PROMPT)
            session.events.append({
                "type": "model_reply", "attempts": reply.attempts,
                "seconds": round(reply.seconds, 2), "parsed": reply.parsed is not None,
                "text": reply.text, "transport_error": reply.transport_error,
                "tokens": reply.tokens,
            })
            if reply.parsed is None:
                session.say("The model did not return usable JSON.")
                return

            explanation = str(reply.parsed.get("explanation", ""))
            commands = [c for c in reply.parsed.get("commands", []) if isinstance(c, str) and c.strip()]
            questions = [q for q in reply.parsed.get("questions", []) if isinstance(q, str) and q.strip()]

            if commands or not questions or not self.allow_questions:
                break
            # Include the model's own reply, not just the answers: without it
            # the model has no memory of having asked and repeats itself.
            answers = [f"Q: {q}\nA: {session.ask(q)}" for q in questions[:3]]
            transcript.append("You asked:\n" + "\n".join(answers)
                              + "\n\nNow give commands, or ask something different.")

        for command in commands:
            result = session.run(split_command(command))
            if result.blocked or result.returncode != 0:
                break  # later steps assume this one worked

        session.say(explanation)
