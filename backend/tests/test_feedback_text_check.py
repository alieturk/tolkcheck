"""Parsing the feedback step's answer into per-pair flags (evaluation/feedback_text_check.py)."""
from __future__ import annotations

import asyncio
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

EVAL_DIR = Path(__file__).resolve().parent.parent / "evaluation"
sys.path.insert(0, str(EVAL_DIR))

import feedback_text_check as ftc  # noqa: E402
from metrics import counts  # noqa: E402
from sessions import load_session  # noqa: E402

from tests.test_session_lint import v4_session  # noqa: E402


def session(number: int = 20):
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp, f"S{number}.json")
        path.write_text(json.dumps(v4_session(number)), encoding="utf-8")
        return load_session(path)


def issue(severity: str, kind: str = "omission") -> dict:
    return {"type": kind, "severity": severity, "description": "x"}


class TestIsFlagged(unittest.TestCase):
    def test_high_and_critical_flag_under_the_primary_rule(self):
        self.assertTrue(ftc.is_flagged([issue("critical")]))
        self.assertTrue(ftc.is_flagged([issue("high")]))
        self.assertFalse(ftc.is_flagged([issue("medium")]))
        self.assertFalse(ftc.is_flagged([issue("low")]))
        self.assertFalse(ftc.is_flagged([]))

    def test_any_issue_rule(self):
        self.assertTrue(ftc.is_flagged([issue("low")], "any_issue"))
        self.assertTrue(ftc.is_flagged([issue("medium")], "any_issue"))

    def test_false_negative_never_flags(self):
        self.assertFalse(ftc.is_flagged([issue("critical", "false-negative")]))
        self.assertFalse(ftc.is_flagged([issue("high", "false-negative")], "any_issue"))
        self.assertTrue(ftc.is_flagged([issue("low", "false-negative"), issue("high")]))

    def test_severity_case_is_ignored(self):
        self.assertTrue(ftc.is_flagged([issue("High")]))


class TestIssuesByPair(unittest.TestCase):
    def test_keys_like_the_ui(self):
        structured = [
            {"pair_index": 0, "direction": "client_to_officer", "issues": [issue("high")]},
            {"pair_index": 1, "direction": "officer_to_client", "issues": []},
            {"pair_index": "2", "issues": [issue("low")]},          # direction missing → c2o, index as text
            {"pair_index": None, "direction": "client_to_officer", "issues": [issue("high")]},
            "rommel",
        ]
        got = ftc.issues_by_pair(structured)
        self.assertEqual(set(got), {("client_to_officer", 0), ("officer_to_client", 1), ("client_to_officer", 2)})
        self.assertEqual(got[("client_to_officer", 2)][0]["severity"], "low")

    def test_empty_or_missing(self):
        self.assertEqual(ftc.issues_by_pair(None), {})
        self.assertEqual(ftc.issues_by_pair([]), {})


class TestAssignFlags(unittest.TestCase):
    def setUp(self):
        self.s = session(20)
        self.o2c, self.c2o = ftc.session_layout(self.s.pairs)

    def test_layout_follows_direction_and_order(self):
        self.assertEqual([p.direction for p in self.o2c], ["nl->tr"] * 4)
        self.assertEqual([p.direction for p in self.c2o], ["tr->nl"] * 4)
        self.assertEqual([p.pair_id for p in self.o2c], ["S20-P01", "S20-P03", "S20-P05", "S20-P07"])
        self.assertEqual([p.pair_id for p in self.c2o], ["S20-P02", "S20-P04", "S20-P06", "S20-P08"])

    def test_issues_go_back_to_the_right_pair(self):
        structured = [
            {"pair_index": 1, "direction": "officer_to_client", "issues": [issue("critical")]},   # P03
            {"pair_index": 0, "direction": "client_to_officer", "issues": [issue("medium")]},     # P02
        ] + [{"pair_index": i, "direction": d, "issues": []}
             for d, idx in (("officer_to_client", (0, 2, 3)), ("client_to_officer", (1, 2, 3))) for i in idx]
        results = {r.pair_id: r for r in ftc.assign_flags(self.s.pairs, {}, structured)}
        self.assertEqual(list(results), [p.pair_id for p in self.s.pairs])     # session order kept
        self.assertTrue(results["S20-P03"].flags["high_critical"])
        self.assertFalse(results["S20-P02"].flags["high_critical"])
        self.assertTrue(results["S20-P02"].flags["any_issue"])
        self.assertFalse(results["S20-P01"].flags["any_issue"])
        self.assertTrue(all(r.issues is not None for r in results.values()))

    def test_pair_left_out_by_the_model_is_not_flagged_and_marked(self):
        results = {r.pair_id: r for r in ftc.assign_flags(self.s.pairs, {}, [])}
        self.assertTrue(all(r.issues is None for r in results.values()))
        self.assertFalse(any(r.flags["any_issue"] for r in results.values()))


class TestRows(unittest.TestCase):
    def test_flags_become_rows_that_metrics_count(self):
        s = session(20)
        structured = [{"pair_index": i, "direction": "officer_to_client", "issues": [issue("high")]}
                      for i in range(4)]                          # flag every question
        results = ftc.assign_flags(s.pairs, {}, structured)
        k = counts(ftc.rows_for(results, "high_critical"), ftc.THRESHOLD)
        questions = [p for p in s.pairs if p.direction == "nl->tr"]
        self.assertEqual(k.tp, sum(1 for p in questions if not p.is_control))
        self.assertEqual(k.fp, sum(1 for p in questions if p.is_control))
        self.assertEqual(k.tp + k.fn, sum(1 for p in s.pairs if not p.is_control))


class TestRecordingClient(unittest.TestCase):
    def test_records_text_usage_and_temperature(self):
        message = SimpleNamespace(
            model="claude-sonnet-4-6", stop_reason="end_turn",
            content=[SimpleNamespace(type="text", text='{"pairs": []}')],
            usage=SimpleNamespace(input_tokens=10, output_tokens=5, cache_creation_input_tokens=0,
                                  cache_read_input_tokens=3))

        class Inner:
            async def create(self, **kwargs):
                return message

        client = ftc.RecordingClient(SimpleNamespace(messages=Inner()))
        got = asyncio.run(client.messages.create(model="m", temperature=0.0, messages=[]))
        self.assertIs(got, message)
        self.assertEqual(client.calls[0]["text"], '{"pairs": []}')
        self.assertEqual(client.calls[0]["usage"]["cache_read_input_tokens"], 3)
        self.assertEqual(client.calls[0]["temperature"], 0.0)



class TestLeftOutPairs(unittest.TestCase):
    def test_skipped_pairs_are_not_counted(self):
        s = session(20)
        structured = [{"pair_index": i, "direction": d, "issues": [issue("high")]}
                      for d in ("officer_to_client", "client_to_officer") for i in range(4)]
        results = ftc.assign_flags(s.pairs, {}, structured)
        all_rows = ftc.rows_for(results, "high_critical")
        left = ftc.rows_for(results, "high_critical", {"S20-P01", "S20-P02"})
        self.assertEqual((len(all_rows), len(left)), (8, 6))


if __name__ == "__main__":
    unittest.main()
