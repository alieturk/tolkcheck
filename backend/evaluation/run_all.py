"""Run every DV2 evaluation whose prerequisites are met and write one report.

    uv run python evaluation/run_all.py
    uv run python evaluation/run_all.py --only scoring,translation
    uv run python evaluation/run_all.py --models large-v3

Writes `evaluation/results/YYYY-MM-DD-report.md` containing: what ran, what was
skipped and why, every number produced, and a limitations section.

The report is SOURCE MATERIAL for DV2's "D) afweging" and the DV2/DV4
"Gaten"/"beperkingen" paragraphs — deliberately not written as report prose.
Numbers here come from actual runs; a check that cannot run says so rather than
producing a plausible-looking figure.
"""
from __future__ import annotations

import argparse
import asyncio
import datetime as _dt
import json
import platform
import subprocess
import sys

from _common import (
    FAILED,
    RAN,
    RESULTS_DIR,
    SKIPPED,
    CheckResult,
    log,
    md_table,
    setup_logging,
)

CHECKS = {
    "wer": "wer_check",
    "diarization": "diarization_check",
    "scoring": "scoring_check",
    "translation": "translation_check",
}


def _provenance() -> dict:
    from app.config import settings

    def ver(mod: str) -> str:
        try:
            import importlib.metadata as md
            return md.version(mod)
        except Exception:
            return "not installed"

    try:
        commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                                capture_output=True, text=True, timeout=10).stdout.strip()
        dirty = subprocess.run(["git", "status", "--porcelain"],
                               capture_output=True, text=True, timeout=10).stdout.strip()
    except Exception:
        commit, dirty = "unknown", ""

    return {
        "timestamp": _dt.datetime.now().isoformat(timespec="seconds"),
        "git_commit": commit + (" (working tree dirty)" if dirty else ""),
        "python": sys.version.split()[0],
        "platform": f"{platform.system()} {platform.release()} ({platform.machine()})",
        "whisper_model_config_default": settings.whisper_model,
        "whisper_device": settings.whisper_device,
        "whisper_compute_type": settings.whisper_compute_type,
        "llm_model": settings.llm_model,
        "versions": {m: ver(m) for m in (
            "faster-whisper", "pyannote.audio", "pyannote.metrics",
            "sentence-transformers", "torch", "anthropic", "jiwer", "sacrebleu")},
    }


LIMITATIONS = """\
Read these before quoting any number above.

1. **The audio is synthetic (TTS), not human speech.** All clips and the
   3-speaker session were generated with Microsoft Edge neural TTS
   (`evaluation/make_fixtures.py`). No accents beyond the voice's own, no
   disfluencies, no false starts, no room acoustics, no background noise, no
   telephone-bandwidth limiting. Whisper and TTS are both centred on clean read
   speech, so this specifically flatters the transcription step. **Every WER and
   DER figure here is a floor — a best case — not an estimate of what happens in
   an IND hearing room.**

2. **Sample size is far too small for a calibration claim.** 8 audio clips
   (~84 s of speech), 1 diarization session (~38 s), 20 text pairs, 10
   translation items. These numbers can show that an effect exists and roughly
   how large it is. They cannot establish a threshold, a precision/recall
   operating point, or a confidence interval. Anything DV4 concludes about
   thresholds needs an order of magnitude more labelled data.

3. **One session, one speaker configuration.** The diarization figure comes from
   a single synthetic session with one deliberate 1.2 s overlap. Real hearings
   have frequent overlap, interruptions, back-channelling ("hm", "ja"), and long
   silences. DER on one clean session says nothing about variance across
   sessions.

4. **No native-speaker validation.** The Turkish source text, the Dutch
   translations, and the error-category labels in `data/pairs.csv` and
   `data/translation_pairs.csv` were all authored by an LLM (Claude). Every row
   carries `human_verified=no`. Consequences: the Turkish may be unidiomatic in
   ways that depress LaBSE scores independently of the labelled error; a pair
   labelled `betekenisverschuiving` may not be one; and in
   `translation_check.py` Claude is being scored against Claude-written
   references, so its absolute values are not translation quality.

5. **The deviant pairs are constructed, not observed.** They were written to
   instantiate the five error categories cleanly. Real interpreter errors are
   subtler, often partial, and frequently co-occur — an omission plus a hedge
   shift in the same utterance. Clean single-error pairs make the detection task
   easier than the real one.

6. **The diarization ground truth is exact by construction, not annotated.**
   Segment boundaries are the offsets the clips were placed at, so DER carries no
   annotator error — better than hand labelling in that one respect, but the
   flip side is that TTS voices separate far more easily than real speakers who
   share an accent or pitch range.

7. **The interpreter's Dutch is spoken by a Turkish voice.** edge-tts voices are
   locale-bound and none covers both languages, so the interpreter's Dutch turns
   are Turkish-accented. Speaker identity stays consistent (which is what
   diarization keys on), but this was a constraint, not a design decision.

8. **WER needed a normalisation choice.** Whisper renders small cardinals as
   digits or words unpredictably. WER is reported on normalised text (lowercase,
   punctuation stripped, small number words digitised) with a `WER raw` column
   showing the unnormalised figure. The normaliser's number map is hand-written
   and covers only the fixtures — see `_common.py`.

9. **Nothing here measures the end-to-end system.** Each check isolates one
   stage against clean input. In production the stages compose: a diarization
   swap feeds the wrong text to scoring, and a transcription error is
   indistinguishable at the scoring stage from an interpreter error. The
   compounded error rate is **not measured** and will be worse than any single
   figure here suggests.
"""

