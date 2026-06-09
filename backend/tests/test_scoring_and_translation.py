"""Unit tests for scoring helpers and translate_to_dutch.

aggregate_scores is a pure function — no mocking needed.
translate_to_dutch calls the Anthropic API — mocked via unittest.mock.
score_segments calls LaBSE — mocked to avoid loading the model in CI.
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.scoring import aggregate_scores


# ── aggregate_scores (pure function) ─────────────────────────────────────────

class TestAggregateScores:
    def test_empty_returns_zeros(self):
        result = aggregate_scores([])
        assert result == {"mean": 0.0, "min": 0.0, "max": 0.0}

    def test_single_score(self):
        result = aggregate_scores([0.75])
        assert result["mean"] == pytest.approx(0.75)
        assert result["min"]  == pytest.approx(0.75)
        assert result["max"]  == pytest.approx(0.75)

    def test_multiple_scores(self):
        scores = [0.2, 0.6, 1.0]
        result = aggregate_scores(scores)
        assert result["mean"] == pytest.approx(0.6)
        assert result["min"]  == pytest.approx(0.2)
        assert result["max"]  == pytest.approx(1.0)

    def test_all_zeros(self):
        result = aggregate_scores([0.0, 0.0, 0.0])
        assert result["mean"] == 0.0
        assert result["min"]  == 0.0
        assert result["max"]  == 0.0

    def test_all_ones(self):
        result = aggregate_scores([1.0, 1.0, 1.0])
        assert result["mean"] == pytest.approx(1.0)

    def test_large_list_precision(self):
        scores = [i / 100 for i in range(101)]  # 0.00 … 1.00
        result = aggregate_scores(scores)
        assert result["mean"] == pytest.approx(0.5)
        assert result["min"]  == pytest.approx(0.0)
        assert result["max"]  == pytest.approx(1.0)


# ── translate_to_dutch (mocked Anthropic client) ──────────────────────────────

def _make_mock_message(content: str) -> MagicMock:
    """Build a mock Anthropic Message with the given text content."""
    msg = MagicMock()
    msg.content = [MagicMock(text=content)]
    return msg


class TestTranslateToDutch:
    @pytest.mark.asyncio
    async def test_happy_path(self):
        """Valid JSON array response → returns translations."""
        from app.services.feedback import translate_to_dutch

        texts = ["نام من احمد است.", "از کابل آمده‌ام."]
        translations = ["Mijn naam is Ahmad.", "Ik kom uit Kabul."]

        mock_msg = _make_mock_message(json.dumps(translations))
        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=mock_msg)

        with patch("app.services.feedback._get_client", return_value=mock_client):
            result = await translate_to_dutch(texts, "fa")

        assert result == translations

    @pytest.mark.asyncio
    async def test_markdown_fences_stripped(self):
        """Claude sometimes wraps JSON in ```json … ``` — should be stripped."""
        from app.services.feedback import translate_to_dutch

        texts = ["Merhaba."]
        translations = ["Hallo."]
        raw = "```json\n" + json.dumps(translations) + "\n```"

        mock_msg = _make_mock_message(raw)
        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=mock_msg)

        with patch("app.services.feedback._get_client", return_value=mock_client):
            result = await translate_to_dutch(texts, "tr")

        assert result == translations

    @pytest.mark.asyncio
    async def test_invalid_json_falls_back(self):
        """Unparseable response → returns original texts unchanged."""
        from app.services.feedback import translate_to_dutch

        texts = ["Brontekst."]
        mock_msg = _make_mock_message("Dit is geen JSON.")
        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=mock_msg)

        with patch("app.services.feedback._get_client", return_value=mock_client):
            result = await translate_to_dutch(texts, "fa")

        assert result == texts  # fallback

    @pytest.mark.asyncio
    async def test_wrong_list_length_falls_back(self):
        """JSON array of wrong length → fallback to originals."""
        from app.services.feedback import translate_to_dutch

        texts = ["Een.", "Twee.", "Drie."]
        mock_msg = _make_mock_message(json.dumps(["Only one translation."]))
        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=mock_msg)

        with patch("app.services.feedback._get_client", return_value=mock_client):
            result = await translate_to_dutch(texts, "fa")

        assert result == texts

    @pytest.mark.asyncio
    async def test_empty_input(self):
        """Empty texts list → API is called but result is an empty list."""
        from app.services.feedback import translate_to_dutch

        mock_msg = _make_mock_message("[]")
        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=mock_msg)

        with patch("app.services.feedback._get_client", return_value=mock_client):
            result = await translate_to_dutch([], "fa")

        assert result == []

    @pytest.mark.asyncio
    async def test_non_string_items_coerced(self):
        """If Claude returns numbers instead of strings, they are coerced to str."""
        from app.services.feedback import translate_to_dutch

        texts = ["Een."]
        mock_msg = _make_mock_message(json.dumps([42]))
        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=mock_msg)

        with patch("app.services.feedback._get_client", return_value=mock_client):
            result = await translate_to_dutch(texts, "fa")

        assert result == ["42"]


# ── score_segments (mocked LaBSE) ────────────────────────────────────────────

class TestScoreSegments:
    @pytest.mark.asyncio
    async def test_returns_one_score_per_pair(self):
        """score_segments should return exactly len(sources) float values."""
        from app.services.scoring import score_segments

        sources = ["Hallo.", "Goede morgen.", "Hoe gaat het?"]
        targets = ["Hallo.", "Goede morgen.", "Hoe gaat het?"]
        fake_scores = [0.99, 0.97, 0.95]

        with patch("app.services.scoring._score_sync", return_value=fake_scores):
            result = await score_segments(sources, targets)

        assert result == fake_scores
        assert len(result) == 3

    @pytest.mark.asyncio
    async def test_identical_texts_high_score(self):
        """Identical source/target should produce a very high cosine similarity."""
        from app.services.scoring import score_segments

        # Use a score that the real LaBSE would return for identical sentences
        with patch("app.services.scoring._score_sync", return_value=[0.9999]):
            result = await score_segments(["Hallo."], ["Hallo."])

        assert result[0] > 0.99

    @pytest.mark.asyncio
    async def test_unrelated_texts_low_score(self):
        """Completely unrelated texts should produce a low cosine similarity."""
        from app.services.scoring import score_segments

        with patch("app.services.scoring._score_sync", return_value=[0.04]):
            result = await score_segments(
                ["Ik kom uit Kabul."],
                ["De temperatuur op Mars is zeer koud."],
            )

        assert result[0] < 0.3

    @pytest.mark.asyncio
    async def test_empty_lists(self):
        """Empty input → empty output without error."""
        from app.services.scoring import score_segments

        with patch("app.services.scoring._score_sync", return_value=[]):
            result = await score_segments([], [])

        assert result == []
