"""DV2 — transcription accuracy (WER) on the Turkish/Dutch gold clips.

Measures what the pipeline actually does, not the convenient thing:
`transcription.transcribe_chunk()` is called with a pre-loaded waveform and
`language=None`, exactly as `pipeline.run_pipeline()` calls it per diarization
turn. The batch `transcription.transcribe()` path is NOT used, because production
never uses it.

Runs once per model in --models so the config.py choice between `large-v3` and
`turbo` rests on measured numbers rather than assumption.

    uv run python evaluation/wer_check.py
    uv run python evaluation/wer_check.py --models large-v3
    uv run python evaluation/wer_check.py --models turbo,large-v3

Requires: jiwer, and enough disk/time for each Whisper model to download.
⚠️  Reference transcripts are the TTS input text — see make_fixtures.py for why
    these WER figures are a best case, not a field estimate.
"""
from __future__ import annotations

import argparse
import asyncio
import time

from _common import (
    AUDIO_DIR,
    FAILED,
    RAN,
    CheckResult,
    log,
    md_table,
    normalise_text,
    setup_logging,
)

NAME = "wer_check"
DEFAULT_MODELS = ["turbo", "large-v3"]


def _load_clips() -> list[dict]:
    """Every .wav in data/audio that has a matching .txt reference."""
    clips = []
    for wav in sorted(AUDIO_DIR.glob("*.wav")):
        ref = wav.with_suffix(".txt")
        if not ref.exists():
            log.warning("[%s] no reference for %s — skipped", NAME, wav.name)
            continue
        clips.append({
            "id": wav.stem,
            "path": wav,
            # Clip ids are prefixed with the language they were synthesised in.
            "language": wav.stem.split("_")[0],
            "reference": ref.read_text(encoding="utf-8").strip(),
        })
    return clips


async def _transcribe_one(clip: dict) -> tuple[str, float, str, float]:
    """Transcribe one clip the way run_pipeline does.

    Returns (text, elapsed_s, detected_lang, audio_s). Audio duration comes from the
    loaded waveform rather than torchaudio.info(), which is deprecated and slated
    for removal in torchaudio 2.9.
    """
    import torchaudio

    from app.services import transcription

    waveform, sr = torchaudio.load(str(clip["path"]))
    audio_s = waveform.shape[-1] / sr
    t0 = time.perf_counter()
    # language=None: production always auto-detects per turn (pipeline.py sets
    # `language = None` explicitly and documents why), so forcing the known
    # language here would measure a configuration the tool never runs in.
    segs = await transcription.transcribe_chunk(waveform, sr, None)
    elapsed = time.perf_counter() - t0

    text = " ".join(s["text"] for s in segs).strip()
    detected = segs[0].get("language", "?") if segs else "?"
    return text, elapsed, detected, audio_s


def _score(reference: str, hypothesis: str) -> dict:
    import jiwer

    ref_n = normalise_text(reference, map_numbers=True)
    hyp_n = normalise_text(hypothesis, map_numbers=True)
    ref_raw = normalise_text(reference, map_numbers=False)
    hyp_raw = normalise_text(hypothesis, map_numbers=False)

    out = jiwer.process_words(ref_n, hyp_n)
    return {
        "wer": out.wer,
        "cer": jiwer.cer(ref_n, hyp_n),
        "wer_no_numfix": jiwer.wer(ref_raw, hyp_raw),
        "sub": out.substitutions,
        "del": out.deletions,
        "ins": out.insertions,
        "ref_words": len(ref_n.split()),
    }


