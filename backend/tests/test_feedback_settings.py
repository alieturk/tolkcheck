"""The LaBSE cut-offs and temperature in feedback.py come from settings (DV4)."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.config import settings
from app.services import feedback


def test_score_rules_are_off_by_default():
    assert settings.llm_score_rules is False
    prompt = feedback.build_system_prompt()
    assert "Score ≥" not in prompt
    assert "{score_rules}" not in prompt
    assert feedback._SYSTEM_PROMPT == prompt


def test_prompt_keeps_current_cutoffs_when_rules_are_on(monkeypatch):
    monkeypatch.setattr(settings, "llm_score_rules", True)
    prompt = feedback.build_system_prompt()
    assert "Score ≥ 0.70" in prompt
    assert "Score 0.50–0.69" in prompt
    assert "Score < 0.50" in prompt
    assert "als de score ≥ 0.65" in prompt
    assert "{score_rules}" not in prompt


def test_calibrated_threshold_is_written_into_prompt(monkeypatch):
    monkeypatch.setattr(settings, "llm_score_rules", True)
    monkeypatch.setattr(settings, "labse_correct_threshold", 0.83)
    monkeypatch.setattr(settings, "labse_likely_issue_threshold", 0.61)
    monkeypatch.setattr(settings, "labse_no_addition_threshold", 0.78)
    prompt = feedback.build_system_prompt()
    assert "Score ≥ 0.83" in prompt
    assert "Score 0.61–0.82" in prompt
    assert "als de score ≥ 0.78" in prompt
    assert "0.70" not in prompt


def test_prompt_names_permitted_exceptions_and_defines_severity():
    prompt = feedback.build_system_prompt()
    assert "vraagt om herhaling" in prompt and "regionaal woord" in prompt
    assert "verbetert zichzelf direct" in prompt and "zelfcorrectie" in prompt
    assert "GEEN afwijking" in prompt
    for level in ("- critical:", "- high:", "- medium:", "- low:"):
        assert level in prompt


@pytest.mark.asyncio
async def test_llm_sees_the_original_client_text_and_the_helper_translation():
    pair = {"source_block": {"text": "Evet dedim."}, "interp_block": {"text": "Ik zei nee."},
            "scoring_text": "Ik zei ja."}
    message = MagicMock()
    message.content = [MagicMock(text='{"overall_feedback": "", "pairs": []}')]
    message.usage.input_tokens = message.usage.output_tokens = 1
    message.stop_reason = "end_turn"
    client = MagicMock()
    client.messages.create = AsyncMock(return_value=message)
    with patch.object(feedback, "_get_client", return_value=client):
        await feedback.generate_feedback([pair], [0.9])
    sent = client.messages.create.await_args.kwargs["messages"][0]["content"]
    assert "Evet dedim." in sent and "Ik zei ja." in sent and "Ik zei nee." in sent


def test_rules_can_be_switched_off(monkeypatch):
    monkeypatch.setattr(settings, "llm_score_rules", False)
    prompt = feedback.build_system_prompt()
    assert "Markeer NOOIT" not in prompt
    assert "ook bij een hoge score" in prompt
    # the non-judgement framing stays regardless
    assert "Je beoordeelt de tolk NIET" in prompt


def _reply(text: str):
    return SimpleNamespace(
        content=[SimpleNamespace(text=text)],
        usage=SimpleNamespace(input_tokens=1, output_tokens=1),
        stop_reason="end_turn",
    )


@pytest.mark.asyncio
async def test_feedback_call_uses_configured_temperature():
    client = SimpleNamespace(messages=SimpleNamespace(
        create=AsyncMock(return_value=_reply('{"overall_feedback": "x", "pairs": []}'))))
    pair = {"source_block": {"text": "a"}, "interp_block": {"text": "b"}, "scoring_text": "a"}
    with patch.object(feedback, "_get_client", return_value=client):
        await feedback.generate_feedback([pair], [0.8], [pair], [0.6])
    assert client.messages.create.call_args.kwargs["temperature"] == settings.llm_temperature == 0.0


@pytest.mark.asyncio
async def test_translation_call_uses_configured_temperature():
    client = SimpleNamespace(messages=SimpleNamespace(
        create=AsyncMock(return_value=_reply('["een"]'))))
    with patch.object(feedback, "_get_client", return_value=client):
        out = await feedback.translate_to_dutch(["bir"], "tr")
    assert out == ["een"]
    assert client.messages.create.call_args.kwargs["temperature"] == 0.0