HUMAN_NEEDED = """\
- **A Turkish/Dutch bilingual reviewer**, for two jobs: validate the source text
  and category labels in `data/pairs.csv` (flip `human_verified` to `yes` per
  row), and fill the `reviewer_verdict` column in
  `results/translation_manual_review.csv`. Until then every figure derived from
  that data is provisional. This is the single biggest gap.
- **Real hearing audio**, or failing that human volunteers reading the existing
  scripts. This is what would turn the WER and DER floors into usable estimates.
  Real IND audio needs a legal basis and an AVG/DPIA route (DV5 territory), so
  human-volunteer recordings are the realistic near-term step.
- **More labelled pairs, ideally drawn from observed interpreting**, before DV4
  calibrates any threshold. Constructed pairs cannot establish an operating point.
- **A decision on the c2o asymmetry** once `scoring_check.py`'s two paths have
  been read: keep the Claude pseudo-reference hop, or drop it and score c2o
  cross-lingually like o2c. The docstring on `pipeline.resume_scoring` states the
  hypothesis; this report is the evidence for settling it.
"""


async def _run_one(key: str, models: list[str] | None) -> CheckResult:
    mod_name = CHECKS[key]
    log.info("")
    log.info("=" * 70)
    log.info("[run_all] starting %s", mod_name)
    log.info("=" * 70)
    try:
        mod = __import__(mod_name)
    except Exception as exc:
        return CheckResult.failed(mod_name, f"could not import: {type(exc).__name__}: {exc}")

    try:
        if key == "wer":
            return await mod.run(models)
        return await mod.run()
    except Exception as exc:
        import traceback
        log.error(traceback.format_exc())
        return CheckResult.failed(mod_name, f"{type(exc).__name__}: {exc}")


