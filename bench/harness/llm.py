from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field

DEFAULT_OLLAMA_URL = "http://localhost:11434/api/generate"


@dataclass
class Reply:
    text: str
    parsed: dict | None      # None when the model's output was not valid JSON
    attempts: int            # how many tries it took (parse failures are retried)
    seconds: float
    raw_attempts: list[str] = field(default_factory=list)
    transport_error: str = ""   # set when the server could not be reached at all


class OllamaBackend:
    """Local model through Ollama's HTTP API.

    num_ctx is set explicitly on every call. Ollama's default context is
    small, and when a prompt exceeds it Ollama silently drops the oldest
    content instead of raising, so a system prompt can vanish mid-run.
    """

    def __init__(self, model: str = "qwen2.5:7b", url: str = DEFAULT_OLLAMA_URL,
                 num_ctx: int = 8192, temperature: float = 0.0, seed: int = 1,
                 timeout: int = 180, max_attempts: int = 3, keep_alive: str = "30m"):
        self.model, self.url, self.num_ctx = model, url, num_ctx
        self.temperature, self.seed, self.timeout = temperature, seed, timeout
        self.max_attempts = max_attempts
        self.keep_alive = keep_alive

    @property
    def name(self) -> str:
        return f"ollama/{self.model}"

    def _post(self, prompt: str, system: str | None) -> str:
        payload = {
            "model": self.model, "prompt": prompt, "format": "json", "stream": False,
            # Without this Ollama unloads the model between requests, and
            # reloading 4.7 GB from disk costs ~8s on every single call.
            "keep_alive": self.keep_alive,
            "options": {"temperature": self.temperature, "seed": self.seed, "num_ctx": self.num_ctx},
        }
        if system:
            payload["system"] = system
        request = urllib.request.Request(
            self.url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            return json.loads(response.read().decode())["response"]

    def json_reply(self, prompt: str, system: str | None = None) -> Reply:
        """Ask for JSON, retrying if the model returns something unparseable.
        Parse failures are counted, not hidden: for small models they are a
        result worth reporting, not noise to sweep up."""
        start, raw, transport = time.monotonic(), [], ""
        for attempt in range(1, self.max_attempts + 1):
            try:
                text = self._post(prompt, system)
            except (urllib.error.URLError, TimeoutError, OSError) as e:
                transport = str(e)
                raw.append(f"<request failed: {e}>")
                continue
            raw.append(text)
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                return Reply(text, parsed, attempt, time.monotonic() - start, raw)
        return Reply(raw[-1] if raw else "", None, self.max_attempts, time.monotonic() - start,
                     raw, transport_error=transport)


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
