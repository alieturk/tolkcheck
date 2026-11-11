"""The Gemini route of evaluation/generate_sessions.py, with a fake google-genai client."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

EVAL_DIR = Path(__file__).resolve().parent.parent / "evaluation"
sys.path.insert(0, str(EVAL_DIR))

import generate_sessions as gs  # noqa: E402
from google.genai import types  # noqa: E402

from tests.test_generate_sessions import fenced  # noqa: E402
from tests.test_session_lint import v3_session  # noqa: E402

PV = "tolkcheck-sessies-v3"
SECRET = "test-gemini-key-do-not-log"


def response(text: str, finish=types.FinishReason.STOP, model_version="gemini-3.8-flash-001",
             thought: str | None = None) -> types.GenerateContentResponse:
    parts = [types.Part(text=thought, thought=True)] if thought else []
    parts.append(types.Part(text=text))
    return types.GenerateContentResponse(
        candidates=[types.Candidate(content=types.Content(role="model", parts=parts),
                                    finish_reason=finish)],
        usage_metadata=types.GenerateContentResponseUsageMetadata(
            prompt_token_count=3000, cached_content_token_count=0, candidates_token_count=4000,
            thoughts_token_count=1000, total_token_count=8000),
        model_version=model_version,
    )


class FakeGeminiClient:
    """Mimics client.models.generate_content and records every request."""

    def __init__(self, responses: list):
        self.responses = list(responses)
        self.requests: list[dict] = []
        self.models = SimpleNamespace(generate_content=self._generate)

    def _generate(self, *, model, contents, config):
        self.requests.append({"model": model, "contents": list(contents), "config": config})
        return self.responses.pop(0)


class TestProviderChoice(unittest.TestCase):
    def test_gemini_prefix(self):
        self.assertEqual(gs.provider_for("gemini-3.8-flash"), gs.GEMINI)
        self.assertEqual(gs.provider_for("claude-sonnet-4-6"), gs.ANTHROPIC)
        self.assertEqual(gs.provider_for("geminix"), gs.ANTHROPIC)
        self.assertEqual(gs.provider_for("models/gemini-3.8-flash"), gs.ANTHROPIC)


class TestGeminiCaller(unittest.TestCase):
    def setUp(self):
        self.a = gs.assignment(25)

    def test_valid_first_time(self):
        client = FakeGeminiClient([response(fenced(v3_session(25)), thought="denkstappen")])
        out = gs.generate_one(gs.gemini_caller(client, "gemini-3.8-flash"), "PROMPT", self.a, PV)
        self.assertTrue(out.ok)
        self.assertEqual(out.provider, gs.GEMINI)
        self.assertEqual(out.data["generator"], "gemini-3.8-flash-001")   # the id the API returned
        req = client.requests[0]
        self.assertEqual(req["model"], "gemini-3.8-flash")
        self.assertEqual(req["config"].system_instruction, "PROMPT")
        self.assertEqual(req["contents"][0].role, "user")
        self.assertEqual(req["contents"][0].parts[0].text, gs.user_message(self.a))
        self.assertNotIn("denkstappen", out.attempts[0].text)   # thought parts are not the answer

    def test_retry_sends_model_content_back_and_only_errors(self):
        bad = v3_session(25)
        bad["pairs"].pop()
        first = response(fenced(bad))
        client = FakeGeminiClient([first, response(fenced(v3_session(25)))])
        out = gs.generate_one(gs.gemini_caller(client, "gemini-3.8-flash"), "PROMPT", self.a, PV)
        self.assertTrue(out.ok)
        contents = client.requests[1]["contents"]
        self.assertEqual([c.role for c in contents], ["user", "model", "user"])
        self.assertIs(contents[1], first.candidates[0].content)   # passed back unchanged
        self.assertEqual(contents[1].parts[0].text, fenced(bad))
        self.assertIn("7 paren", contents[2].parts[0].text)

    def test_usage_is_summed_under_usage_metadata_names(self):
        bad = v3_session(25)
        bad["pairs"].pop()
        client = FakeGeminiClient([response(fenced(bad)), response(fenced(v3_session(25)))])
        out = gs.generate_one(gs.gemini_caller(client, "gemini-3.8-flash"), "s", self.a, PV)
        self.assertEqual(out.usage["prompt_token_count"], 6000)
        self.assertEqual(out.usage["candidates_token_count"], 8000)
        self.assertEqual(out.usage["thoughts_token_count"], 2000)
        rec = gs.log_record(out)
        self.assertEqual(rec["provider"], "gemini")
        self.assertEqual(rec["model"], "gemini-3.8-flash-001")
        # 6000 × $0.75 + (8000 + 2000) × $3.75, per million
        self.assertAlmostEqual(rec["cost_usd_estimate"], (6000 * 0.75 + 10000 * 3.75) / 1e6)

    def test_max_tokens_and_safety(self):
        client = FakeGeminiClient([response("half", finish=types.FinishReason.MAX_TOKENS)])
        out = gs.generate_one(gs.gemini_caller(client, "gemini-3.8-flash"), "s", self.a, PV, max_retries=0)
        self.assertIn("max_tokens", out.problems[0])
        client = FakeGeminiClient([response("", finish=types.FinishReason.SAFETY)] * 4)
        out = gs.generate_one(gs.gemini_caller(client, "gemini-3.8-flash"), "s", self.a, PV)
        self.assertFalse(out.ok)
        self.assertEqual(len(client.requests), 1)   # a refusal is not retried
        self.assertIn("weigerde", out.problems[0])

    def test_blocked_prompt_without_candidates(self):
        blocked = types.GenerateContentResponse(
            candidates=[], prompt_feedback=types.GenerateContentResponsePromptFeedback(
                block_reason=types.BlockedReason.SAFETY))
        client = FakeGeminiClient([blocked])
        out = gs.generate_one(gs.gemini_caller(client, "gemini-3.8-flash"), "s", self.a, PV)
        self.assertFalse(out.ok)
        self.assertIn("weigerde", out.problems[0])

    def test_key_never_reaches_raw_or_log(self):
        client = FakeGeminiClient([response(fenced(v3_session(25)))])
        out = gs.generate_one(gs.gemini_caller(client, "gemini-3.8-flash"), "s", self.a, PV)
        with tempfile.TemporaryDirectory() as tmp:
            gs.write_outcome(out, Path(tmp))
            written = "".join(p.read_text(encoding="utf-8") for p in Path(tmp).rglob("*") if p.is_file())
        written += json.dumps(gs.log_record(out))
        self.assertNotIn(SECRET, written)


class TestPrices(unittest.TestCase):
    def test_versioned_id_falls_back_to_the_base_price(self):
        usage = {"prompt_token_count": 1_000_000, "candidates_token_count": 1_000_000}
        self.assertAlmostEqual(gs.cost_usd("gemini-3.8-flash", usage), 4.5)
        self.assertAlmostEqual(gs.cost_usd("gemini-3.8-flash-001", usage), 4.5)
        self.assertIsNone(gs.cost_usd("gemini-9-ultra", usage))

    def test_usage_summary_uses_provider_names(self):
        self.assertEqual(gs.usage_summary({"prompt_token_count": 5, "thoughts_token_count": 2}),
                         "prompt 5 · denken 2")


if __name__ == "__main__":
    unittest.main()
