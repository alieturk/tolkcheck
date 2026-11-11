"""Tests for salvaging a feedback response cut off by the output token limit.

A real 40-block hearing overran max_tokens=4096 mid-string. json.loads threw,
the handler stored the raw JSON blob as prose with structured_issues=[], and the
UI showed "Kritieke problemen (0)" against a feedback panel full of critical
findings. Every complete pair before the cut was intact and recoverable.
"""
from __future__ import annotations

import json

from app.services.feedback import _extract_overall, _parse_feedback_json

DOC = {
    "overall_feedback": "Samenvattend oordeel over het gehoor.",
    "pairs": [
        {"pair_index": 0, "direction": "client_to_officer", "issues": []},
        {"pair_index": 1, "direction": "client_to_officer",
         "issues": [{"type": "omission", "severity": "critical",
                     "description": "Detail ontbreekt", "originalPhrase": "a",
                     "translatedPhrase": "b"}]},
        {"pair_index": 0, "direction": "officer_to_client", "issues": []},
    ],
}


class TestParseFeedbackJson:
    def test_intact_document(self):
        assert _parse_feedback_json(json.dumps(DOC)) == DOC

    def test_truncated_mid_pair_keeps_complete_pairs(self):
        full = json.dumps(DOC)
        cut = full.index('{"pair_index": 0, "direction": "officer_to_client"')
        truncated = full[:cut] + '{"pair_index": 0, "issues": [{"description": "Hei bedankt'
        parsed = _parse_feedback_json(truncated)
        assert parsed is not None
        assert len(parsed["pairs"]) == 2
        assert parsed["overall_feedback"] == DOC["overall_feedback"]
        assert parsed["pairs"][1]["issues"][0]["severity"] == "critical"

    def test_truncated_before_any_pair_closes_returns_none(self):
        full = json.dumps(DOC)
        truncated = full[: full.index('"pairs"') + 12]
        assert _parse_feedback_json(truncated) is None

    def test_braces_inside_strings_do_not_confuse_the_scan(self):
        doc = {"overall_feedback": 'Tolk zei "{niet}" en [dit]',
               "pairs": [{"pair_index": 0, "issues": []}]}
        full = json.dumps(doc)
        assert _parse_feedback_json(full) == doc
        truncated = full[:-2] + ', {"pair_index": 1, "issues": [{"desc'
        parsed = _parse_feedback_json(truncated)
        assert parsed is not None and len(parsed["pairs"]) == 1

    def test_escaped_quotes_inside_strings(self):
        doc = {"overall_feedback": 'Hij zei \\"stop\\" tegen mij',
               "pairs": [{"pair_index": 0, "issues": []}]}
        full = json.dumps(doc)
        parsed = _parse_feedback_json(full + "trailing garbage")
        assert parsed is not None
        assert len(parsed["pairs"]) == 1

    def test_empty_pairs_array(self):
        doc = {"overall_feedback": "Geen problemen.", "pairs": []}
        assert _parse_feedback_json(json.dumps(doc)) == doc

    def test_unrecoverable_returns_none(self):
        assert _parse_feedback_json("this is not json at all") is None


class TestExtractOverall:
    def test_pulls_the_summary_from_a_broken_document(self):
        broken = '{"overall_feedback": "Toch bruikbaar oordeel.", "pairs": [{"pair'
        assert _extract_overall(broken) == "Toch bruikbaar oordeel."

    def test_handles_escaped_quotes(self):
        broken = '{"overall_feedback": "Zin met \\"aanhalingstekens\\" erin", "pairs": ['
        assert _extract_overall(broken) == 'Zin met "aanhalingstekens" erin'

    def test_returns_none_when_the_value_itself_is_cut(self):
        assert _extract_overall('{"overall_feedback": "afgekapt midden in') is None

    def test_returns_none_when_key_absent(self):
        assert _extract_overall('{"pairs": []}') is None


# ── Several JSON blocks, and answers that cannot be read (DV4 dev, S26) ─────────
import asyncio  # noqa: E402
from types import SimpleNamespace  # noqa: E402

from app.services import feedback  # noqa: E402
from app.services.feedback import _parse_feedback_response  # noqa: E402

ISSUE = {"type": "omission", "severity": "high", "description": "Bijzin ontbreekt",
         "originalPhrase": "a", "translatedPhrase": "b"}


def _fenced(doc: dict) -> str:
    return "```json\n" + json.dumps(doc, ensure_ascii=False, indent=2) + "\n```"


C2O_BLOCK = {"overall_feedback": "Antwoorden: één afwijking.",
             "pairs": [{"pair_index": 0, "direction": "client_to_officer", "issues": [ISSUE]},
                       {"pair_index": 1, "direction": "client_to_officer", "issues": []}]}
