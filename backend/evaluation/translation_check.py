"""DV2 — how much of the c2o score is Claude's translation rather than the interpreter?

The c2o (client→officer) path scores `LaBSE(claude_translation, interpreter_dutch)`.
Any error Claude makes translating the client's Turkish lands in that score
indistinguishably from an error the interpreter made. This script measures the
Claude step on its own, against hand-written Dutch reference translations.

Two signals:

  chrF / BLEU     surface overlap with the reference (sacrebleu). chrF is the
                  primary one — character-level, so it degrades gracefully on
                  Turkish morphology where BLEU on short sentences is very noisy.

  LaBSE ceiling   LaBSE(claude_translation, human_reference), computed with the
                  same `scoring.score_segments()` the pipeline uses. This is the
                  useful number: it is roughly the score a PERFECT interpreter
                  could achieve on the c2o path, because the pipeline compares
                  the interpreter against Claude's Dutch, not against the truth.
                  If it sits at 0.9, the translation hop costs ~0.1 of headroom
                  before the interpreter is even considered.

Also writes a manual-review CSV to results/ for a native Turkish/Dutch speaker to
fill in — chrF is a rough proxy and cannot tell an acceptable paraphrase from a
meaning change. That human column is the authoritative one.

    uv run python evaluation/translation_check.py

Requires ANTHROPIC_API_KEY. sacrebleu is optional (without it the review template
is still produced, just with no automatic metric).
"""
from __future__ import annotations

import asyncio
import csv

from _common import (
    DATA,
    RAN,
    RESULTS_DIR,
    CheckResult,
    env_missing,
    log,
    md_table,
    mean,
    setup_logging,
)

NAME = "translation_check"
ITEMS_CSV = DATA / "translation_pairs.csv"


def _load_items() -> list[dict]:
    with ITEMS_CSV.open(encoding="utf-8-sig", newline="") as fh:
        return [r for r in csv.DictReader(fh) if r.get("item_id")]


