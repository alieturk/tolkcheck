"""Unit tests for the DV4 detection metrics and the session loader.

evaluation/ is not collected by pytest (see pytest.ini), but metrics.py and
sessions.py are standard-library only and decide every number in the DV4 table,
so they are tested here. detection_check.py itself needs LaBSE and is not.
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import pytest

EVAL_DIR = Path(__file__).resolve().parent.parent / "evaluation"
sys.path.insert(0, str(EVAL_DIR))

from metrics import (  # noqa: E402
    Row,
    choose_threshold,
    counts,
    precision_at_prevalence,
    session_bootstrap,
    wilson,
)
from sessions import SessionFormatError, load_session  # noqa: E402


class TestWilson:
    def test_known_value(self):
        lo, hi = wilson(7, 10)
        assert lo == pytest.approx(0.3968, abs=1e-3)
        assert hi == pytest.approx(0.8922, abs=1e-3)

    def test_bounds_at_zero_and_n(self):
        assert wilson(0, 20)[0] == 0.0
        assert wilson(20, 20)[1] == 1.0
        assert wilson(0, 20)[1] > 0      # unlike the normal approximation

    def test_empty(self):
        assert all(math.isnan(x) for x in wilson(0, 0))

    def test_rejects_k_above_n(self):
        with pytest.raises(ValueError):
            wilson(3, 2)


def _rows():
    # session A: two deviations, one control; session B: one deviation, two controls
    return [
        Row("A", "omissie", 0.40),
        Row("A", "toevoeging", 0.62),
        Row("A", None, 0.91),
        Row("B", "omissie", 0.85),   # a miss at any sensible threshold
        Row("B", None, 0.88),
        Row("B", None, 0.60),        # a false alarm at threshold 0.70
    ]


class TestCounts:
    def test_flag_means_below_threshold(self):
        c = counts(_rows(), 0.70)
        assert (c.tp, c.fn, c.fp, c.tn) == (2, 1, 1, 2)
        assert c.recall == pytest.approx(2 / 3)
        assert c.fpr == pytest.approx(1 / 3)
        assert c.precision == pytest.approx(2 / 3)

    def test_score_equal_to_threshold_is_not_flagged(self):
        assert counts([Row("A", "omissie", 0.70)], 0.70).tp == 0

    def test_per_category_keeps_controls_as_negatives(self):
        c = counts(_rows(), 0.70, "omissie")
        assert (c.tp, c.fn, c.fp, c.tn) == (1, 1, 1, 2)

    def test_undefined_when_no_positives(self):
        assert math.isnan(counts([Row("A", None, 0.9)], 0.7).recall)


class TestChooseThreshold:
    def test_f1_separates_a_separable_set(self):
        rows = [Row("A", "omissie", 0.3), Row("A", "omissie", 0.4),
                Row("A", None, 0.8), Row("A", None, 0.9)]
        t = choose_threshold(rows, "f1")
        assert 0.4 < t <= 0.8
        assert counts(rows, t).f1 == 1.0
        assert t == pytest.approx(0.6)        # lowest of the tied best: fewest flags

    def test_recall_target(self):
        t = choose_threshold(_rows(), "recall:1.0")
        assert counts(_rows(), t).recall == 1.0
        assert t == pytest.approx((0.85 + 0.88) / 2)

    def test_needs_both_classes(self):
        with pytest.raises(ValueError):
            choose_threshold([Row("A", "omissie", 0.3)], "f1")

    def test_unknown_criterion(self):
        with pytest.raises(ValueError):
            choose_threshold(_rows(), "accuracy")


def test_precision_at_prevalence():
    assert precision_at_prevalence(0.8, 0.1, 0.1) == pytest.approx(0.08 / 0.17)
    # with no false alarms precision is 1 whatever the prevalence
    assert precision_at_prevalence(0.5, 0.0, 0.05) == pytest.approx(1.0)


class TestSessionBootstrap:
    def test_deterministic_and_contains_estimate(self):
        rows = _rows() * 3
        rows = [Row(f"{r.session_id}{i // 6}", r.category, r.score) for i, r in enumerate(rows)]
        a = session_bootstrap(rows, 0.70, ["omissie", "toevoeging"], n_boot=300, seed=1)
        b = session_bootstrap(rows, 0.70, ["omissie", "toevoeging"], n_boot=300, seed=1)
        assert a == b
        lo, hi = a["recall:all"]
        assert lo <= counts(rows, 0.70).recall <= hi

    def test_absent_category_is_nan(self):
        out = session_bootstrap(_rows(), 0.70, ["entiteitsfout"], n_boot=50)
        assert all(math.isnan(x) for x in out["recall:entiteitsfout"])


# ── session loader ────────────────────────────────────────────────────────────

S12 = EVAL_DIR / "data" / "sessions" / "S12.json"


def _write(tmp_path: Path, data: dict) -> Path:
    p = tmp_path / "s.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


def _minimal(**pair_overrides) -> dict:
    pair = {
        "pair_id": "X-P01", "order": 1, "direction": "tr->nl",
        "source": {"lang": "tr", "text": "Bir."}, "rendering": {"lang": "nl", "text": "Een."},
        "label": "omissie", "expected_flag": True,
    }
    pair.update(pair_overrides)
    return {"session_id": "X", "split": "dev", "reviewed": True, "pairs": [pair]}


class TestLoader:
    def test_s12_example(self):
        s = load_session(S12)
        assert s.session_id == "S12" and s.split == "draft" and not s.reviewed
        assert [p.category for p in s.pairs] == [None, "omissie", "toevoeging", "register_en_nadruk"]
        assert s.pairs[0].is_control
        assert any("different voices" in w for w in s.warnings)

    def test_unknown_label_is_rejected(self, tmp_path):
        with pytest.raises(SessionFormatError, match="unknown label"):
            load_session(_write(tmp_path, _minimal(label="omission")))

    def test_control_cannot_expect_a_flag(self, tmp_path):
        with pytest.raises(SessionFormatError, match="control pair"):
            load_session(_write(tmp_path, _minimal(label="controle_correct", expected_flag=True)))

    def test_language_must_match_direction(self, tmp_path):
        with pytest.raises(SessionFormatError, match="do not match"):
            load_session(_write(tmp_path, _minimal(direction="nl->tr")))

    def test_bad_split(self, tmp_path):
        data = _minimal()
        data["split"] = "train"
        with pytest.raises(SessionFormatError, match="split"):
            load_session(_write(tmp_path, data))

    def test_deviation_without_expected_flag_becomes_control_with_warning(self, tmp_path):
        s = load_session(_write(tmp_path, _minimal(expected_flag=False)))
        assert s.pairs[0].is_control
        assert s.warnings
