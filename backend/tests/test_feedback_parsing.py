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
