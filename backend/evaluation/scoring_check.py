"""DV2/DV4 — does LaBSE actually separate correct renderings from deviant ones?

Runs the REAL `scoring.score_segments()` (no mocks — every existing test under
tests/ mocks `_score_sync`) over the labelled pairs in data/pairs.csv, down both
scoring paths that pipeline.py uses:

  path A  "cross_lingual"     scoring.score_segments(source, interpreter)
                              Direct cross-lingual LaBSE. This is the o2c path.

  path B  "pseudo_reference"  feedback.translate_to_dutch(non-Dutch side)
                              then score_segments(dutch, dutch)
                              Claude pseudo-reference + monolingual LaBSE. This is
                              the c2o path — the legally decisive direction.

For a tr2nl pair the translated side is the SOURCE, which is exactly what
`resume_scoring` does. For an nl2tr pair the source is already Dutch, so the
INTERPRETER side is translated instead — the structural mirror (get both sides
into Dutch, then compare monolingually). The `translated_side` column records
which, per pair, so no row is ambiguous.

Answers three questions the literature cannot:
  (a) do known-correct pairs score meaningfully higher than known-deviant ones?
  (b) do the two paths give different distributions for the same deviation?
  (c) would feedback.py's current 0.70 / 0.65 / 0.50 cut-offs classify these
      labelled examples correctly?

    uv run python evaluation/scoring_check.py
    uv run python evaluation/scoring_check.py --paths cross_lingual   # skip Claude

Path B needs ANTHROPIC_API_KEY. Without it, path B is skipped and said so —
never faked.
"""
from __future__ import annotations

import argparse
import asyncio
import csv

from _common import (
    DATA,
    RAN,
    CheckResult,
    env_missing,
    log,
    md_table,
    mean,
    setup_logging,
)

NAME = "scoring_check"
PAIRS_CSV = DATA / "pairs.csv"

# ── feedback.py's thresholds, mirrored ────────────────────────────────────────
# These live inside feedback._SYSTEM_PROMPT as prose, so they cannot be imported.
# _assert_thresholds_in_sync() below fails loudly if the prompt is edited without
# updating these — otherwise this script would silently grade against stale numbers.
T_CORRECT = 0.70        # >= 0.70 -> "vertaling is semantisch correct"
T_LIKELY_ISSUE = 0.50   # <  0.50 -> "waarschijnlijk een vertaalprobleem"
T_NO_ADDITION = 0.65    # >= 0.65 -> LLM told to NEVER flag as "addition"

CORRECT = "correct"
POSSIBLE = "possible issue"
LIKELY = "likely issue"


def _assert_thresholds_in_sync() -> str | None:
    """Return a warning string if feedback._SYSTEM_PROMPT no longer contains these numbers."""
    from app.services.feedback import _SYSTEM_PROMPT

    missing = [f"{t:.2f}" for t in (T_CORRECT, T_LIKELY_ISSUE, T_NO_ADDITION)
               if f"{t:.2f}" not in _SYSTEM_PROMPT]
    if missing:
        return (f"Threshold drift: {', '.join(missing)} no longer appear in "
                f"feedback._SYSTEM_PROMPT. The classification columns below are graded "
                f"against scoring_check.py's constants, which may now be stale.")
    return None


def _classify(score: float) -> str:
    if score >= T_CORRECT:
        return CORRECT
    if score >= T_LIKELY_ISSUE:
        return POSSIBLE
    return LIKELY


def _load_pairs() -> list[dict]:
    with PAIRS_CSV.open(encoding="utf-8-sig", newline="") as fh:
        return [r for r in csv.DictReader(fh) if r.get("pair_id")]


async def _path_cross_lingual(pairs: list[dict]) -> list[float]:
    """Direct cross-lingual LaBSE, one batched call as production does."""
    from app.services import scoring

    sources = [p["source_text"] for p in pairs]
    targets = [p["interpreter_text"] for p in pairs]
    return await scoring.score_segments(sources, targets)


