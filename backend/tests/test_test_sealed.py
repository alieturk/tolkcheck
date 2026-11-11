"""Sealed test predictions and the later scoring step (evaluation/test_sealed.py), no API."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

EVAL_DIR = Path(__file__).resolve().parent.parent / "evaluation"
sys.path.insert(0, str(EVAL_DIR))

import test_sealed as ts  # noqa: E402
from metrics import Row, choose_threshold, counts  # noqa: E402
from sessions import load_session  # noqa: E402

from tests.test_session_lint import v4_session  # noqa: E402


def load(number: int, split: str, mutate=None):
    data = v4_session(number)
    data["split"] = split
    if mutate:
        mutate(data)
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp, f"S{number}.json")
        path.write_text(json.dumps(data), encoding="utf-8")
        return load_session(path)


def issue(severity: str, kind: str = "omission") -> dict:
    return {"type": kind, "severity": severity, "description": "x"}


def sealed_predictions(sessions, flag_a, flag_b, labse):
    """Predictions as predict() writes them, with chosen flags and scores per pair."""
    return [{"pair_id": p.pair_id, "session_id": p.session_id, "direction": p.direction,
             "text_hash": ts.text_hash(p), "labse": labse(p),
             "issues_A": [issue("high")] if flag_a(p) else [],
             "issues_B": [issue("high")] if flag_b(p) else []}
            for s in sessions for p in s.pairs]


class TestTextHash(unittest.TestCase):
    def test_changes_with_text_not_with_labels(self):
        a = load(30, "test")
        b = load(30, "test", lambda d: d["pairs"][0].update(label="controle_parafrase", severity="none", expected_flag=False, reference_rendering=None))
        c = load(30, "test", lambda d: d["pairs"][0]["rendering"].update(text="iets anders"))
        self.assertEqual(ts.text_hash(a.pairs[0]), ts.text_hash(b.pairs[0]))
        self.assertNotEqual(ts.text_hash(a.pairs[0]), ts.text_hash(c.pairs[0]))


class TestIssuesPerPairId(unittest.TestCase):
    def test_maps_direction_and_index_to_pair_ids(self):
        s = load(30, "test")
        structured = [{"pair_index": 1, "direction": "officer_to_client", "issues": [issue("high")]},
                      {"pair_index": 0, "direction": "client_to_officer", "issues": []}]
        got = ts.issues_per_pair_id(s, structured)
        self.assertEqual(got["S30-P03"][0]["severity"], "high")   # second question
        self.assertEqual(got["S30-P02"], [])                       # first answer
        self.assertIsNone(got["S30-P01"])                          # not in the answer
        self.assertEqual(len(got), 8)


class TestComputeMetrics(unittest.TestCase):
    def setUp(self):
        self.dev = [load(n, "dev") for n in (20, 21)]
        self.test = [load(n, "test") for n in (30, 31, 32)]
        # dev: deviations score 0.5, controls 0.9 → C threshold separates them
        self.dev_scores = {p.pair_id: (0.5 if not p.is_control else 0.9) for s in self.dev for p in s.pairs}

    def test_perfect_predictions(self):
        preds = sealed_predictions(self.test, lambda p: not p.is_control, lambda p: False,
                                   lambda p: 0.5 if not p.is_control else 0.9)
        r = ts.compute_metrics(self.test, self.dev, preds, self.dev_scores, n_boot=50)
        self.assertEqual(r["excluded_pairs"], {})
        c = r["variants"]["C"]
        self.assertTrue(0.5 < c["threshold"] <= 0.9)
        self.assertEqual(c["numbers"]["all"]["recall"], 1.0)
        self.assertEqual(c["numbers"]["all"]["fpr"], 0.0)
        a = r["variants"]["A"]["high_critical"]["numbers"]["all"]
        self.assertEqual((a["recall"], a["fpr"]), (1.0, 0.0))
        b = r["variants"]["B"]["high_critical"]["numbers"]["all"]
        self.assertEqual(b["recall"], 0.0)

    def test_threshold_is_chosen_on_dev_not_on_test(self):
        preds = sealed_predictions(self.test, lambda p: False, lambda p: False, lambda p: 0.2)
        r = ts.compute_metrics(self.test, self.dev, preds, self.dev_scores, n_boot=50)
        dev_rows = [Row(p.session_id, p.category, self.dev_scores[p.pair_id]) for s in self.dev for p in s.pairs]
        self.assertEqual(r["variants"]["C"]["threshold"], choose_threshold(dev_rows, "recall_at_fpr", max_fpr=0.10))
        self.assertEqual(r["variants"]["C"]["numbers"]["all"]["fpr"], 1.0)   # every test pair below it

    def test_reviewed_labels_are_used(self):
        # the reviewer turns a deviation into a control; the sealed prediction still flags it
        flagged = {p.pair_id for s in self.test for p in s.pairs if not p.is_control}
        preds = sealed_predictions(self.test, lambda p: p.pair_id in flagged, lambda p: False, lambda p: 0.9)
        target = next(p for p in self.test[0].pairs if not p.is_control)
        idx = int(target.pair_id.split("-P")[1]) - 1
        reviewed = [load(30, "test", lambda d: d["pairs"][idx].update(
            label="controle_parafrase", subtype=None, severity="none", expected_flag=False,
            reference_rendering=None))] + self.test[1:]
        r = ts.compute_metrics(reviewed, self.dev, preds, self.dev_scores, n_boot=50)
        a = r["variants"]["A"]["high_critical"]["numbers"]["all"]
        self.assertEqual(a["fp"], 1)

    def test_changed_text_is_excluded(self):
        preds = sealed_predictions(self.test, lambda p: False, lambda p: False, lambda p: 0.9)
        changed = [load(30, "test", lambda d: d["pairs"][2]["rendering"].update(text="nieuw"))] + self.test[1:]
        r = ts.compute_metrics(changed, self.dev, preds, self.dev_scores, n_boot=50)
        self.assertEqual(r["excluded_pairs"], {"S30-P03": "tekst gewijzigd sinds verzegeling"})
        self.assertEqual(r["n_test_pairs"], 23)

    def test_missing_answer_counts_as_not_flagged(self):
        preds = sealed_predictions(self.test, lambda p: True, lambda p: True, lambda p: 0.9)
        for p in preds:
            p["issues_A"] = None
        r = ts.compute_metrics(self.test, self.dev, preds, self.dev_scores, n_boot=50)
        self.assertEqual(r["variants"]["A"]["pairs_without_answer"], 24)
        self.assertEqual(r["variants"]["A"]["high_critical"]["numbers"]["all"]["tp"], 0)

    def test_false_negative_and_any_issue_rule(self):
        preds = sealed_predictions(self.test, lambda p: False, lambda p: False, lambda p: 0.9)
        for p in preds:
            p["issues_A"] = [issue("critical", "false-negative"), issue("low")]
        r = ts.compute_metrics(self.test, self.dev, preds, self.dev_scores, n_boot=50)
        self.assertEqual(r["variants"]["A"]["high_critical"]["numbers"]["all"]["tp"], 0)
        k = r["variants"]["A"]["any_issue"]["numbers"]["all"]
        self.assertEqual(k["tp"] + k["fp"], 24)


class TestGuards(unittest.TestCase):
    def test_flag_encoding_matches_metrics(self):
        rows = [Row("S", "omissie", ts.ftc.FLAGGED_SCORE), Row("S", None, ts.ftc.NOT_FLAGGED_SCORE)]
        k = counts(rows, ts.ftc.THRESHOLD)
        self.assertEqual((k.tp, k.fp), (1, 0))



class TestTwoRuns(unittest.TestCase):
    def setUp(self):
        self.test = [load(n, "test") for n in (30, 31)]

    def test_identical_runs_are_fully_stable(self):
        preds = sealed_predictions(self.test, lambda p: not p.is_control, lambda p: False, lambda p: 0.8)
        st = ts.stability(preds, json.loads(json.dumps(preds)), threshold=0.85)
        for key, v in st.items():
            self.assertEqual((v["n"], v["share"], v["differ"]), (16, 1.0, []), key)
        self.assertEqual(set(st), {"C", "A:high_critical", "A:any_issue", "B:high_critical", "B:any_issue"})

    def test_differences_are_counted_per_variant(self):
        run1 = sealed_predictions(self.test, lambda p: True, lambda p: False, lambda p: 0.8)
        run2 = json.loads(json.dumps(run1))
        run2[0]["issues_A"] = []                       # A changes its mind on one pair
        run2[1]["issues_B"] = [issue("medium")]        # B: only below the primary rule
        st = ts.stability(run1, run2, threshold=0.85)
        self.assertEqual(st["A:high_critical"]["same"], 15)
        self.assertEqual(st["A:high_critical"]["differ"], [run1[0]["pair_id"]])
        self.assertEqual(st["B:high_critical"]["share"], 1.0)
        self.assertEqual(st["B:any_issue"]["same"], 15)
        self.assertEqual(st["C"]["share"], 1.0)

    def test_only_kept_pairs_with_the_same_text_count(self):
        run1 = sealed_predictions(self.test, lambda p: True, lambda p: True, lambda p: 0.8)
        run2 = json.loads(json.dumps(run1))
        run2[2]["text_hash"] = "anders"
        st = ts.stability(run1, run2, threshold=0.85, pair_ids={p["pair_id"] for p in run1[:5]})
        self.assertEqual(st["C"]["n"], 4)

    def test_run_dirs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self.assertRaises(SystemExit):
                ts.run_dirs(root)
            (root / "run1").mkdir()
            (root / "run1" / "manifest.json").write_text("{}", encoding="utf-8")
            self.assertEqual(ts.run_dirs(root), (root / "run1", None))
            (root / "run2").mkdir()
            (root / "run2" / "manifest.json").write_text("{}", encoding="utf-8")
            self.assertEqual(ts.run_dirs(root), (root / "run1", root / "run2"))
            self.assertEqual(ts.run_dirs(root / "run2"), (root / "run2", None))   # a single run folder

    def test_primary_run_is_fixed(self):
        self.assertEqual((ts.PRIMARY_RUN, ts.STABILITY_RUN), ("run1", "run2"))


if __name__ == "__main__":
    unittest.main()
