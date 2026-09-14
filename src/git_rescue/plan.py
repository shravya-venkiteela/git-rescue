from __future__ import annotations
import json
from dataclasses import dataclass, field

RISKS = ("safe", "reversible", "destructive")


@dataclass
class Step:
    argv: list[str]            #the exact command, already split
    purpose: str
    claimed_risk: str          #the model's own label; never trusted (see risk.py)

    @property
    def text(self) -> str:
        return " ".join(self.argv)


@dataclass
class Plan:
    diagnosis: str
    confidence: str                                  # low | medium | high
    steps: list[Step] = field(default_factory=list)
    questions: list[str] = field(default_factory=list)
    unrecoverable: list[str] = field(default_factory=list)
    rotate_secrets_first: bool = False
    raw: dict = field(default_factory=dict)

    @property
    def is_question_only(self) -> bool:
        return bool(self.questions) and not self.steps


class PlanError(ValueError):
    """The model's plan was malformed. The message is fed back to it."""


def parse(data: dict) -> Plan:
    """Turn model JSON into a Plan, or raise PlanError with a message the
    model can act on. Validation is strict: a plan that cannot be checked
    cannot be executed."""
    if not isinstance(data, dict):
        raise PlanError("the plan must be a JSON object")

    diagnosis = str(data.get("diagnosis", "")).strip()
    if not diagnosis:
        raise PlanError("'diagnosis' is required: say what you believe went wrong")

    confidence = str(data.get("confidence", "")).strip().lower()
    if confidence not in ("low", "medium", "high"):
        raise PlanError("'confidence' must be exactly one of: low, medium, high")

    steps = []
    for i, raw_step in enumerate(data.get("steps") or [], start=1):
        if not isinstance(raw_step, dict):
            raise PlanError(f"step {i} must be an object with command, purpose and risk")
        command = raw_step.get("command")
        argv = command.split() if isinstance(command, str) else list(command or [])
        if not argv:
            raise PlanError(f"step {i} has no command")
        if argv[0] != "git":
            raise PlanError(f"step {i}: every command must start with 'git', got '{argv[0]}'")
        if any(part.startswith("<") or part.startswith("{") for part in argv):
            raise PlanError(f"step {i}: '{' '.join(argv)}' contains a placeholder. "
                            "Use a literal value you saw in tool output.")
        risk = str(raw_step.get("risk", "")).strip().lower()
        if risk not in RISKS:
            raise PlanError(f"step {i}: 'risk' must be one of {', '.join(RISKS)}")
        purpose = str(raw_step.get("purpose", "")).strip()
        if not purpose:
            raise PlanError(f"step {i}: 'purpose' is required")
        steps.append(Step(argv, purpose, risk))

    questions = [str(q) for q in (data.get("questions") or []) if str(q).strip()]
    if not steps and not questions:
        raise PlanError("a plan needs either steps, or questions to ask the user first")

    return Plan(
        diagnosis=diagnosis,
        confidence=confidence,
        steps=steps,
        questions=questions,
        unrecoverable=[str(u) for u in (data.get("unrecoverable") or []) if str(u).strip()],
        rotate_secrets_first=bool(data.get("rotate_secrets_first", False)),
        raw=data,
    )


SCHEMA_HELP = """{
  "diagnosis": "what went wrong, in one or two sentences",
  "confidence": "low | medium | high",
  "questions": ["only if you must ask the user before acting"],
  "steps": [
    {"command": "git ...", "purpose": "why this step", "risk": "safe | reversible | destructive"}
  ],
  "unrecoverable": ["anything genuinely lost that no command can bring back"],
  "rotate_secrets_first": false
}"""


def to_json(plan: Plan) -> str:
    return json.dumps({
        "diagnosis": plan.diagnosis, "confidence": plan.confidence,
        "steps": [{"command": s.text, "purpose": s.purpose, "risk": s.claimed_risk} for s in plan.steps],
        "questions": plan.questions, "unrecoverable": plan.unrecoverable,
        "rotate_secrets_first": plan.rotate_secrets_first,
    }, indent=2)