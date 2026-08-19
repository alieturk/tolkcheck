# `evaluation/` — measured evidence for DV2

These scripts exist because DV2 asks which ASR, diarization, and semantic-comparison
methods are *suitable* for reference-free deviation detection in Turkish–Dutch, and
**that question cannot be settled by reading papers**. The published numbers for
Whisper, pyannote, and LaBSE were measured on other data, other languages, and other
pipeline shapes than the one in `app/`. These scripts run the actual code in this
repository against data with known ground truth and report what comes out.

They are **not** unit tests and deliberately do not live in `tests/`:

- they need model weights (several GB), an HF token, and an Anthropic API key
- a single run takes minutes to tens of minutes on CPU
- they produce a human-readable report, not pass/fail assertions
- their numbers are expected to drift with model versions; a moved number is a
  finding to write down, not a build to break

`pytest.ini` sets `testpaths = tests`, so nothing here is collected by a bare
`pytest` run. Keep it that way.

---

## Quick start

```bash
# from backend/
uv pip install -e '.[eval]'                      # jiwer, pyannote.metrics, sacrebleu, edge-tts
uv run python evaluation/make_fixtures.py        # generate the audio fixtures (once)
uv run python evaluation/run_all.py              # run everything possible, write the report
```

The report lands at `evaluation/results/YYYY-MM-DD-report.md`.

Run one check at a time while iterating:

```bash
uv run python evaluation/scoring_check.py                        # no audio needed
uv run python evaluation/scoring_check.py --paths cross_lingual  # no API key needed
uv run python evaluation/wer_check.py --models large-v3          # skip the second model
uv run python evaluation/diarization_check.py
uv run python evaluation/translation_check.py
uv run python evaluation/run_all.py --only scoring,translation
```

## What each script needs

| Script | Needs | Runs without it? |
|---|---|---|
| `make_fixtures.py` | `edge-tts`, internet (Microsoft TTS endpoint) | no — audio checks have no input without it |
| `wer_check.py` | `jiwer`, audio fixtures, Whisper weights (downloads on first run: `turbo` ~1.6 GB, `large-v3` ~3 GB) | no |
| `diarization_check.py` | `pyannote.metrics`, session fixture, **`HF_TOKEN`** + accepted licence | no — skips with a reason |
| `scoring_check.py` | `sentence-transformers` + LaBSE weights (~1.8 GB, downloads on first run) | path A yes; path B needs **`ANTHROPIC_API_KEY`** |
| `translation_check.py` | **`ANTHROPIC_API_KEY`**; `sacrebleu` optional | no |

`HF_TOKEN` also requires accepting the model licence at
<https://hf.co/pyannote/speaker-diarization-3.1> with the same account — a valid
token alone gives a 401/403.

Every script degrades honestly: a missing prerequisite produces a `skipped` result
with the reason, which `run_all.py` prints in the report's *Not run* section. **No
script ever substitutes an estimated number for one it could not measure.**

## What each script measures

**`wer_check.py`** — WER/CER per clip and corpus WER per language, for each Whisper
model. Calls `transcription.transcribe_chunk()` with a pre-loaded waveform and
`language=None`, which is exactly how `pipeline.run_pipeline()` calls it per
diarization turn; the batch `transcribe()` function is not used because production
does not use it. Also reports per-turn language auto-detection accuracy — arguably
the more important number, since the pipeline relies on per-turn detection to tell
the interpreter's two languages apart.

**`diarization_check.py`** — DER against the ground-truth RTTM, using the real
pyannote pipeline via `diarization.diarize(num_speakers=3)`. Reports DER overall,
on non-overlapping speech only, and inside the session's deliberate 1.2 s overlap —
the case `diarization.py`'s own `OVERLAP` warning already flags.

**`scoring_check.py`** — the central DV2 measurement. Runs the real
`scoring.score_segments()` (every test in `tests/` mocks it) over 20 labelled pairs
down **both** paths `pipeline.resume_scoring` uses: direct cross-lingual LaBSE (the
o2c path) and Claude pseudo-reference + monolingual LaBSE (the c2o path). Reports
whether correct and deviant pairs separate at all, whether the two paths differ, and
how `feedback.py`'s 0.70 / 0.65 / 0.50 cut-offs would classify each labelled pair —
including which real errors they would call fine.