async def _path_pseudo_reference(pairs: list[dict]) -> tuple[list[float | None], list[dict]]:
    """Translate the non-Dutch side to Dutch with Claude, then score Dutch-Dutch."""
    from app.services import feedback, scoring

    # Which side needs translating, per pair.
    for p in pairs:
        if p["source_lang"] != "nl":
            p["_translate_side"] = "source"
            p["_to_translate"] = p["source_text"]
            p["_other_side"] = p["interpreter_text"]
            p["_src_lang"] = p["source_lang"]
        else:
            p["_translate_side"] = "interpreter"
            p["_to_translate"] = p["interpreter_text"]
            p["_other_side"] = p["source_text"]
            p["_src_lang"] = p["target_lang"]

    # Batch per source language — translate_to_dutch takes one language per call,
    # matching how resume_scoring calls it (all c2o texts of one session at once).
    by_lang: dict[str, list[dict]] = {}
    for p in pairs:
        by_lang.setdefault(p["_src_lang"], []).append(p)

    details: list[dict] = []
    for lang, group in by_lang.items():
        texts = [p["_to_translate"] for p in group]
        log.info("[%s] translate  lang=%s count=%d", NAME, lang, len(texts))
        translated = await feedback.translate_to_dutch(texts, lang)
        for p, orig, dutch in zip(group, texts, translated):
            # translate_to_dutch falls back to returning the input verbatim when the
            # API call or JSON parse fails. Identical output for a non-Dutch input
            # therefore means "no translation happened", which must not be scored as
            # if it had.
            p["_dutch"] = dutch
            p["_translation_failed"] = (dutch.strip() == orig.strip())

    scored: list[float | None] = []
    ok = [p for p in pairs if not p["_translation_failed"]]
    if ok:
        a = [p["_dutch"] if p["_translate_side"] == "source" else p["_other_side"] for p in ok]
        b = [p["_other_side"] if p["_translate_side"] == "source" else p["_dutch"] for p in ok]
        vals = await scoring.score_segments(a, b)
        it = iter(vals)
        for p in pairs:
            scored.append(None if p["_translation_failed"] else next(it))
    else:
        scored = [None] * len(pairs)

    for p, s in zip(pairs, scored):
        details.append({
            "pair_id": p["pair_id"],
            "translated_side": p["_translate_side"],
            "translation": p.get("_dutch", ""),
            "failed": p["_translation_failed"],
            "score": s,
        })
        if s is not None:
            log.info("[%s] pseudo_ref  pair=%s side=%s score=%.4f  %r",
                     NAME, p["pair_id"], p["_translate_side"], s,
                     p.get("_dutch", "")[:60].replace("\n", " "))
    return scored, details


def _separation_block(rows: list[dict], path: str) -> tuple[str, dict]:
    """Correct-vs-deviant separation for one path."""
    corr = [r[path] for r in rows if r["is_correct"] and r[path] is not None]
    dev = [r[path] for r in rows if not r["is_correct"] and r[path] is not None]
    if not corr or not dev:
        return f"Not enough scored pairs on `{path}` to compute separation.\n", {}

    min_c, max_d = min(corr), max(dev)
    gap = min_c - max_d
    stats = {
        "n_correct": len(corr), "n_deviant": len(dev),
        "mean_correct": mean(corr), "mean_deviant": mean(dev),
        "min_correct": min_c, "max_correct": max(corr),
        "min_deviant": min(dev), "max_deviant": max_d,
        "margin": gap, "separable": gap > 0,
        "delta_means": mean(corr) - mean(dev),
    }
    md = md_table(
        ["group", "n", "mean", "min", "max"],
        [["known-correct", len(corr), mean(corr), min(corr), max(corr)],
         ["known-deviant", len(dev), mean(dev), min(dev), max(dev)]])
    if gap > 0:
        md += (f"\n\nThe two groups **do not overlap** on this path: the lowest correct pair "
               f"({min_c:.3f}) scores above the highest deviant pair ({max_d:.3f}), a margin of "
               f"{gap:.3f}. Some threshold in that band separates these 20 pairs perfectly — "
               f"though on n={len(corr)}+{len(dev)} hand-written pairs that is an existence "
               f"proof, not a calibration.\n")
    else:
        md += (f"\n\nThe two groups **overlap**: the highest deviant pair ({max_d:.3f}) scores "
               f"at or above the lowest correct pair ({min_c:.3f}), an overlap of {-gap:.3f}. "
               f"No single cut-off on this path can separate correct from deviant without "
               f"error — which bounds what DV4 threshold calibration can achieve and means "
               f"the score cannot be the sole signal.\n")
    return md, stats