async def main(only: list[str], models: list[str] | None) -> int:
    setup_logging()
    prov = _provenance()
    log.info("[run_all] commit=%s python=%s platform=%s",
             prov["git_commit"], prov["python"], prov["platform"])

    results: list[CheckResult] = []
    for key in only:
        results.append(await _run_one(key, models))

    ran = [r for r in results if r.status == RAN]
    skipped = [r for r in results if r.status == SKIPPED]
    failed = [r for r in results if r.status == FAILED]

    # ── Assemble the report ───────────────────────────────────────────────────
    today = _dt.date.today().isoformat()
    md: list[str] = []
    md.append(f"# DV2 evaluation report — {today}")
    md.append("")
    md.append("Generated by `evaluation/run_all.py`. Every number below comes from an actual "
              "run against the fixtures in `evaluation/data/`. Checks whose prerequisites were "
              "missing are listed as skipped with the reason — no figure is estimated, "
              "extrapolated, or filled in by hand anywhere in this file.")
    md.append("")
    md.append("**Purpose.** Source material for DV2's *D) afweging* section and the DV2/DV4 "
              "*Gaten* / *beperkingen* paragraphs. It is deliberately not written as report "
              "prose. Read §Known limitations before quoting anything.")
    md.append("")

    md.append("## Summary")
    md.append("")
    md.append(md_table(["check", "status", "headline"],
                       [[r.name, r.status, _headline(r)] for r in results]))
    md.append("")
    md.append(f"{len(ran)} ran, {len(skipped)} skipped, {len(failed)} failed.")
    md.append("")

    if skipped or failed:
        md.append("### Not run")
        md.append("")
        for r in skipped + failed:
            md.append(f"- **{r.name}** ({r.status}): {r.reason}")
        md.append("")

    md.append("## Environment")
    md.append("")
    md.append(md_table(["key", "value"],
                       [[k, v] for k, v in prov.items() if k != "versions"]))
    md.append("")
    md.append(md_table(["package", "version"], [[k, v] for k, v in prov["versions"].items()]))
    md.append("")

    for r in results:
        md.append(f"## {r.name}")
        md.append("")
        if r.status != RAN:
            md.append(f"**{r.status.upper()}** — {r.reason}")
            md.append("")
            continue
        md.append(r.markdown)
        md.append("")

    md.append("## Known limitations of this evaluation")
    md.append("")
    md.append(LIMITATIONS)
    md.append("")
    md.append("## What still needs a human")
    md.append("")
    md.append(HUMAN_NEEDED)
    md.append("")

    md.append("## Raw numbers (JSON)")
    md.append("")
    md.append("For anyone wanting to re-tabulate without re-running.")
    md.append("")
    md.append("```json")
    md.append(json.dumps({r.name: r.numbers for r in ran}, indent=2, ensure_ascii=False,
                         default=str))
    md.append("```")
    md.append("")

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out = RESULTS_DIR / f"{today}-report.md"
    out.write_text("\n".join(md), encoding="utf-8")

    log.info("")
    log.info("[run_all] DONE  ran=%d skipped=%d failed=%d", len(ran), len(skipped), len(failed))
    log.info("[run_all] report -> %s", out)
    for r in skipped + failed:
        log.info("[run_all] %-22s %s — %s", r.name, r.status, r.reason)

    return 1 if failed else 0


def _headline(r: CheckResult) -> str:
    """One-line summary per check for the summary table."""
    if r.status != RAN:
        return r.reason[:110]
    n = r.numbers
    if r.name == "wer_check":
        return "; ".join(f"{m}: corpus WER {v['corpus_wer']:.3f}" for m, v in n.items()
                         if isinstance(v, dict) and "corpus_wer" in v) or "ran"
    if r.name == "diarization_check":
        s = f"DER {n.get('der_overall', float('nan')):.3f} overall"
        if n.get("der_overlap_region") is not None:
            s += f", {n['der_overlap_region']:.3f} in the overlap"
        return s
    if r.name == "scoring_check":
        parts = []
        for path, sep in (n.get("separation") or {}).items():
            if sep:
                parts.append(f"{path}: correct {sep['mean_correct']:.3f} vs deviant "
                             f"{sep['mean_deviant']:.3f}"
                             f"{' (separable)' if sep.get('separable') else ' (OVERLAP)'}")
        for path, te in (n.get("threshold_eval") or {}).items():
            parts.append(f"{path}: {te['false_negatives']} false negative(s)")
        return "; ".join(parts) or "ran"
    if r.name == "translation_check":
        s = []
        if "chrf_mean" in n:
            s.append(f"chrF {n['chrf_mean']:.1f}")
        if "labse_ceiling_mean" in n:
            s.append(f"LaBSE ceiling {n['labse_ceiling_mean']:.3f}")
        return ", ".join(s) or "ran"
    return "ran"


def _cli() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--only", default=",".join(CHECKS),
                    help=f"comma-separated subset of: {', '.join(CHECKS)}")
    ap.add_argument("--models", default=None,
                    help="Whisper models for the WER check (default: turbo,large-v3)")
    args = ap.parse_args()

    only = [k.strip() for k in args.only.split(",") if k.strip()]
    bad = [k for k in only if k not in CHECKS]
    if bad:
        print(f"unknown check(s): {', '.join(bad)}. Valid: {', '.join(CHECKS)}", file=sys.stderr)
        return 2

    models = [m.strip() for m in args.models.split(",")] if args.models else None
    return asyncio.run(main(only, models))


if __name__ == "__main__":
    raise SystemExit(_cli())
