"""The hosted backend, tested against a fake local server that speaks the
OpenAI chat-completions format. No API key or network access needed."""
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from bench.harness.llm import OpenAICompatibleBackend, build_backend


def serve(responses):
    """Start a server that answers each POST with the next (status, body)."""
    seen = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            seen.append({"body": body, "auth": self.headers.get("Authorization"), "path": self.path,
                         "agent": self.headers.get("User-Agent")})
            status, payload = responses.pop(0)
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(payload).encode())

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, seen


def completion(text):
    return {"choices": [{"message": {"role": "assistant", "content": text}}]}


def backend_for(server, **kw):
    return OpenAICompatibleBackend("test-model", f"http://127.0.0.1:{server.server_port}/v1/",
                                   "secret-key", **kw)


def test_a_json_reply_is_parsed_and_the_request_is_well_formed():
    server, seen = serve([(200, completion('{"tool": "reflog"}'))])
    reply = backend_for(server).json_reply("the user says hi", system="be helpful")
    assert reply.parsed == {"tool": "reflog"} and reply.attempts == 1
    req = seen[0]
    assert req["path"] == "/v1/chat/completions"
    assert req["auth"] == "Bearer secret-key"
    assert req["body"]["messages"][0] == {"role": "system", "content": "be helpful"}
    assert req["body"]["messages"][1]["content"] == "the user says hi"
    assert req["body"]["response_format"] == {"type": "json_object"}


def test_unparseable_output_is_retried_then_reported():
    server, _ = serve([(200, completion("not json"))] * 3)
    reply = backend_for(server).json_reply("x")
    assert reply.parsed is None and reply.attempts == 3 and reply.transport_error == ""


def test_a_retry_that_succeeds_counts_its_attempts():
    server, _ = serve([(200, completion("prose")), (200, completion('{"ready": true}'))])
    reply = backend_for(server).json_reply("x")
    assert reply.parsed == {"ready": True} and reply.attempts == 2


def test_a_rate_limit_is_a_transport_error_not_a_bad_model(monkeypatch):
    """Free tiers answer 429 when you go too fast. That must never be
    scored as the model producing garbage."""
    monkeypatch.setattr("bench.harness.llm.time.sleep", lambda s: None)
    server, _ = serve([(429, {"error": {"message": "quota exceeded"}})] * 3)
    backend = backend_for(server)
    backend.max_rate_limit_waits = 0
    reply = backend.json_reply("x")
    assert reply.parsed is None and "429" in reply.transport_error


def test_a_bad_key_is_a_transport_error():
    server, _ = serve([(401, {"error": {"message": "API key not valid"}})] * 3)
    reply = backend_for(server).json_reply("x")
    assert "401" in reply.transport_error and "not valid" in reply.transport_error


def test_an_unreachable_server_is_a_transport_error():
    b = OpenAICompatibleBackend("m", "http://127.0.0.1:9/v1/", "k", timeout=2)
    assert b.json_reply("x").transport_error