async def run(paths: list[str] | None = None) -> CheckResult:
    paths = paths or ["cross_lingual", "pseudo_reference"]

    if not PAIRS_CSV.exists():
        return CheckResult.skipped(NAME, f"{PAIRS_CSV} not found")

    pairs = _load_pairs()
    if not pairs:
        return CheckResult.skipped(NAME, f"{PAIRS_CSV} has no rows")

    drift = _assert_thresholds_in_sync()
    if drift:
        log.warning("[%s] %s", NAME, drift)

    skip_reason_b = None
    if "pseudo_reference" in paths and env_missing("anthropic_api_key"):
        skip_reason_b = "ANTHROPIC_API_KEY unset or placeholder in .env"
        paths = [p for p in paths if p != "pseudo_reference"]

    log.info("[%s] pairs=%d paths=%s thresholds=%.2f/%.2f/%.2f",
             NAME, len(pairs), ",".join(paths), T_CORRECT, T_NO_ADDITION, T_LIKELY_ISSUE)

    rows: list[dict] = [{
        "pair_id": p["pair_id"],
        "direction": p["direction"],
        "category": p["category"],
        "is_correct": p["category"] == "correct",
        "source_text": p["source_text"],
        "interpreter_text": p["interpreter_text"],
        "error_note": p.get("error_note", ""),
        "cross_lingual": None,
        "pseudo_reference": None,
    } for p in pairs]

    if "cross_lingual" in paths:
        try:
            vals = await _path_cross_lingual(pairs)
        except Exception as exc:
            return CheckResult.failed(
                NAME, f"cross-lingual scoring raised {type(exc).__name__}: {exc}")
        for r, v in zip(rows, vals):
            r["cross_lingual"] = float(v)
            log.info("[%s] cross_lingual  pair=%s cat=%-22s score=%.4f",
                     NAME, r["pair_id"], r["category"], v)

    translation_details: list[dict] = []
    if "pseudo_reference" in paths:
        try:
            vals, translation_details = await _path_pseudo_reference(pairs)
            for r, v in zip(rows, vals):
                r["pseudo_reference"] = None if v is None else float(v)
        except Exception as exc:
            log.error("[%s] pseudo_reference path raised %s: %s", NAME, type(exc).__name__, exc)
            skip_reason_b = f"{type(exc).__name__}: {exc}"

    active = [p for p in ("cross_lingual", "pseudo_reference")
              if any(r[p] is not None for r in rows)]
    if not active:
        return CheckResult.failed(NAME, "no path produced any score")

    # ── Report ────────────────────────────────────────────────────────────────
    md: list[str] = []
    numbers: dict = {"thresholds": {"correct": T_CORRECT, "no_addition": T_NO_ADDITION,
                                    "likely_issue": T_LIKELY_ISSUE},
                     "n_pairs": len(rows), "paths_run": active}

    if drift:
        md.append(f"⚠️  {drift}\n")
    if skip_reason_b:
        md.append(f"⚠️  **Path B (pseudo_reference) was not run:** {skip_reason_b}. "
                  f"Everything below about the c2o path is therefore unmeasured — the "
                  f"cross-lingual figures are path A only.\n")

    md.append(f"Real LaBSE (`scoring.score_segments`, no mocks) over {len(rows)} hand-written "
              f"labelled pairs. Higher = more similar. Bucket column applies feedback.py's "
              f"cut-offs: ≥{T_CORRECT:.2f} `{CORRECT}`, ≥{T_LIKELY_ISSUE:.2f} `{POSSIBLE}`, "
              f"below that `{LIKELY}`.\n")

    # Per-pair table
    headers = ["pair", "dir", "category", *active, *(f"bucket ({p})" for p in active)]
    md.append(md_table(headers, [
        [r["pair_id"], r["direction"], r["category"],
         *("—" if r[p] is None else f"{r[p]:.3f}" for p in active),
         *("—" if r[p] is None else _classify(r[p]) for p in active)]
        for r in rows]))
    md.append("")

    # (a) separation
    md.append("### (a) Do correct pairs score higher than deviant ones?\n")
    for p in active:
        md.append(f"**path `{p}`**\n")
        block, stats = _separation_block(rows, p)
        md.append(block)
        numbers.setdefault("separation", {})[p] = stats

    # per-category means
    md.append("### Score by error category\n")
    cats = sorted({r["category"] for r in rows})
    cat_rows = []
    for cat in cats:
        sub = [r for r in rows if r["category"] == cat]
        row = [cat, len(sub)]
        for p in active:
            vals = [r[p] for r in sub if r[p] is not None]
            row += [f"{mean(vals):.3f}" if vals else "—",
                    f"{min(vals):.3f}–{max(vals):.3f}" if vals else "—"]
        cat_rows.append(row)
    md.append(md_table(["category", "n", *(x for p in active for x in (f"mean ({p})", f"range ({p})"))],
                       cat_rows))
    md.append("")
    numbers["by_category"] = {
        cat: {p: mean([r[p] for r in rows if r["category"] == cat and r[p] is not None])
              for p in active}
        for cat in cats}

    # (b) path comparison
    md.append("### (b) Do the two paths behave differently on the same pair?\n")
    if len(active) < 2:
        md.append("Only one path ran, so no comparison is possible. This question is "
                  "**unanswered**.\n")
    else:
        both = [r for r in rows if r["cross_lingual"] is not None and r["pseudo_reference"] is not None]
        if not both:
            md.append("No pair has a score on both paths.\n")
        else:
            deltas = [r["pseudo_reference"] - r["cross_lingual"] for r in both]
            md.append(md_table(
                ["pair", "category", "cross_lingual", "pseudo_reference", "Δ (B−A)", "bucket changed?"],
                [[r["pair_id"], r["category"], f"{r['cross_lingual']:.3f}",
                  f"{r['pseudo_reference']:.3f}",
                  f"{r['pseudo_reference'] - r['cross_lingual']:+.3f}",
                  "yes → " + _classify(r["pseudo_reference"])
                  if _classify(r["cross_lingual"]) != _classify(r["pseudo_reference"]) else "no"]
                 for r in both]))
            flips = [r for r in both
                     if _classify(r["cross_lingual"]) != _classify(r["pseudo_reference"])]
            md.append(f"\nMean shift going through Claude: **{mean(deltas):+.3f}** "
                      f"(range {min(deltas):+.3f} to {max(deltas):+.3f}). "
                      f"The bucket changed on **{len(flips)}/{len(both)}** pairs"
                      + (": " + ", ".join(f"`{r['pair_id']}`" for r in flips) if flips else "")
                      + ".\n")
            c_shift = mean([r["pseudo_reference"] - r["cross_lingual"] for r in both if r["is_correct"]])
            d_shift = mean([r["pseudo_reference"] - r["cross_lingual"] for r in both if not r["is_correct"]])
            md.append(f"Broken out: correct pairs shift **{c_shift:+.3f}**, deviant pairs shift "
                      f"**{d_shift:+.3f}**. The pseudo-reference hop only helps if it lifts "
                      f"correct pairs more than deviant ones — i.e. if the first number is "
                      f"clearly larger than the second, widening the margin.\n")

            # State the conclusion rather than leaving it to be inferred. "Path B
            # scores higher" is the obvious misreading here, and it points the wrong
            # way: a uniform lift of both groups moves no decision. What matters is
            # only whether the GAP between correct and deviant grew.
            sep_a = numbers.get("separation", {}).get("cross_lingual", {})
            sep_b = numbers.get("separation", {}).get("pseudo_reference", {})
            if sep_a and sep_b:
                gap_a = sep_a["delta_means"]
                gap_b = sep_b["delta_means"]
                md.append(f"Correct-minus-deviant gap: **{gap_a:.3f}** on `cross_lingual` vs "
                          f"**{gap_b:.3f}** on `pseudo_reference` "
                          f"(change {gap_b - gap_a:+.3f}).\n")
                if gap_b - gap_a > 0.02:
                    md.append("**On this sample the Claude hop does widen the gap**, which is "
                              "the evidence the c2o design needs. Weigh it against the extra "
                              "API dependency, the cost, and the translation error it folds in "
                              "(see `translation_check`).\n")
                elif gap_b - gap_a < -0.02:
                    md.append("**On this sample the Claude hop NARROWS the gap** — it makes "
                              "correct and deviant pairs harder to tell apart, not easier. That "
                              "argues against the c2o design: drop the translation hop and score "
                              "c2o cross-lingually like o2c.\n")
                else:
                    md.append("**On this sample the Claude hop does not meaningfully change the "
                              "gap** (within ±0.02). It raises correct and deviant scores by "
                              "about the same amount, so it shifts the whole distribution "
                              "upward without improving discrimination — and a uniform shift "
                              "changes no decision that a re-tuned threshold could not achieve "
                              "without it. This does **not** support the hypothesis in "
                              "`pipeline.resume_scoring`'s docstring that routing c2o through "
                              "Dutch buys accuracy. Since the hop also adds an API dependency, "
                              "latency, cost, and a second error source on the legally decisive "
                              "direction, the burden of proof is on keeping it. Note the caveat: "
                              f"n={sep_a['n_correct']}+{sep_a['n_deviant']} unvalidated pairs, "
                              "so this is a strong hint to test properly, not a settled result.\n")
            numbers["path_delta"] = {"mean": mean(deltas), "correct": c_shift, "deviant": d_shift,
                                     "bucket_flips": len(flips), "n": len(both)}

    # (c) threshold behaviour
    md.append("### (c) Would the current thresholds classify these pairs correctly?\n")
    for p in active:
        scored = [r for r in rows if r[p] is not None]
        fn = [r for r in scored if not r["is_correct"] and _classify(r[p]) == CORRECT]
        fp = [r for r in scored if r["is_correct"] and _classify(r[p]) != CORRECT]
        flagged_dev = [r for r in scored if not r["is_correct"] and _classify(r[p]) != CORRECT]
        n_dev = sum(1 for r in scored if not r["is_correct"])
        n_corr = sum(1 for r in scored if r["is_correct"])

        recall = len(flagged_dev) / n_dev if n_dev else 0.0
        precision = (len(flagged_dev) / (len(flagged_dev) + len(fp))
                     if (len(flagged_dev) + len(fp)) else 0.0)

        md.append(f"**path `{p}`** — treating \"not `{CORRECT}`\" as *flagged*:\n")
        md.append(md_table(
            ["metric", "value"],
            [["deviant pairs flagged (recall)", f"{len(flagged_dev)}/{n_dev} = {recall:.1%}"],
             ["correct pairs wrongly flagged", f"{len(fp)}/{n_corr}"],
             ["precision of flags", f"{precision:.1%}"],
             [f"**false negatives** (deviant scored ≥{T_CORRECT:.2f})", f"{len(fn)}/{n_dev}"]]))
        md.append("")
        if fn:
            md.append("False negatives — real errors this threshold calls semantically correct. "
                      "These are the dangerous ones: the officer is told the rendering is fine.\n")
            for r in fn:
                md.append(f"- `{r['pair_id']}` ({r['category']}, {r[p]:.3f}) — {r['error_note']}  \n"
                          f"  source: {r['source_text']}  \n"
                          f"  interpreter: {r['interpreter_text']}")
            md.append("")
        else:
            md.append(f"No false negatives: every deviant pair scored below {T_CORRECT:.2f}.\n")

        # The ≥0.65 addition rule is a separate, harder guarantee of silence.
        adds = [r for r in scored if r["category"] == "toevoeging"]
        muted = [r for r in adds if r[p] >= T_NO_ADDITION]
        if adds:
            md.append(f"**The `≥{T_NO_ADDITION:.2f}` never-flag-addition rule.** feedback.py's prompt "
                      f"says *\"Markeer NOOIT een vertaling als 'addition' als de score "
                      f"≥ {T_NO_ADDITION:.2f}\"*. Of {len(adds)} labelled `toevoeging` pairs, "
                      f"**{len(muted)}** score at or above that line"
                      + (" — " + ", ".join(f"`{r['pair_id']}` ({r[p]:.3f})" for r in muted)
                         if muted else "")
                      + ". Any pair in that set cannot be reported as an addition no matter what "
                        "the LLM observes, so this rule is a hard ceiling on toevoeging recall, "
                        "independent of the 0.70 bucket.\n")
            numbers.setdefault("addition_rule", {})[p] = {
                "n_toevoeging": len(adds), "muted": len(muted),
                "muted_ids": [r["pair_id"] for r in muted]}

        numbers.setdefault("threshold_eval", {})[p] = {
            "recall": recall, "precision": precision,
            "false_negatives": len(fn), "false_negative_ids": [r["pair_id"] for r in fn],
            "false_positives": len(fp), "false_positive_ids": [r["pair_id"] for r in fp],
            "n_deviant": n_dev, "n_correct": n_corr,
        }

    # ── (d) what separates the caught from the missed ─────────────────────────
    # If the flagged deviations are the ones that changed how MUCH text there is,
    # while the missed ones changed what the text MEANS at constant length, then the
    # score is closer to a length/content-volume detector than a semantic one — which
    # would explain why the categories fail so unevenly and bound what any threshold
    # can do. Length ratio is a crude proxy but it is the obvious confound to check.
    md.append("### (d) What distinguishes the deviations it catches from the ones it misses?\n")
    for p in active:
        dev = [r for r in rows if not r["is_correct"] and r[p] is not None]
        if not dev:
            continue
        for r in dev:
            sw = len(r["source_text"].split())
            iw = len(r["interpreter_text"].split())
            r["_len_ratio"] = iw / sw if sw else 0.0
            r["_len_delta"] = abs(iw - sw)

        flagged = [r for r in dev if _classify(r[p]) != CORRECT]
        missed = [r for r in dev if _classify(r[p]) == CORRECT]

        md.append(f"**path `{p}`**\n")
        md.append(md_table(
            ["pair", "category", "score", "flagged?", "src words", "interp words", "length ratio"],
            [[r["pair_id"], r["category"], f"{r[p]:.3f}",
              "yes" if _classify(r[p]) != CORRECT else "**no**",
              len(r["source_text"].split()), len(r["interpreter_text"].split()),
              f"{r['_len_ratio']:.2f}"]
             for r in sorted(dev, key=lambda r: r[p])]))
        md.append("")

        if flagged and missed:
            f_dev = mean(r["_len_delta"] for r in flagged)
            m_dev = mean(r["_len_delta"] for r in missed)
            md.append(
                f"Mean absolute word-count difference between source and rendering: "
                f"**{f_dev:.1f}** words for the {len(flagged)} deviation(s) the threshold "
                f"catches, **{m_dev:.1f}** for the {len(missed)} it misses.\n")
            if f_dev > m_dev * 1.5:
                md.append(
                    "The caught deviations are the ones that changed how *much* was said; the "
                    "missed ones changed what was said while keeping the length similar. On this "
                    "sample the score behaves more like a content-volume detector than a "
                    "semantic one. That is consistent with the per-category pattern above — "
                    "wholesale omissions and additions are visible, whereas a flipped negation, "
                    "a swapped date, or a hedge removed all preserve length and survive. It also "
                    "bounds DV4: no threshold on this signal can catch a same-length meaning "
                    "reversal, so threshold calibration alone cannot fix these categories — they "
                    "need a different signal (targeted negation/entity/modality checks) or they "
                    "have to be declared out of scope.\n")
            else:
                md.append(
                    "Length change does not obviously explain which deviations are caught on "
                    "this sample, so the failures are not simply a content-volume artefact.\n")
        numbers.setdefault("length_confound", {})[p] = {
            "mean_len_delta_flagged": mean(r["_len_delta"] for r in flagged) if flagged else None,
            "mean_len_delta_missed": mean(r["_len_delta"] for r in missed) if missed else None,
            "flagged_ids": [r["pair_id"] for r in flagged],
            "missed_ids": [r["pair_id"] for r in missed],
        }

    if translation_details:
        md.append("### Claude translations used on path B\n")
        md.append("Shown so translation error can be told apart from interpreter error — if a "
                  "row's Dutch is wrong, that pair's path-B score says nothing about the "
                  "interpreter. `translation_check.py` quantifies this separately.\n")
        md.append(md_table(["pair", "side translated", "Claude Dutch", "failed?"],
                           [[d["pair_id"], d["translated_side"], d["translation"],
                             "yes" if d["failed"] else "no"] for d in translation_details]))
        md.append("")
        nfail = sum(1 for d in translation_details if d["failed"])
        if nfail:
            md.append(f"⚠️  {nfail} translation(s) returned the input unchanged, meaning "
                      f"`translate_to_dutch` hit its silent fallback. Those pairs are excluded "
                      f"from path B rather than scored as if translated.\n")
        numbers["translation_failures"] = nfail

    md.append(f"\n**Pair provenance.** All {len(rows)} pairs were written by hand for this "
              f"evaluation and every row in `pairs.csv` carries `human_verified=no`. They were "
              f"authored by an LLM (Claude) against the five error categories named in the "
              f"report, NOT validated by a native Turkish speaker. Category labels and the "
              f"naturalness of the Turkish are both unverified. Until a native speaker signs "
              f"off, treat the direction of these results as informative and the exact "
              f"numbers as provisional.\n")

    return CheckResult(name=NAME, status=RAN, markdown="\n".join(md), numbers=numbers)


def _main() -> int:
    setup_logging()
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--paths", default="cross_lingual,pseudo_reference",
                    help="comma-separated: cross_lingual,pseudo_reference")
    args = ap.parse_args()

    res = asyncio.run(run([p.strip() for p in args.paths.split(",") if p.strip()]))
    print("\n" + "=" * 70)
    print(f"{res.name}: {res.status}" + (f" — {res.reason}" if res.reason else ""))
    print("=" * 70)
    print(res.markdown or "(no output)")
    return 0 if res.status == RAN else 1


if __name__ == "__main__":
    raise SystemExit(_main())
