"""Dev set (S20–S29) after review, 2026-11-14: LaBSE variants and analysis.

Run from backend/:
    uv run python evaluation/results/dev_na_review_2026-11-14/dev_na_review.py <dev-only sessions dir>

* C: threshold chosen on the reviewed dev pairs with metrics.choose_threshold
  (recall_at_fpr, max FPR 0.10, as TESTOPZET.md), reported on the same pairs
  (in-sample, so optimistic) with detection_check.run.
* LaBSE_0.70: fixed threshold 0.70, the cut-off in variant A's rules (not variant A).
* ROC-AUC per category, mean LaBSE score per label, score drop per category.
Pairs the reviewer left out are skipped (detection_check does that itself).
Variants A and B are added by feedback_text_check.py --add-to.
"""
import asyncio
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path.cwd() / "evaluation"))

import detection_check as dc  # noqa: E402
from _common import neutralise_broken_torchcodec, setup_logging  # noqa: E402
from metrics import Row, choose_threshold, counts  # noqa: E402
from sessions import CATEGORIES, load_sessions  # noqa: E402

OUT = Path(__file__).resolve().parent
CRITERION, MAX_FPR = "recall_at_fpr", 0.10


def auc_low_is_deviant(dev, ctrl):
    if not dev or not ctrl:
        return None
    return sum((d < c) + 0.5 * (d == c) for d in dev for c in ctrl) / (len(dev) * len(ctrl))


def clean(x):
    if isinstance(x, float) and math.isnan(x):
        return None
    if isinstance(x, dict):
        return {k: clean(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [clean(v) for v in x]
    return x


async def main(dev_dir: Path) -> None:
    setup_logging()
    neutralise_broken_torchcodec()
    sessions = load_sessions(dev_dir)
    assert {s.split for s in sessions} == {"dev"}, "map bevat niet alleen dev"
    assert all(s.reviewed for s in sessions), "niet alle sessies gereviewd"
    pairs = [p for s in sessions for p in s.pairs if not p.excluded]
    scores = dict(zip([p.pair_id for p in pairs], await dc._score(pairs, "cross_lingual")))
    rows = [Row(p.session_id, p.category, scores[p.pair_id]) for p in pairs if scores[p.pair_id] is not None]
    thr = choose_threshold(rows, CRITERION, max_fpr=MAX_FPR)
    k = counts(rows, thr)
    print(f"drempel C: {thr:.4f} · recall {k.recall:.3f} · FPR {k.fpr:.3f} · {len(rows)} paren")

    variants = {}
    for name, threshold in (("C", thr), ("LaBSE_0.70", 0.70)):
        res = await dc.run(path="cross_lingual", threshold=threshold, dry_run=True, sessions_dir=dev_dir)
        assert res.status == dc.RAN, res.reason
        md = res.markdown
        if name == "C":
            md = md.replace("vooraf opgegeven, niet afgesteld",
                            f"gekozen op deze gereviewde dev-paren ({CRITERION}, max FPR {MAX_FPR}), in-sample") \
                   .replace("met een vooraf opgegeven drempel. Er is geen drempel gekozen en er zijn geen testsessies bekeken.",
                            f"met een drempel die op dezelfde dev-paren is gekozen ({CRITERION}). Er zijn geen testsessies bekeken.")
        n = res.numbers
        variants[name] = {"threshold": threshold, "markdown": md,
                          "numbers": {x: v for x, v in n.items() if x not in ("scores", "reference_scores")},
                          "pair_scores": n["scores"], "reference_scores": n["reference_scores"]}
        if name == "C":
            variants[name].update(criterion=CRITERION, max_fpr=MAX_FPR)
        else:
            variants[name]["note"] = "vaste drempel 0,70 uit de drempelregels van variant A; NIET variant A zelf"

    ctrl = [scores[p.pair_id] for p in pairs if p.is_control]
    auc = {c: {"auc": auc_low_is_deviant([scores[p.pair_id] for p in pairs if p.category == c], ctrl)}
           for c in CATEGORIES}
    auc["alle_afwijkingen"] = {"auc": auc_low_is_deviant([scores[p.pair_id] for p in pairs if not p.is_control], ctrl)}
    means = {}
    for p in pairs:
        means.setdefault(p.label if p.is_control else "afwijking (alle)", []).append(scores[p.pair_id])
    means = {lab: {"n": len(v), "gemiddeld": sum(v) / len(v)} for lab, v in sorted(means.items())}
    ref = variants["C"]["reference_scores"]
    drop = {}
    for c in CATEGORIES:
        d = [ref[p.pair_id] - scores[p.pair_id] for p in pairs if p.category == c and p.pair_id in ref]
        drop[c] = {"n": len(d), "gemiddeld": sum(d) / len(d) if d else None,
                   "min": min(d) if d else None, "max": max(d) if d else None}

    data = {"status": "dev na review (gereviewde labels); in-sample voor C",
            "date": "2026-11-14", "sessions": [s.session_id for s in sessions],
            "reviewed_by": sorted({s.reviewed_by for s in sessions}),
            "excluded_by_reviewer": {p.pair_id: p.excluded_reason for s in sessions for p in s.pairs if p.excluded},
            "variants": variants,
            "labse_analysis": {"roc_auc_per_category": auc, "mean_score_per_label": means,
                               "score_drop_per_category": drop}}
    (OUT / "dev_na_review.json").write_text(json.dumps(clean(data), indent=1, ensure_ascii=False, default=str),
                                            encoding="utf-8")
    md = ["# DV4 dev S20–S29 na review (2026-11-14)\n",
          f"Gereviewd door {', '.join(data['reviewed_by'])}. Weggelaten: "
          + (", ".join(f"{k} ({v})" for k, v in data["excluded_by_reviewer"].items()) or "geen") + ".\n"]
    for name, v in variants.items():
        md += [f"\n## {name} — drempel {v['threshold']:.3f}\n", v["markdown"]]
    (OUT / "dev_na_review.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print(json.dumps(clean(data["labse_analysis"]), indent=1, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main(Path(sys.argv[1])))
