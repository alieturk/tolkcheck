"""Detection metrics for DV4 — standard library only, so they are unit-tested.

A pair is *flagged* when its similarity score is BELOW the threshold (a low
LaBSE score is the deviation signal). Each scored pair is a ``Row``: its
session, its category (``None`` for a negative control) and its score.

What can and cannot be reported per category
--------------------------------------------
The detector emits one score and no category, so a false alarm lands on a
control pair, which has no category. Recall is therefore reported per category;
the false-alarm rate (FPR) and precision only for the whole set. Precision also
depends on how many pairs deviate, which in a synthetic set is chosen by the
author; ``precision_at_prevalence`` recomputes it for a realistic share of
deviating pairs from recall and FPR (Davis & Goadrich, 2006).

Intervals
---------
``wilson`` gives the 95% Wilson score interval for a proportion, which behaves
at small n and at 0 or 1 where the normal approximation does not. Pairs from one
session share voices and topic and are not independent, so ``session_bootstrap``
resamples whole sessions; report that interval when the two differ.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import Iterable, Sequence

Z95 = 1.959963984540054


@dataclass(frozen=True)
class Row:
    session_id: str
    category: str | None   # None = negative control
    score: float

    @property
    def deviant(self) -> bool:
        return self.category is not None


def wilson(k: int, n: int, z: float = Z95) -> tuple[float, float]:
    """95% Wilson score interval for k successes out of n. (nan, nan) when n == 0."""
    if n == 0:
        return (math.nan, math.nan)
    if not 0 <= k <= n:
        raise ValueError(f"k={k} outside 0..n={n}")
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


def flagged(score: float, threshold: float) -> bool:
    return score < threshold


@dataclass(frozen=True)
class Counts:
    tp: int
    fn: int
    fp: int
    tn: int

    @property
    def recall(self) -> float:
        n = self.tp + self.fn
        return self.tp / n if n else math.nan

    @property
    def fpr(self) -> float:
        n = self.fp + self.tn
        return self.fp / n if n else math.nan

    @property
    def precision(self) -> float:
        n = self.tp + self.fp
        return self.tp / n if n else math.nan

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        if math.isnan(p) or math.isnan(r) or p + r == 0:
            return 0.0
        return 2 * p * r / (p + r)


def counts(rows: Iterable[Row], threshold: float, category: str | None = None) -> Counts:
    """Confusion counts. With ``category`` set, positives are only that category
    (other categories are left out, controls stay in as negatives)."""
    tp = fn = fp = tn = 0
    for r in rows:
        if r.deviant:
            if category is not None and r.category != category:
                continue
            if flagged(r.score, threshold):
                tp += 1
            else:
                fn += 1
        else:
            if flagged(r.score, threshold):
                fp += 1
            else:
                tn += 1
    return Counts(tp, fn, fp, tn)


def candidate_thresholds(scores: Sequence[float]) -> list[float]:
    """Midpoints between consecutive distinct scores, plus one above the max and
    one below the min, so every distinct way of splitting the set is tried once."""
    uniq = sorted(set(scores))
    if not uniq:
        return []
    mids = [(a + b) / 2 for a, b in zip(uniq, uniq[1:])]
    return [uniq[0] - 1e-6] + mids + [uniq[-1] + 1e-6]


def choose_threshold(rows: Sequence[Row], criterion: str = "f1") -> float:
    """Pick the flag threshold on (dev) rows.

    ``f1``      maximise F1 over deviations vs controls
    ``youden``  maximise recall - FPR (insensitive to the share of deviations)
    ``recall:X``  lowest threshold whose recall is at least X (fewest flags that
                still catch that share), e.g. ``recall:0.8``

    Ties go to the lower threshold, i.e. fewer flags shown to the officer.
    """
    if not any(r.deviant for r in rows) or all(r.deviant for r in rows):
        raise ValueError("need both deviant and control rows to choose a threshold")
    cands = candidate_thresholds([r.score for r in rows])
    if criterion.startswith("recall:"):
        target = float(criterion.split(":", 1)[1])
        ok = [t for t in cands if counts(rows, t).recall >= target]
        if not ok:
            raise ValueError(f"no threshold reaches recall {target}")
        return min(ok)
    if criterion == "f1":
        key = lambda t: counts(rows, t).f1  # noqa: E731
    elif criterion == "youden":
        key = lambda t: counts(rows, t).recall - counts(rows, t).fpr  # noqa: E731
    else:
        raise ValueError(f"unknown criterion {criterion!r}")
    best = max(key(t) for t in cands)
    return min(t for t in cands if key(t) == best)


def precision_at_prevalence(recall: float, fpr: float, prevalence: float) -> float:
    """Precision if `prevalence` of all pairs deviated, given recall and FPR."""
    num = recall * prevalence
    den = num + fpr * (1 - prevalence)
    return num / den if den else math.nan


def _metrics(rows: Sequence[Row], threshold: float, categories: Sequence[str]) -> dict[str, float]:
    out: dict[str, float] = {}
    for c in categories:
        out[f"recall:{c}"] = counts(rows, threshold, c).recall
    total = counts(rows, threshold)
    out["recall:all"] = total.recall
    out["fpr"] = total.fpr
    out["precision"] = total.precision
    return out


def session_bootstrap(
    rows: Sequence[Row],
    threshold: float,
    categories: Sequence[str],
    n_boot: int = 2000,
    seed: int = 20261107,
) -> dict[str, tuple[float, float]]:
    """Percentile 95% intervals from resampling whole sessions with replacement.
    A metric that is undefined in a resample (e.g. no pair of that category drawn)
    is skipped for that resample; the interval is (nan, nan) if it never exists."""
    by_session: dict[str, list[Row]] = {}
    for r in rows:
        by_session.setdefault(r.session_id, []).append(r)
    ids = sorted(by_session)
    if not ids:
        return {}
    rng = random.Random(seed)
    samples: dict[str, list[float]] = {}
    for _ in range(n_boot):
        draw = [r for sid in rng.choices(ids, k=len(ids)) for r in by_session[sid]]
        for key, val in _metrics(draw, threshold, categories).items():
            if not math.isnan(val):
                samples.setdefault(key, []).append(val)
    keys = list(_metrics(rows, threshold, categories))
    out: dict[str, tuple[float, float]] = {}
    for key in keys:
        vals = sorted(samples.get(key, []))
        if not vals:
            out[key] = (math.nan, math.nan)
            continue
        lo = vals[int(0.025 * (len(vals) - 1))]
        hi = vals[int(math.ceil(0.975 * (len(vals) - 1)))]
        out[key] = (lo, hi)
    return out