def test_a_missing_key_stops_with_instructions(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(SystemExit) as e:
        build_backend("gemini")
    assert "GEMINI_API_KEY" in str(e.value)


def test_presets_pick_the_right_endpoint(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    b = build_backend("gemini")
    assert "generativelanguage.googleapis.com" in b.url and b.url.endswith("/chat/completions")
    assert b.model == "gemini-3.6-flash"
    assert build_backend("gemini", model="gemini-2.5-pro").model == "gemini-2.5-pro"


def test_seed_is_sent_only_when_set():
    """Gemini answers HTTP 400 'Unknown name seed' if seed is present."""
    server, seen = serve([(200, completion("{}")), (200, completion("{}"))])
    backend_for(server, seed=7).json_reply("x")
    backend_for(server, seed=None).json_reply("x")
    assert seen[0]["body"]["seed"] == 7
    assert "seed" not in seen[1]["body"]


def test_the_gemini_preset_never_sends_seed(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    assert build_backend("gemini", seed=3).seed is None
    monkeypatch.setenv("GROQ_API_KEY", "k")
    assert build_backend("groq", seed=3).seed == 3


def test_an_overloaded_provider_is_retried(monkeypatch):
    """Gemini answered 503 'high demand' mid-run. That is temporary."""
    monkeypatch.setattr("bench.harness.llm.time.sleep", lambda s: None)
    server, _ = serve([(503, {"error": {"message": "high demand"}}), (200, completion('{"ready": true}'))])
    reply = backend_for(server).json_reply("x")
    assert reply.parsed == {"ready": True} and reply.attempts == 2


def test_requests_do_not_use_pythons_default_user_agent():
    """Groq's Cloudflare front answers 403 'error code: 1010' to it."""
    server, seen = serve([(200, completion("{}"))])
    backend_for(server).json_reply("x")
    assert seen[0]["agent"] and "Python-urllib" not in seen[0]["agent"]


def test_a_rejected_json_generation_is_retried_without_json_mode():
    """Groq answers 400 json_validate_failed when the model's output is not
    JSON. That is the model failing, so it must not look like an outage,
    and the retry drops JSON mode and parses the plain reply."""
    rejected = {"error": {"message": "Failed to validate JSON", "code": "json_validate_failed"}}
    server, seen = serve([(400, rejected), (200, completion('Sure! {"ready": true}'))])
    reply = backend_for(server).json_reply("x")
    assert reply.parsed == {"ready": True} and reply.transport_error == ""
    assert "response_format" in seen[0]["body"] and "response_format" not in seen[1]["body"]


def test_repeated_json_rejections_are_unparsed_output_not_an_outage():
    rejected = {"error": {"message": "Failed to validate JSON", "code": "json_validate_failed"}}
    server, _ = serve([(400, rejected)] + [(200, completion("no json here"))] * 2)
    reply = backend_for(server).json_reply("x")
    assert reply.parsed is None and reply.transport_error == ""


def test_other_400s_are_still_transport_errors():
    server, _ = serve([(400, {"error": {"message": "Unknown name seed"}})] * 3)
    assert "400" in backend_for(server).json_reply("x").transport_error


@pytest.mark.parametrize("text,expected", [
    ('{"a": 1}', {"a": 1}),
    ('```json\n{"a": 1}\n```', {"a": 1}),
    ('Here you go: {"a": {"b": 2}} done', {"a": {"b": 2}}),
    ("[1, 2]", None),
    ("no braces", None),
    ("{broken", None),
])
def test_lenient_object_parsing(text, expected):
    from bench.harness.llm import _loads_object
    assert _loads_object(text) == expected


def test_a_rate_limit_waits_as_long_as_the_provider_says(monkeypatch):
    """Groq's TPM 429 says how long to wait. Waiting it out must not use up
    an attempt, and must not end the run."""
    slept = []
    monkeypatch.setattr("bench.harness.llm.time.sleep", slept.append)
    limit = {"error": {"message": "Rate limit reached on tokens per minute (TPM): Limit 8000, "
                                  "Used 7146, Requested 1136. Please try again in 2.114999999s."}}
    server, _ = serve([(429, limit), (429, limit), (200, completion('{"ready": true}'))])
    reply = backend_for(server).json_reply("x")
    assert reply.parsed == {"ready": True} and reply.attempts == 1 and reply.transport_error == ""
    assert slept == [pytest.approx(2.615), pytest.approx(2.615)]


def test_a_daily_quota_is_not_waited_out(monkeypatch):
    slept = []
    monkeypatch.setattr("bench.harness.llm.time.sleep", slept.append)
    daily = {"error": {"message": "tokens per day (TPD) limit. Please try again in 7m12s."}}
    server, _ = serve([(429, daily)] * 3)
    reply = backend_for(server).json_reply("x")
    assert "429" in reply.transport_error and all(s <= 30 for s in slept)


@pytest.mark.parametrize("body,header,expected", [
    ("Please try again in 2.114999999s.", None, 2.615),
    ("Please try again in 345ms.", None, 0.845),
    ("Please try again in 1m2.5s.", None, 63.0),
    ("Please retry in 17.3s.", None, 17.8),
    ("quota exceeded", "4", 4.5),
    ("quota exceeded", None, 5.0),
])
def test_rate_limit_delay(body, header, expected):
    from bench.harness.llm import rate_limit_delay
    assert rate_limit_delay(body, header, 1) == pytest.approx(expected)


def test_a_tool_call_rejection_is_bad_output_not_an_outage():
    """gpt-oss sometimes emits a tool call; Groq answers 400 tool_use_failed.
    That is the model's failure, so it is retried and never a transport error."""
    rejected = {"error": {"message": "Tool choice is none, but model called a tool",
                          "code": "tool_use_failed"}}
    server, _ = serve([(400, rejected), (200, completion('{"ready": true}'))])
    reply = backend_for(server).json_reply("x")
    assert reply.parsed == {"ready": True} and "rejected" in reply.raw_attempts[0]

    server, _ = serve([(400, rejected)] * 3)
    reply = backend_for(server).json_reply("x")
    assert reply.parsed is None and reply.transport_error == ""


def test_an_empty_reply_records_why():
    """gpt-oss sometimes returns empty content. The transcript must say why."""
    empty = {"choices": [{"finish_reason": "length",
                          "message": {"role": "assistant", "content": "", "reasoning": "x" * 50}}]}
    server, _ = serve([(200, empty)] * 3)
    reply = backend_for(server).json_reply("x")
    assert reply.parsed is None and reply.transport_error == ""
    assert "finish_reason=length" in reply.text and "reasoning_chars=50" in reply.text


def test_an_empty_reply_is_retried_with_a_nudge_not_the_same_prompt():
    empty = {"choices": [{"finish_reason": "stop", "message": {"role": "assistant", "content": ""}}]}
    server, seen = serve([(200, empty), (200, completion('{"ready": true}'))])
    reply = backend_for(server).json_reply("original prompt")
    assert reply.parsed == {"ready": True}
    assert "was empty" not in seen[0]["body"]["messages"][-1]["content"]
    assert "was empty" in seen[1]["body"]["messages"][-1]["content"]