async def run(models: list[str] | None = None) -> CheckResult:
    models = models or DEFAULT_MODELS

    try:
        import jiwer  # noqa: F401
    except ImportError:
        return CheckResult.skipped(NAME, "jiwer not installed (`uv pip install -e '.[eval]'`)")

    clips = _load_clips()
    if not clips:
        return CheckResult.skipped(
            NAME, f"no gold clips in {AUDIO_DIR} — run `python evaluation/make_fixtures.py` first")

    from app.config import settings
    from app.services import transcription

    original_model = settings.whisper_model
    per_model: dict[str, list[dict]] = {}
    failures: list[str] = []

    try:
        for model_name in models:
            # transcription._get_model() caches the WhisperModel at module level and
            # keys off settings, so both have to be reset to switch model.
            settings.whisper_model = model_name
            transcription._model = None
            log.info("[%s] model=%s device=%s compute=%s clips=%d",
                     NAME, model_name, settings.whisper_device,
                     settings.whisper_compute_type, len(clips))

            rows = []
            for clip in clips:
                try:
                    hyp, elapsed, detected, audio_s = await _transcribe_one(clip)
                except Exception as exc:
                    log.error("[%s] clip=%s model=%s FAILED: %s", NAME, clip["id"], model_name, exc)
                    failures.append(f"{model_name}/{clip['id']}: {exc}")
                    continue

                sc = _score(clip["reference"], hyp)
                row = {
                    "clip": clip["id"],
                    "expected_lang": clip["language"],
                    "detected_lang": detected,
                    "audio_s": audio_s,
                    "secs": elapsed,
                    "rtf": (elapsed / audio_s) if audio_s else None,
                    "hypothesis": hyp,
                    **sc,
                }
                rows.append(row)
                log.info("[%s] clip=%s model=%s lang=%s/%s wer=%.3f cer=%.3f "
                         "sub=%d del=%d ins=%d %.1fs (rtf=%.2f)",
                         NAME, clip["id"], model_name, clip["language"], detected,
                         sc["wer"], sc["cer"], sc["sub"], sc["del"], sc["ins"],
                         elapsed, row["rtf"] or 0.0)
            per_model[model_name] = rows
    finally:
        settings.whisper_model = original_model
        transcription._model = None

    if not any(per_model.values()):
        return CheckResult.failed(NAME, "every clip failed to transcribe: " + "; ".join(failures[:5]))

    # ── Report ────────────────────────────────────────────────────────────────
    md: list[str] = []
    numbers: dict = {}

    md.append("Per-clip WER. `transcribe_chunk()` called with a pre-loaded waveform and "
              "`language=None` — the same call `run_pipeline()` makes per diarization turn. "
              "WER is computed on normalised text (lowercase, punctuation stripped, small "
              "number words digitised); `WER raw` omits the number mapping so the formatting "
              "contribution is visible. RTF = processing seconds per audio second on CPU.\n")

    for model_name, rows in per_model.items():
        if not rows:
            md.append(f"### {model_name}\n\nAll clips failed.\n")
            continue

        md.append(f"### `{model_name}`\n")
        md.append(md_table(
            ["clip", "lang exp/det", "audio s", "WER", "WER raw", "CER", "sub", "del", "ins", "ref words", "RTF"],
            [[r["clip"], f"{r['expected_lang']}/{r['detected_lang']}",
              f"{r['audio_s']:.1f}" if r["audio_s"] else "?",
              r["wer"], r["wer_no_numfix"], r["cer"],
              r["sub"], r["del"], r["ins"], r["ref_words"],
              f"{r['rtf']:.2f}" if r["rtf"] else "?"] for r in rows]))
        md.append("")

        # Corpus-level WER: total errors / total reference words. This is the figure
        # to quote — a plain mean of per-clip WERs over-weights short clips.
        tot_err = sum(r["sub"] + r["del"] + r["ins"] for r in rows)
        tot_ref = sum(r["ref_words"] for r in rows)
        by_lang: dict[str, dict] = {}
        for r in rows:
            b = by_lang.setdefault(r["expected_lang"], {"err": 0, "ref": 0, "n": 0})
            b["err"] += r["sub"] + r["del"] + r["ins"]
            b["ref"] += r["ref_words"]
            b["n"] += 1

        lang_rows = [[lang, b["n"], b["err"], b["ref"], b["err"] / b["ref"]]
                     for lang, b in sorted(by_lang.items())]
        lang_rows.append(["**all**", len(rows), tot_err, tot_ref, tot_err / tot_ref])
        md.append("Corpus WER per language (total errors / total reference words):\n")
        md.append(md_table(["language", "clips", "errors", "ref words", "corpus WER"], lang_rows))
        md.append("")

        misdetect = [r for r in rows if r["detected_lang"] != r["expected_lang"]]
        if misdetect:
            md.append(f"⚠️  Language auto-detection was wrong on {len(misdetect)}/{len(rows)} clips: "
                      + ", ".join(f"`{r['clip']}` (expected {r['expected_lang']}, got "
                                  f"{r['detected_lang']})" for r in misdetect)
                      + ". This matters more than WER: pipeline.py relies on per-turn "
                        "auto-detection to tell the interpreter's two languages apart.\n")
        else:
            md.append(f"Language auto-detection was correct on all {len(rows)} clips.\n")

        numbers[model_name] = {
            "corpus_wer": tot_err / tot_ref,
            "per_language": {lang: b["err"] / b["ref"] for lang, b in by_lang.items()},
            "mean_rtf": (sum(r["rtf"] for r in rows if r["rtf"]) /
                         max(sum(1 for r in rows if r["rtf"]), 1)),
            "language_misdetections": len(misdetect),
            "clips": len(rows),
        }

    if len(numbers) > 1:
        md.append("### Model comparison\n")
        md.append(md_table(
            ["model", "corpus WER", *(f"WER {lang}" for lang in sorted(
                next(iter(numbers.values()))["per_language"])), "mean RTF", "lang misdetects"],
            [[m, n["corpus_wer"], *(n["per_language"].get(lang, float("nan"))
                                    for lang in sorted(n["per_language"])),
              f"{n['mean_rtf']:.2f}", n["language_misdetections"]]
             for m, n in numbers.items()]))
        md.append("")

        # Whether this fixture set can tell the models apart at all is a separate
        # question from which model won, and the more important one to report
        # honestly: a tie on saturated data is not evidence of equivalence.
        wers = {m: n["corpus_wer"] for m, n in numbers.items()}
        spread = max(wers.values()) - min(wers.values())
        best = min(wers, key=wers.get)
        all_zero = all(w == 0.0 for w in wers.values())
        numbers["_comparison"] = {"corpus_wer_by_model": wers, "spread": spread,
                                  "discriminating": spread > 0.01}

        if spread == 0.0:
            md.append(
                f"⚠️  **This fixture set does not discriminate between the models.** Every model "
                f"tested produced an identical corpus WER of {min(wers.values()):.3f}"
                + (" — i.e. a perfect transcription of every clip" if all_zero else "")
                + ". The measurement is saturated: clean TTS read speech is easy enough that "
                  "`turbo` and `large-v3` are indistinguishable on it, so **these numbers cannot "
                  "justify the `large-v3` default in config.py, and equally cannot justify "
                  "switching to `turbo`.** A tie on a saturated benchmark is not evidence of "
                  "equivalence — it means the benchmark is not measuring the thing. The "
                  "distillation cost of `turbo` would show up on accented, noisy, or "
                  "disfluent Turkish, which is exactly what this fixture set lacks. Settling "
                  "the model choice needs harder audio (real or human-recorded); until then "
                  "`large-v3` stands as the conservative default, not the measured one.\n")
            md.append("The only difference is speed: mean RTF "
                      + ", ".join(f"`{m}` {n['mean_rtf']:.2f}" for m, n in numbers.items()
                                  if isinstance(n, dict) and "mean_rtf" in n)
                      + " (processing seconds per audio second, CPU int8). Note this is the "
                        "one dimension the fixture set *can* measure.\n")
        elif spread < 0.01:
            md.append(f"⚠️  The models differ by only {spread:.4f} corpus WER — within noise for "
                      f"8 clips. `{best}` is nominally ahead but this data cannot support a "
                      f"model choice.\n")
        else:
            md.append(f"`{best}` has the lower corpus WER ({wers[best]:.3f} vs "
                      + ", ".join(f"{m} {w:.3f}" for m, w in wers.items() if m != best)
                      + f"), a spread of {spread:.3f}. On 8 clips of clean TTS speech treat this "
                        f"as directional only.\n")

    md.append("**Transcripts produced (for eyeballing what the errors actually are):**\n")
    for model_name, rows in per_model.items():
        for r in rows:
            ref = next(c["reference"] for c in clips if c["id"] == r["clip"])
            md.append(f"- `{model_name}` / `{r['clip']}`  \n"
                      f"  ref: {ref}  \n"
                      f"  hyp: {r['hypothesis']}")
    md.append("")

    if failures:
        md.append("**Clips that failed outright:** " + "; ".join(f"`{f}`" for f in failures) + "\n")

    result = CheckResult(name=NAME, status=RAN, markdown="\n".join(md), numbers=numbers)
    if failures and not any(per_model.values()):
        result.status = FAILED
        result.reason = "; ".join(failures[:5])
    return result


def _main() -> int:
    setup_logging()
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--models", default=",".join(DEFAULT_MODELS),
                    help="comma-separated Whisper model names (default: turbo,large-v3)")
    args = ap.parse_args()

    res = asyncio.run(run([m.strip() for m in args.models.split(",") if m.strip()]))
    print("\n" + "=" * 70)
    print(f"{res.name}: {res.status}" + (f" — {res.reason}" if res.reason else ""))
    print("=" * 70)
    print(res.markdown or "(no output)")
    return 0 if res.status == RAN else 1


if __name__ == "__main__":
    raise SystemExit(_main())
