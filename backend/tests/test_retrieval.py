"""Unit tests for app.services.retrieval.

_parse_source_file and format_context_block are pure functions — tested directly.
retrieve/retrieve_for_pairs touch the DB and the embedding model — both mocked,
same style as test_scoring_and_translation.py (LaBSE and Anthropic are mocked
there too, to avoid loading models / calling APIs in CI).
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.services.retrieval import (
    RETRIEVAL_SCORE_CEILING,
    _parse_source_file,
    format_context_block,
    retrieve,
    retrieve_for_pairs,
)


def _make_pair(source_text: str, interp_text: str) -> dict:
    return {
        "source_block": {"text": source_text},
        "interp_block": {"text": interp_text},
    }


def _make_chunk(source_id: str, category: str = "taxonomy", content: str = "Inhoud.",
                 title: str = "Bron X"):
    chunk = MagicMock()
    chunk.id = uuid4()
    chunk.source_id = source_id
    chunk.category = category
    chunk.content = content
    chunk.title = title
    return chunk


# ── _parse_source_file (frontmatter + paragraph splitting) ───────────────────

class TestParseSourceFile:
    def test_happy_path(self, tmp_path):
        path = tmp_path / "source.md"
        path.write_text(
            "---\n"
            "source_id: test-source\n"
            "category: taxonomy\n"
            "title: Some Author (2024). A Title.\n"
            "language: nl\n"
            "---\n"
            "\n"
            "First paragraph.\n"
            "\n"
            "Second paragraph.\n",
            encoding="utf-8",
        )
        meta, paragraphs = _parse_source_file(path)
        assert meta["source_id"] == "test-source"
        assert meta["category"] == "taxonomy"
        assert meta["title"] == "Some Author (2024). A Title."
        assert meta["language"] == "nl"
        assert paragraphs == ["First paragraph.", "Second paragraph."]

    def test_missing_frontmatter_raises(self, tmp_path):
        path = tmp_path / "bad.md"
        path.write_text("Just some text, no frontmatter.", encoding="utf-8")
        with pytest.raises(ValueError, match="frontmatter"):
            _parse_source_file(path)

    def test_missing_required_field_raises(self, tmp_path):
        path = tmp_path / "bad.md"
        path.write_text(
            "---\nsource_id: x\ncategory: taxonomy\n---\n\nBody paragraph.\n",
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="title"):
            _parse_source_file(path)

    def test_no_paragraphs_raises(self, tmp_path):
        path = tmp_path / "empty.md"
        path.write_text(
            "---\nsource_id: x\ncategory: taxonomy\ntitle: T\n---\n\n",
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="no content paragraphs"):
            _parse_source_file(path)

    def test_multi_paragraph_split_on_blank_lines(self, tmp_path):
        path = tmp_path / "multi.md"
        path.write_text(
            "---\nsource_id: x\ncategory: taxonomy\ntitle: T\n---\n"
            "\nPara one.\n\n\nPara two (extra blank line before it).\n\nPara three.\n",
            encoding="utf-8",
        )
        _, paragraphs = _parse_source_file(path)
        assert paragraphs == ["Para one.", "Para two (extra blank line before it).", "Para three."]


# ── format_context_block (pure formatting) ────────────────────────────────────

class TestFormatContextBlock:
    def test_empty_list_returns_empty_string(self):
        assert format_context_block([]) == ""

    def test_includes_content_and_title_per_chunk(self):
        chunks = [_make_chunk("src-1", content="Belangrijke inhoud.", title="Auteur (2024). Titel.")]
        block = format_context_block(chunks)
        assert "Belangrijke inhoud." in block
        assert "Auteur (2024). Titel." in block
        assert "ACHTERGRONDINFORMATIE" in block

    def test_multiple_chunks_all_present(self):
        chunks = [_make_chunk("a", content="Inhoud A"), _make_chunk("b", content="Inhoud B")]
        block = format_context_block(chunks)
        assert "Inhoud A" in block
        assert "Inhoud B" in block


# ── retrieve_for_pairs (score-ceiling filtering) ──────────────────────────────

class TestRetrieveForPairs:
    @pytest.mark.asyncio
    async def test_only_sub_threshold_pairs_become_queries(self):
        pairs = [
            _make_pair("Bron laag.", "Tolk laag."),   # below ceiling -> queried
            _make_pair("Bron hoog.", "Tolk hoog."),    # above ceiling -> skipped
        ]
        scores = [RETRIEVAL_SCORE_CEILING - 0.1, RETRIEVAL_SCORE_CEILING + 0.1]

        with patch("app.services.retrieval.retrieve", new=AsyncMock(return_value=[])) as mock_retrieve:
            await retrieve_for_pairs(db=AsyncMock(), pairs=pairs, scores=scores)

        called_queries = mock_retrieve.call_args.args[1]
        assert len(called_queries) == 1
        assert "Bron laag." in called_queries[0]
        assert "Tolk laag." in called_queries[0]

    @pytest.mark.asyncio
    async def test_all_pairs_above_ceiling_yields_no_queries(self):
        pairs = [_make_pair("Bron.", "Tolk.")]
        scores = [0.99]

        with patch("app.services.retrieval.retrieve", new=AsyncMock(return_value=[])) as mock_retrieve:
            result = await retrieve_for_pairs(db=AsyncMock(), pairs=pairs, scores=scores)

        # retrieve() is still called, but with an empty query list — its own
        # empty-queries short-circuit (tested separately below) means no chunks
        # come back either way.
        called_queries = mock_retrieve.call_args.args[1]
        assert called_queries == []
        assert result == []


# ── retrieve (embedding + DB failures degrade gracefully) ────────────────────

class TestRetrieve:
    @pytest.mark.asyncio
    async def test_empty_queries_returns_empty_without_touching_db_or_model(self):
        db = AsyncMock()
        result = await retrieve(db, [])
        assert result == []
        db.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_embedding_failure_returns_empty_list(self):
        db = AsyncMock()
        with patch("app.services.retrieval.embed_texts", new=AsyncMock(side_effect=RuntimeError("boom"))):
            result = await retrieve(db, ["een vraag"])
        assert result == []
        db.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_db_failure_returns_empty_list(self):
        db = AsyncMock()
        db.execute = AsyncMock(side_effect=RuntimeError("db down"))
        with patch("app.services.retrieval.embed_texts", new=AsyncMock(return_value=[[0.1, 0.2]])):
            result = await retrieve(db, ["een vraag"])
        assert result == []

    @pytest.mark.asyncio
    async def test_dedupes_chunks_seen_across_multiple_queries(self):
        db = AsyncMock()
        shared_chunk = _make_chunk("shared-source")

        query_result = MagicMock()
        query_result.all.return_value = [(shared_chunk, 0.1)]
        db.execute = AsyncMock(return_value=query_result)

        with patch("app.services.retrieval.embed_texts",
                   new=AsyncMock(return_value=[[0.1, 0.2], [0.3, 0.4]])):
            result = await retrieve(db, ["vraag een", "vraag twee"], top_k=1)

        assert len(result) == 1
        assert result[0].source_id == "shared-source"
