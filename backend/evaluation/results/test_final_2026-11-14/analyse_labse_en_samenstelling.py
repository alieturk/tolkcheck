"""Extra analysis next to test_sealed.py score (2026-11-14), descriptive only.

Run from backend/:
    uv run python evaluation/results/test_final_2026-11-14/analyse_labse_en_samenstelling.py

* composition of dev and test after review (pairs, deviations per category,
  controls per label, left-out pairs)
* LaBSE on test: ROC-AUC per category (deviations of the category against all
  controls; low score = deviant) from the SEALED run1 scores, and the score drop
  LaBSE(source, reference) − LaBSE(source, rendering) per category. The reference
  scores are computed now (LaBSE is deterministic); the rendering scores are the
  sealed ones.
* not_assessed / parse problems in the sealed raw answers of A and B, run1 and run2.

Writes labse_analyse.json and labse_analyse.md next to this file. Chooses nothing,
changes no prediction.
"""
import asyncio
import json
import sys
from collections import Counter
from pathlib import Path

BACKEND = Path.cwd()
sys.path.insert(0, str(BACKEND / "evaluation"))

from _common import neutralise_broken_torchcodec, setup_logging  # noqa: E402
from sessions import CATEGORIES, load_sessions  # noqa: E402

OUT = Path(__file__).resolve().parent
SESSIONS = BACKEND.parent / "eval" / "data" / "tolkcheck_dv4" / "sessions_v4"
SEALED = BACKEND / "evaluation" / "results" / "test_sealed_2026-11-11"


def auc_low_is_deviant(dev, ctrl):
    if not dev or not ctrl:
        return None
    return sum((d < c) + 0.5 * (d == c) for d in dev for c in ctrl) / (len(dev) * len(ctrl))


def composition(sessions):
    pairs = [p for s in sessions for p in s.pairs]
    kept = [p for p in pairs if not p.excluded]
    return {
        "sessies": len(sessions),
        "paren": len(pairs),
        "weggelaten": {p.pair_id: p.excluded_reason for p in pairs if p.excluded},
        "afwijkingen_per_categorie": dict(Counter(p.category for p in kept if not p.is_control)),
        "afwijkingen_totaal": sum(not p.is_control for p in kept),
        "controles_per_label": dict(Counter(p.label for p in kept if p.is_control)),
        "controles_totaal": sum(p.is_control for p in kept),
        "gecorrigeerd": sum(1 for s in sessions for p in json.loads(s.path.read_text(encoding="utf-8"))["pairs"]
                            if "label_origineel" in p),
    }


async def main() -> None:
    setup_logging()
    neutralise_broken_torchcodec()
    from app.services import scoring

    sessions = load_sessions(SESSIONS)
    dev = [s for s in sessions if s.split == "dev"]
    test = [s for s in sessions if s.split == "test"]
    sealed = {p["pair_id"]: p for p in json.loads((SEALED / "run1" / "predictions.json").read_text(encoding="utf-8"))}

    kept = [p for s in test for p in s.pairs if not p.excluded]
    ctrl = [sealed[p.pair_id]["labse"] for p in kept if p.is_control]
    auc = {}
    for c in CATEGORIES:
        d = [sealed[p.pair_id]["labse"] for p in kept if p.category == c]
        auc[c] = {"auc": auc_low_is_deviant(d, ctrl), "n_dev": len(d), "n_controls": len(ctrl)}
    alld = [sealed[p.pair_id]["labse"] for p in kept if not p.is_control]
    auc["alle_afwijkingen"] = {"auc": auc_low_is_deviant(alld, ctrl), "n_dev": len(alld), "n_controls": len(ctrl)}

    with_ref = [p for p in kept if not p.is_control and p.reference_text]
    ref_scores = await scoring.score_segments([p.source_text for p in with_ref], [p.reference_text for p in with_ref])
    drop = {}
    for c in CATEGORIES:
        d = [float(r) - sealed[p.pair_id]["labse"] for p, r in zip(with_ref, ref_scores) if p.category == c]
        drop[c] = {"n": len(d), "gemiddeld": sum(d) / len(d) if d else None,
                   "min": min(d) if d else None, "max": max(d) if d else None}

    means = {}
    for p in kept:
        means.setdefault(p.label if p.is_control else "afwijking (alle)", []).append(sealed[p.pair_id]["labse"])
    means = {k: {"n": len(v), "gemiddeld": sum(v) / len(v)} for k, v in sorted(means.items())}

    parse = {}
    for run in ("run1", "run2"):
        manifest = json.loads((SEALED / run / "manifest.json").read_text(encoding="utf-8"))
        for v in ("A", "B"):
            not_assessed = {}
            for raw in sorted((SEALED / run / f"raw_{v}").glob("S*.json")):
                na = json.loads(raw.read_text(encoding="utf-8"))["parsed"].get("not_assessed") or []
                if na:
                    not_assessed[raw.stem] = na
            parse[f"{run}:{v}"] = {"paren_zonder_antwoord": manifest["variants"][v]["pairs_without_answer"],
                                   "stop_reasons": manifest["variants"][v]["stop_reasons"],
                                   "sessies_met_not_assessed": not_assessed}

    result = {"samenstelling": {"dev": composition(dev), "test": composition(test)},
              "test_roc_auc_per_categorie": auc, "test_scoredaling_per_categorie": drop,
              "test_gemiddelde_labse_per_label": means, "parse_en_not_assessed": parse}
    (OUT / "labse_analyse.json").write_text(json.dumps(result, indent=1, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(result, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
