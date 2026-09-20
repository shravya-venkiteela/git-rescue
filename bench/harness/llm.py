from __future__ import annotations

import re

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


class OpenAICompatibleBackend:
    """Any endpoint that speaks the OpenAI chat-completions format.

    Gemini, Groq, OpenRouter and Cerebras all do, so one class covers every
    hosted option: only base_url, model and the API key change. Uses urllib,
    like OllamaBackend, so no SDK dependency is added.
    """

    def __init__(self, model: str, base_url: str, api_key: str,
                 temperature: float = 0.0, seed: int = 1,
                 timeout: int = 120, max_attempts: int = 3):
        self.model = model
        self.url = base_url.rstrip("/") + "/chat/completions"
        self.api_key = api_key
        self.temperature, self.seed, self.timeout = temperature, seed, timeout
        self.max_attempts = max_attempts

    @property
    def name(self) -> str:
        return f"{self.url.split('/')[2]}/{self.model}"

    # Free tiers limit tokens per minute. Groq's 429 says exactly how long to
    # wait ("try again in 2.11s"); the old fixed 10 s back-off with 3 tries
    # gave up on limits that clear in seconds, and two scenarios were lost to it.
    max_rate_limit_waits = 6
    longest_rate_limit_wait = 120.0   # longer than this is a daily quota: give up

    def _post_patiently(self, prompt: str, system: str | None, json_mode: bool = True) -> str:
        """_post, but a 429 is waited out (as the provider asks) and retried
        without using up one of json_reply's attempts."""
        waits = 0
        while True:
            try:
                return self._post(prompt, system, json_mode=json_mode)
            except urllib.error.HTTPError as e:
                if e.code != 429 or waits >= self.max_rate_limit_waits:
                    raise
                body = e.read()
                e.read = lambda b=body: b          # json_reply may still need it
                delay = rate_limit_delay(body.decode("utf-8", "replace"),
                                         e.headers.get("Retry-After") if e.headers else None,
                                         waits + 1)
                if delay > self.longest_rate_limit_wait:
                    raise
                waits += 1
                time.sleep(delay)

    def _post(self, prompt: str, system: str | None, json_mode: bool = True) -> str:
        messages = ([{"role": "system", "content": system}] if system else []) + \
                   [{"role": "user", "content": prompt}]
        payload = {
            "model": self.model, "messages": messages,
            # The hosted equivalent of Ollama's format:json. A reply that is
            # still not parseable is retried and then counted, never fixed up.
            "temperature": self.temperature,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        # Not every provider accepts seed: Gemini rejects the whole request
        # with HTTP 400 ("Unknown name seed"). So it is only sent when set.
        if self.seed is not None:
            payload["seed"] = self.seed
        request = urllib.request.Request(
            self.url, data=json.dumps(payload).encode(),
            # Groq sits behind Cloudflare, which answers 403 "error code: 1010"
            # to Python's default "Python-urllib/3.x" User-Agent.
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {self.api_key}",
                     "User-Agent": "git-rescue-bench/0.1", "Accept": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            body = json.loads(response.read().decode())
        choice = body["choices"][0]
        content = choice["message"].get("content") or ""
        if not content.strip():
            #gpt-oss returned empty content in 3 of 9 runs. Record why (e.g.
            #finish_reason "length" when reasoning used every token), so the
            #transcript shows the cause instead of a blank.
            reasoning = choice["message"].get("reasoning") or ""
            self.last_empty = (f"<empty reply: finish_reason={choice.get('finish_reason')}, "
                               f"reasoning_chars={len(reasoning)}>")
        return content

    def json_reply(self, prompt: str, system: str | None = None) -> Reply:
        start, raw, transport, json_mode = time.monotonic(), [], "", True
        for attempt in range(1, self.max_attempts + 1):
            try:
                text = self._post_patiently(prompt, system, json_mode=json_mode)
            except urllib.error.HTTPError as e:
                body = e.read().decode("utf-8", "replace")
                if e.code == 400 and ("json_validate_failed" in body or "tool_use_failed" in body):
                    # Groq's JSON mode rejects the whole reply when the model's
                    # output is not valid JSON. That is the model failing, not
                    # the service: count it as unparsed output and try again
                    # without JSON mode, parsing the plain reply instead.
                    raw.append(f"<provider rejected the reply: {body[:300]}>")
                    json_mode = False
                    continue
                # Kept long: quota errors name WHICH limit (per-minute or
                # per-day) only near the end, and 300 chars cut that off.
                detail = body[:3000]
                # 429 is a free-tier rate limit, not a bad model: report it as a
                # transport problem so a sweep is never misread as model failure.
                transport = f"HTTP {e.code}: {detail}"
                raw.append(f"<request failed: {transport}>")
                # 429 (rate limit) and 503 (provider overloaded) are both
                # temporary: wait and retry rather than failing the run.
                if e.code in (429, 503) and attempt < self.max_attempts:
                    time.sleep(min(30, 10 * attempt))
                continue
            except (urllib.error.URLError, TimeoutError, OSError) as e:
                transport = str(e)
                raw.append(f"<request failed: {e}>")
                continue
            if not text.strip():
                raw.append(getattr(self, "last_empty", "<empty reply>"))
                continue
            raw.append(text)
            parsed = _loads_object(text)
            if parsed is not None:
                return Reply(text, parsed, attempt, time.monotonic() - start, raw)
        return Reply(raw[-1] if raw else "", None, self.max_attempts, time.monotonic() - start,
                     raw, transport_error=transport)


def _loads_object(text: str) -> dict | None:
    """Parse a JSON object, tolerating prose or code fences around it (what a
    model tends to add once JSON mode is off). Anything else is unparsed."""
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        first, last = text.find("{"), text.rfind("}")
        if first < 0 or last <= first:
            return None
        try:
            value = json.loads(text[first:last + 1])
        except json.JSONDecodeError:
            return None
    return value if isinstance(value, dict) else None


# provider -> (base_url, environment variable holding the key, default model)
PRESETS = {
    "gemini": ("https://generativelanguage.googleapis.com/v1beta/openai/", "GEMINI_API_KEY", "gemini-3.6-flash"),  # 2.5 is closed to new keys
    "groq": ("https://api.groq.com/openai/v1/", "GROQ_API_KEY", "openai/gpt-oss-120b"),  # llama-3.3-70b retired
    "openrouter": ("https://openrouter.ai/api/v1/", "OPENROUTER_API_KEY", "meta-llama/llama-3.3-70b-instruct:free"),
}


def build_backend(provider: str, model: str | None = None, num_ctx: int = 8192, seed: int = 1):
    """'ollama' or a key of PRESETS. Keys come from the environment, never code."""
    import os

    if provider == "ollama":
        return OllamaBackend(model=model or "qwen2.5:7b", num_ctx=num_ctx, seed=seed)
    if provider not in PRESETS:
        raise ValueError(f"unknown provider '{provider}'. Known: ollama, {', '.join(PRESETS)}")
    base_url, env_var, default_model = PRESETS[provider]
    key = os.environ.get(env_var, "").strip()
    if not key:
        raise SystemExit(f"{env_var} is not set. Create a key, then: $env:{env_var} = \"...\"")
    # Gemini's OpenAI-compatible endpoint rejects `seed` (HTTP 400).
    return OpenAICompatibleBackend(model or default_model, base_url, key,
                                   seed=None if provider == "gemini" else seed)


def list_models(provider: str) -> list[str]:
    """Ask a hosted provider which models this key can use. Model names are
    retired often (gemini-2.5-flash and llama-3.3-70b-versatile both vanished
    while this benchmark was being built), so check instead of guessing."""
    import os

    base_url, env_var, _ = PRESETS[provider]
    key = os.environ.get(env_var, "").strip()
    if not key:
        raise SystemExit(f"{env_var} is not set.")
    request = urllib.request.Request(
        base_url.rstrip("/") + "/models",
        headers={"Authorization": f"Bearer {key}", "User-Agent": "git-rescue-bench/0.1"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        body = json.loads(response.read().decode())
    return sorted(m.get("id", "") for m in body.get("data", []))


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


_RETRY_IN = re.compile(r"(?:try again|retry) in\s+(?:(\d+)m(?!s))?\s*([\d.]+)\s*(ms|s)\b", re.I)


def rate_limit_delay(body: str, retry_after: str | None, attempt: int) -> float:
    """Seconds to wait after a 429: the provider's own hint when it gives one
    (Groq: "try again in 1m2.5s" / "345ms"; or a Retry-After header), plus a
    half-second margin; otherwise exponential back-off from 5 s."""
    m = _RETRY_IN.search(body)
    if m:
        value = float(m.group(2))
        seconds = int(m.group(1) or 0) * 60 + (value / 1000 if m.group(3).lower() == "ms" else value)
        return seconds + 0.5
    try:
        return float(retry_after) + 0.5
    except (TypeError, ValueError):
        return min(60.0, 5.0 * 2 ** (attempt - 1))