**`translation_check.py`** — chrF/BLEU for `feedback.translate_to_dutch()` against
Dutch references, plus `LaBSE(Claude's Dutch, reference Dutch)`. That last figure is
the practical one: it approximates the ceiling on the c2o path, since the pipeline
scores the interpreter against Claude's Dutch rather than against the truth. Also
writes `results/translation_manual_review.csv` for a bilingual reviewer.

## Fixtures

```
data/
  audio/{tr,nl}_0*.wav + .txt          8 clips, reference transcript = the TTS input text
  session/session_3spk.wav             38 s, 3 speakers, one deliberate 1.2 s overlap
  session/session_3spk.rttm            diarization ground truth
  session/session_3spk.script.json     turn-by-turn record + overlap region
  pairs.csv                            20 labelled source/rendering pairs
  translation_pairs.csv                10 Turkish sentences + Dutch references
```

`pairs.csv` covers five error categories — `omissie`, `toevoeging`,
`betekenisverschuiving`, `entiteitsfout`, and `ontkenning` (negation flip, chosen as
the fifth because reversing a denial is both easy to miss and legally decisive) —
plus a `correct` control group, split across both directions.

### ⚠️ Provenance: none of this data is human-validated

Every row in `pairs.csv` and `translation_pairs.csv` carries `human_verified=no`.
The Turkish text, the Dutch translations, and the category labels were **written by
an LLM (Claude), not by a native speaker.** The audio is **TTS, not human speech.**

This matters concretely, not just as a caveat:

- WER and DER on TTS audio are **floors**. No accents, disfluencies, false starts,
  overlapping crosstalk beyond the one synthesised overlap, room acoustics, or
  handset bandwidth limiting. Whisper and TTS are both centred on clean read speech.
- Unidiomatic Turkish could depress LaBSE scores for reasons unrelated to the
  labelled error, which would look like detection working when it is not.
- A pair labelled `betekenisverschuiving` may not actually be one.
- `translation_check.py` currently scores Claude against Claude-authored references,
  so its absolute values are not translation quality.

**A Turkish/Dutch bilingual reviewer flipping `human_verified` to `yes` per row is
the single highest-value contribution to this evaluation.** Real recorded audio is
second.

## Regenerating fixtures

`make_fixtures.py` is deterministic in structure but the TTS service may return
slightly different audio over time, which shifts clip durations and therefore the
RTTM. Regenerating invalidates comparison with older reports — note the date and
`git_commit` recorded in each report's Environment table when comparing runs.

## Interpreting the report

Read `## Known limitations of this evaluation` first — it is generated into every
report for a reason. In particular:

- **n is small.** 8 clips, 1 session, 20 pairs, 10 translation items. Enough to show
  an effect exists and roughly its size; nowhere near enough to set a threshold.
  DV4 threshold calibration needs an order of magnitude more labelled data.
- **Nothing here measures the composed system.** Each check isolates one stage
  against clean input. In production a diarization swap feeds wrong text to scoring,
  and a transcription error is indistinguishable at the scoring stage from an
  interpreter error. The compounded error rate is **not measured** and is worse than
  any single figure suggests.

## Environment notes

**Windows / no ffmpeg — handled automatically.** `torchcodec` ships as a torchaudio
dependency but needs FFmpeg 4–7 shared libraries at import time. Without them
`import torchcodec` raises `RuntimeError`, and
`sentence_transformers.base.modality_types` guards only against
`ImportError`/`OSError` — so LaBSE cannot be imported at all, with a traceback that
blames audio decoding rather than the missing FFmpeg.

`_common.neutralise_broken_torchcodec()` detects this at import time and substitutes
a stub, so the scripts just work. It is a no-op when torchcodec is absent or
loading correctly. This is worth knowing about because uninstalling torchcodec by
hand does **not** stay fixed — any `uv run` or `uv sync` reinstalls it from the
lockfile, which silently re-broke `scoring_check` between two runs during
development. Audio decoding falls back to `soundfile` (libsndfile ≥ 1.2), which
reads the 16 kHz WAV fixtures — and MP3 — without FFmpeg.

Installing FFmpeg 4–7 on `PATH` also fixes it properly, and then the stub never
engages.

**CPU only.** `whisper_device` defaults to `cpu`. `wer_check.py` reports RTF
(processing seconds per audio second) so the speed side of the `large-v3` vs `turbo`
trade-off is visible alongside the accuracy side.