async def run() -> CheckResult:
    if not ITEMS_CSV.exists():
        return CheckResult.skipped(NAME, f"{ITEMS_CSV} not found")

    items = _load_items()
    if not items:
        return CheckResult.skipped(NAME, f"{ITEMS_CSV} has no rows")

    if env_missing("anthropic_api_key"):
        return CheckResult.skipped(
            NAME, "ANTHROPIC_API_KEY unset or placeholder in .env — cannot call "
                  "translate_to_dutch(). Nothing about the translation step can be "
                  "measured without it.")

    from app.config import settings
    from app.services import feedback

    log.info("[%s] items=%d model=%s", NAME, len(items), settings.llm_model)

    sources = [it["source_text"] for it in items]
    try:
        translations = await feedback.translate_to_dutch(sources, "tr")
    except Exception as exc:
        return CheckResult.failed(
            NAME, f"translate_to_dutch raised {type(exc).__name__}: {exc}")

    rows = []
    for it, hyp in zip(items, translations):
        failed = hyp.strip() == it["source_text"].strip()
        rows.append({
            "item_id": it["item_id"],
            "source": it["source_text"],
            "reference": it["reference_nl"],
            "claude": hyp,
            "failed": failed,
        })
        if failed:
            log.warning("[%s] item=%s translation returned input unchanged (silent fallback)",
                        NAME, it["item_id"])

    usable = [r for r in rows if not r["failed"]]
    if not usable:
        return CheckResult.failed(
            NAME, "every translation returned the input unchanged — translate_to_dutch's "
                  "silent fallback fired for all items (check the API key and llm_model)")

    # ── chrF / BLEU ───────────────────────────────────────────────────────────
    have_sacrebleu = True
    try:
        from sacrebleu.metrics import BLEU, CHRF
        chrf_metric, bleu_metric = CHRF(), BLEU(effective_order=True)
    except ImportError:
        have_sacrebleu = False

    if have_sacrebleu:
        for r in usable:
            r["chrf"] = chrf_metric.sentence_score(r["claude"], [r["reference"]]).score
            r["bleu"] = bleu_metric.sentence_score(r["claude"], [r["reference"]]).score
            log.info("[%s] item=%s chrf=%.1f bleu=%.1f", NAME, r["item_id"], r["chrf"], r["bleu"])

    # ── LaBSE ceiling ─────────────────────────────────────────────────────────
    labse_ok = True
    try:
        from app.services import scoring
        vals = await scoring.score_segments([r["claude"] for r in usable],
                                            [r["reference"] for r in usable])
        for r, v in zip(usable, vals):
            r["labse_vs_ref"] = float(v)
            log.info("[%s] item=%s labse_vs_reference=%.4f", NAME, r["item_id"], v)
    except Exception as exc:
        labse_ok = False
        log.error("[%s] LaBSE ceiling failed: %s: %s", NAME, type(exc).__name__, exc)

    # ── Manual-review template ────────────────────────────────────────────────
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    review_csv = RESULTS_DIR / "translation_manual_review.csv"
    with review_csv.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["item_id", "source_tr", "claude_translation_nl", "reference_nl",
                    "chrf", "labse_vs_reference",
                    "reviewer_verdict_correct_or_not", "reviewer_notes"])
        for r in rows:
            w.writerow([r["item_id"], r["source"], r["claude"], r["reference"],
                        f"{r.get('chrf', ''):.1f}" if r.get("chrf") is not None else "",
                        f"{r.get('labse_vs_ref', ''):.4f}" if r.get("labse_vs_ref") is not None else "",
                        "", ""])
    log.info("[%s] wrote manual review template -> %s", NAME, review_csv)

    # ── Report ────────────────────────────────────────────────────────────────
    md: list[str] = []
    numbers: dict = {"n_items": len(rows), "n_usable": len(usable),
                     "translation_failures": len(rows) - len(usable),
                     "llm_model": settings.llm_model}

    md.append(f"`feedback.translate_to_dutch()` on {len(items)} Turkish sentences with "
              f"hand-written Dutch references, model `{settings.llm_model}`.\n")

    cols = ["item", "chrF", "BLEU", "LaBSE vs reference"]
    md.append(md_table(
        cols,
        [[r["item_id"],
          f"{r['chrf']:.1f}" if r.get("chrf") is not None else "—",
          f"{r['bleu']:.1f}" if r.get("bleu") is not None else "—",
          f"{r['labse_vs_ref']:.3f}" if r.get("labse_vs_ref") is not None else "—"]
         for r in usable]))
    md.append("")

    if have_sacrebleu:
        chrfs = [r["chrf"] for r in usable]
        bleus = [r["bleu"] for r in usable]
        numbers["chrf_mean"] = mean(chrfs)
        numbers["chrf_min"] = min(chrfs)
        numbers["bleu_mean"] = mean(bleus)
        md.append(f"chrF mean **{mean(chrfs):.1f}** (range {min(chrfs):.1f}–{max(chrfs):.1f}), "
                  f"BLEU mean **{mean(bleus):.1f}**. chrF is on 0–100; these are single-reference "
                  f"scores on {len(usable)} short sentences, so treat them as a smoke signal, "
                  f"not a quality estimate.\n")
    else:
        md.append("⚠️  sacrebleu not installed, so no chrF/BLEU. The manual review template was "
                  "still written. Install with `uv pip install -e '.[eval]'`.\n")

    if labse_ok:
        ceils = [r["labse_vs_ref"] for r in usable]
        numbers["labse_ceiling_mean"] = mean(ceils)
        numbers["labse_ceiling_min"] = min(ceils)
        md.append(f"### The headroom this hop costs\n\n"
                  f"LaBSE(Claude's Dutch, human reference Dutch) = mean **{mean(ceils):.3f}**, "
                  f"min **{min(ceils):.3f}**, max **{max(ceils):.3f}**.\n\n"
                  f"Read this as the approximate ceiling on the c2o path: the pipeline scores the "
                  f"interpreter against Claude's Dutch, so where Claude's Dutch already differs "
                  f"from the truth, a flawless interpreter still cannot reach 1.0. "
                  f"With a mean of {mean(ceils):.3f}, roughly "
                  f"**{(1 - mean(ceils)):.3f}** of similarity is spent before the interpreter is "
                  f"assessed at all — against a `{'0.70'}` correct/incorrect threshold, that "
                  f"consumes about {(1 - mean(ceils)) / (1 - 0.70):.0%} of the margin between "
                  f"the threshold and a perfect score.\n")
        worst = min(usable, key=lambda r: r["labse_vs_ref"])
        md.append(f"Weakest item `{worst['item_id']}` ({worst['labse_vs_ref']:.3f}):\n\n"
                  f"- source (tr): {worst['source']}\n"
                  f"- Claude (nl): {worst['claude']}\n"
                  f"- reference (nl): {worst['reference']}\n")
    else:
        md.append("⚠️  The LaBSE ceiling could not be computed (see log). The chrF figures above "
                  "do not translate directly into the pipeline's score scale, so the size of the "
                  "translation hop's contribution is **unmeasured**.\n")

    md.append("### Side-by-side (for the human reviewer)\n")
    md.append(md_table(["item", "source (tr)", "Claude (nl)", "reference (nl)"],
                       [[r["item_id"], r["source"], r["claude"], r["reference"]] for r in rows]))
    md.append("")

    if numbers["translation_failures"]:
        md.append(f"⚠️  {numbers['translation_failures']} item(s) came back unchanged — "
                  f"`translate_to_dutch`'s silent fallback. Excluded from the metrics above.\n")

    md.append(f"**A human still has to read this.** chrF and LaBSE both reward surface and "
              f"embedding similarity; neither can tell an acceptable paraphrase from a changed "
              f"meaning, which is the only distinction that matters here. A fill-in template is "
              f"at `results/{review_csv.name}` — it needs a Turkish/Dutch bilingual reviewer to "
              f"complete the `reviewer_verdict` column. The Dutch references were also written "
              f"by an LLM (`human_verified=no` throughout `translation_pairs.csv`), so at present "
              f"this measures Claude against Claude and the absolute values should not be quoted "
              f"as translation quality.\n")

    return CheckResult(name=NAME, status=RAN, markdown="\n".join(md), numbers=numbers)


def _main() -> int:
    setup_logging()
    res = asyncio.run(run())
    print("\n" + "=" * 70)
    print(f"{res.name}: {res.status}" + (f" — {res.reason}" if res.reason else ""))
    print("=" * 70)
    print(res.markdown or "(no output)")
    return 0 if res.status == RAN else 1


if __name__ == "__main__":
    raise SystemExit(_main())
