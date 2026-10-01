"""Guards for two privacy/scope rules:

- EIS-2: the LLM step signals per fragment and is not asked to judge the
  interpreter, and receives no session-level average that would invite it.
- EIS-5 / BIO2 8.15: no log call writes transcript or translation text. Text
  may only appear in a log call wrapped in len(); this is checked statically
  over every log call in app/, so a new offending call fails here.
"""
from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.services import feedback

APP_DIR = Path(__file__).resolve().parents[1] / "app"
LOG_METHODS = {"debug", "info", "warning", "error", "exception", "critical"}
# Variables that hold utterance or translation text somewhere in app/.
TEXT_NAMES = {"orig", "trans", "text", "texts", "source_text", "interp_text",
              "response_text", "cleaned", "known_terms", "user_content"}


def _is_text_access(node: ast.AST) -> bool:
    if isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Constant):
        return node.slice.value == "text"
    if isinstance(node, ast.Attribute) and node.attr in ("text", "known_terms"):
        return True
    if isinstance(node, ast.Name):
        return node.id in TEXT_NAMES or node.id.endswith("_texts")
    return False


def _offending_args(arg: ast.AST) -> bool:
    """True if `arg` exposes text that is not wrapped in len()."""
    if isinstance(arg, ast.Call) and isinstance(arg.func, ast.Name) and arg.func.id == "len":
        return False
    return any(_is_text_access(n) for n in ast.walk(arg))


def _log_calls():
    for path in sorted(APP_DIR.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id in ("log", "logger")
                    and node.func.attr in LOG_METHODS):
                yield path, node


class TestNoTranscriptInLogs:
    def test_scanner_sees_the_log_calls(self):
        # Sanity check: if the walk finds nothing, the test below proves nothing.
        assert sum(1 for _ in _log_calls()) > 50

    def test_scanner_flags_a_known_bad_call(self):
        bad = ast.parse('log.info("%r", seg["text"][:60])').body[0].value
        ok = ast.parse('log.info("%d", len(seg["text"]))').body[0].value
        assert any(_offending_args(a) for a in bad.args[1:])
        assert not any(_offending_args(a) for a in ok.args[1:])

    def test_no_log_call_writes_text(self):
        offenders = [
            f"{path.relative_to(APP_DIR.parent).as_posix()}:{call.lineno}"
            for path, call in _log_calls()
            if any(_offending_args(a) for a in call.args[1:])
        ]
        assert offenders == []


class TestFeedbackDoesNotJudgeInterpreter:
    def test_prompt_frames_signalling_not_grading(self):
        prompt = feedback._SYSTEM_PROMPT
        assert "beoordelaar" not in prompt
        assert "Je beoordeelt de tolk NIET" in prompt
        assert "Samenvattende beoordeling" not in prompt
        assert "hergehoor" in prompt  # only in the instruction NOT to advise one

    @pytest.mark.asyncio
    async def test_prompt_contains_no_session_average(self):
        pair = {
            "source_block": {"text": "Yirmi dokuz yaşındayım."},
            "interp_block": {"text": "Hij is negenentwintig."},
            "scoring_text": "Ik ben negenentwintig.",
        }
        reply = SimpleNamespace(
            content=[SimpleNamespace(text='{"overall_feedback": "x", "pairs": []}')],
            usage=SimpleNamespace(input_tokens=1, output_tokens=1),
            stop_reason="end_turn",
        )
        client = SimpleNamespace(messages=SimpleNamespace(create=AsyncMock(return_value=reply)))

        with patch.object(feedback, "_get_client", return_value=client):
            await feedback.generate_feedback([pair], [0.8], [pair], [0.6])

        user_content = client.messages.create.call_args.kwargs["messages"][0]["content"]
        assert "Gemiddelde" not in user_content
        assert "gelijkenis: 0.800" in user_content  # per-pair score still sent
