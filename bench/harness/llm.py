"""The benchmark's view of the model backends.

The backends themselves live in the library (`src/git_rescue/llm.py`): the tool
must not import its own benchmark, or the installed `git rescue` command fails
with "No module named 'bench'". Only the benchmark's own scripted stand-in and
the model-listing command live here.
"""
from __future__ import annotations

import json
import sys

from src.git_rescue.llm import (  # noqa: F401  (re-exported for the benchmark and its tests)
    DEFAULT_OLLAMA_URL, PRESETS, OllamaBackend, OpenAICompatibleBackend, Reply,
    build_backend, list_models, rate_limit_delay,
)


class ScriptedBackend:
    """Returns canned replies. For testing the harness without a model."""

    def __init__(self, replies: list[dict | str]):
        self.replies, self.calls = list(replies), []
        self.name = "scripted"

    def json_reply(self, prompt: str, system: str | None = None) -> Reply:
        self.calls.append(prompt)
        item = self.replies.pop(0) if self.replies else {}
        if isinstance(item, str):  # a raw string simulates unparseable output
            return Reply(item, None, 1, 0.0, [item])
        text = json.dumps(item)
        return Reply(text, item, 1, 0.0, [text])


if __name__ == "__main__":
    # uv run python -m bench.harness.llm groq     -> list models this key can use
    import sys

    for name in list_models(sys.argv[1] if len(sys.argv) > 1 else "groq"):
        print(name)