O2C_BLOCK = {"overall_feedback": "Vragen: geen afwijkingen.",
             "pairs": [{"pair_index": 0, "direction": "officer_to_client", "issues": []},
                       {"pair_index": 1, "direction": "officer_to_client", "issues": []}]}


class TestSeveralBlocks:
    def test_two_blocks_are_merged(self):
        text = _fenced(C2O_BLOCK) + "\n\n**Aanvulling AMBTENAAR→CLIËNT paren:**\n\n" + _fenced(O2C_BLOCK)
        parsed = _parse_feedback_response(text)
        keys = [(p["direction"], p["pair_index"]) for p in parsed["pairs"]]
        assert keys == [("client_to_officer", 0), ("client_to_officer", 1),
                        ("officer_to_client", 0), ("officer_to_client", 1)]
        assert parsed["pairs"][0]["issues"] == [ISSUE]
        assert "Antwoorden" in parsed["overall_feedback"] and "Vragen" in parsed["overall_feedback"]

    def test_duplicate_pairs_and_issues_are_merged_once(self):
        again = {"overall_feedback": "Antwoorden: één afwijking.",
                 "pairs": [{"pair_index": 0, "direction": "client_to_officer",
                            "issues": [ISSUE, {**ISSUE, "severity": "critical"}]}]}
        parsed = _parse_feedback_response(_fenced(C2O_BLOCK) + "\n" + _fenced(again))
        entries = [p for p in parsed["pairs"] if (p["direction"], p["pair_index"]) == ("client_to_officer", 0)]
        assert len(entries) == 1
        assert entries[0]["issues"] == [ISSUE, {**ISSUE, "severity": "critical"}]
        assert parsed["overall_feedback"] == "Antwoorden: één afwijking."

    def test_single_unfenced_document_still_works(self):
        assert _parse_feedback_response(json.dumps(DOC))["pairs"][1]["issues"][0]["severity"] == "critical"

    def test_truncated_second_block_keeps_its_complete_pairs(self):
        second = _fenced(O2C_BLOCK)
        cut = second[: second.rfind('{"pair_index": 1') if '{"pair_index": 1' in second else -40]
        parsed = _parse_feedback_response(_fenced(C2O_BLOCK) + "\n" + cut)
        assert ("officer_to_client", 0) in {(p["direction"], p["pair_index"]) for p in parsed["pairs"]}

    def test_nothing_readable_returns_none(self):
        assert _parse_feedback_response("Sorry, ik kan dit niet beoordelen.") is None
        assert _parse_feedback_response("```json\n{kapot\n```") is None


def _run_feedback(answer: str, n_c2o: int = 2, n_o2c: int = 2) -> dict:
    message = SimpleNamespace(content=[SimpleNamespace(text=answer)], stop_reason="end_turn",
                              usage=SimpleNamespace(input_tokens=1, output_tokens=1))

    class Messages:
        async def create(self, **kwargs):
            return message

    old = feedback._client
    feedback._client = SimpleNamespace(messages=Messages())
    try:
        block = {"source_block": {"text": "bron"}, "interp_block": {"text": "tolk"}}
        return asyncio.run(feedback.generate_feedback([block] * n_c2o, [0.9] * n_c2o,
                                                      [block] * n_o2c, [0.9] * n_o2c))
    finally:
        feedback._client = old


class TestNotAssessedIsVisible:
    def test_unreadable_answer_marks_the_session(self):
        result = _run_feedback("Dit is geen JSON.")
        assert result["structured_issues"] == []
        assert result["not_assessed"] == ["client_to_officer", "officer_to_client"]
        assert result["overall_feedback"].startswith("⚠ NIET BEOORDEELD")
        assert "betekent NIET dat er geen afwijkingen zijn" in result["overall_feedback"]

    def test_missing_direction_is_marked(self):
        result = _run_feedback(_fenced(C2O_BLOCK))          # the o2c block never came
        assert result["not_assessed"] == ["officer_to_client"]
        assert "AMBTENAAR→CLIËNT" in result["overall_feedback"].split("\n")[0]
        assert "Antwoorden: één afwijking." in result["overall_feedback"]

    def test_two_blocks_need_no_notice(self):
        result = _run_feedback(_fenced(C2O_BLOCK) + "\n\nAanvulling:\n\n" + _fenced(O2C_BLOCK))
        assert result["not_assessed"] == []
        assert not result["overall_feedback"].startswith("⚠")
        assert len(result["structured_issues"]) == 4

    def test_direction_without_pairs_is_not_marked(self):
        result = _run_feedback(_fenced(C2O_BLOCK), n_o2c=0)
        assert result["not_assessed"] == []
