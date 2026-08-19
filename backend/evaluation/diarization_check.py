"""DV2 — speaker diarization accuracy (DER) on the 3-speaker gold session.

Calls the real `diarization.diarize()` — the actual pyannote
speaker-diarization-3.1 pipeline, with `num_speakers=3` exactly as
`pipeline.run_pipeline()` passes it. The mocked helpers in
tests/test_diarization.py cover none of this.

Reports DER overall and DER restricted to the deliberately overlapped region,
because overlapping speech is the failure mode diarization.py's own
`OVERLAP` warning already flags as a risk — and the region where a swap between
the interpreter's and the client's voice would do the most damage (it would
attribute the client's testimony to the interpreter, or vice versa).

    uv run python evaluation/diarization_check.py

Requires: HF_TOKEN in .env, the model licence accepted at
https://hf.co/pyannote/speaker-diarization-3.1, and pyannote.metrics.
⚠️  Ground truth is exact by construction (see make_fixtures.py), and TTS voices
    separate far more easily than real speakers. This DER is a floor.
"""
from __future__ import annotations

import asyncio
import json

from _common import (
    RAN,
    SESSION_DIR,
    CheckResult,
    env_missing,
    log,
    md_table,
    setup_logging,
)

NAME = "diarization_check"
SESSION_WAV = SESSION_DIR / "session_3spk.wav"
SESSION_RTTM = SESSION_DIR / "session_3spk.rttm"
SESSION_META = SESSION_DIR / "session_3spk.script.json"


def _load_reference():
    """Read the ground-truth RTTM into a pyannote Annotation."""
    from pyannote.core import Annotation, Segment

    ref = Annotation(uri="session_3spk")
    for line in SESSION_RTTM.read_text(encoding="utf-8").splitlines():
        parts = line.split()
        if not parts or parts[0] != "SPEAKER":
            continue
        start, dur, speaker = float(parts[3]), float(parts[4]), parts[7]
        ref[Segment(start, start + dur)] = speaker
    return ref


def _to_annotation(turns: list[dict]):
    """Convert diarize()'s list-of-dicts output into a pyannote Annotation."""
    from pyannote.core import Annotation, Segment

    hyp = Annotation(uri="session_3spk")
    for t in turns:
        hyp[Segment(t["start"], t["end"])] = t["speaker"]
    return hyp


async def run() -> CheckResult:
    if not SESSION_WAV.exists() or not SESSION_RTTM.exists():
        return CheckResult.skipped(
            NAME, f"gold session missing in {SESSION_DIR} — run "
                  "`python evaluation/make_fixtures.py` first")

    try:
        from pyannote.metrics.diarization import DiarizationErrorRate
    except ImportError:
        return CheckResult.skipped(
            NAME, "pyannote.metrics not installed (`uv pip install -e '.[eval]'`)")

    if env_missing("hf_token"):
        return CheckResult.skipped(
            NAME, "HF_TOKEN unset or placeholder in .env — pyannote cannot download "
                  "speaker-diarization-3.1. Also accept the licence at "
                  "https://hf.co/pyannote/speaker-diarization-3.1")

    meta = json.loads(SESSION_META.read_text(encoding="utf-8")) if SESSION_META.exists() else {}
    overlap = meta.get("overlap_region")

    from app.services import diarization

    log.info("[%s] file=%s duration=%.1fs num_speakers=3",
             NAME, SESSION_WAV.name, meta.get("total_duration", -1))

    try:
        turns = await diarization.diarize(SESSION_WAV, num_speakers=3)
    except Exception as exc:
        return CheckResult.failed(
            NAME, f"diarize() raised {type(exc).__name__}: {exc}. If this is a 401/403, "
                  "the HF token lacks access — accept the model licence.")

    if not turns:
        return CheckResult.failed(NAME, "diarize() returned no turns")

    reference = _load_reference()
    hypothesis = _to_annotation(turns)

    # DiarizationErrorRate does optimal (Hungarian) speaker mapping internally, so
    # pyannote's SPEAKER_00/01/02 labels are matched against officer/interpreter/
    # client without us guessing the correspondence.
    metric = DiarizationErrorRate(collar=0.0, skip_overlap=False)
    der_overall = metric(reference, hypothesis, detailed=True)

    # Same metric, windowed to the overlap region only.
    der_overlap = None
    if overlap:
        from pyannote.core import Segment, Timeline

        region = Timeline([Segment(overlap["start"], overlap["end"])], uri="session_3spk")
        der_overlap = DiarizationErrorRate(collar=0.0, skip_overlap=False)(
            reference, hypothesis, uem=region, detailed=True)

    # And with skip_overlap=True, i.e. non-overlapping speech only — the contrast
    # between this and der_overall isolates the overlap cost.
    der_clean = DiarizationErrorRate(collar=0.0, skip_overlap=True)(
        reference, hypothesis, detailed=True)

    def fmt(d) -> dict:
        total = d.get("total", 0) or 1
        return {
            "der": d["diarization error rate"],
            "confusion": d.get("confusion", 0.0),
            "missed": d.get("missed detection", 0.0),
            "false_alarm": d.get("false alarm", 0.0),
            "total": d.get("total", 0.0),
            "confusion_pct": d.get("confusion", 0.0) / total,
            "missed_pct": d.get("missed detection", 0.0) / total,
            "false_alarm_pct": d.get("false alarm", 0.0) / total,
        }

    o, c = fmt(der_overall), fmt(der_clean)
    v = fmt(der_overlap) if der_overlap else None

    log.info("[%s] der_overall=%.4f confusion=%.2fs missed=%.2fs false_alarm=%.2fs ref=%.2fs",
             NAME, o["der"], o["confusion"], o["missed"], o["false_alarm"], o["total"])
    log.info("[%s] der_non_overlap=%.4f", NAME, c["der"])
    if v:
        log.info("[%s] der_overlap_region=%.4f window=%.2f–%.2fs",
                 NAME, v["der"], overlap["start"], overlap["end"])

    # ── Report ────────────────────────────────────────────────────────────────
    md: list[str] = []
    md.append(f"Real `pyannote/speaker-diarization-3.1` via `diarization.diarize(num_speakers=3)` "
              f"on a {meta.get('total_duration', '?')}s synthetic 3-speaker session "
              f"({len(reference.labels())} reference speakers, "
              f"{len(hypothesis.labels())} predicted). DER uses `collar=0.0` — no "
              f"forgiveness window at boundaries — and pyannote's own optimal speaker "
              f"mapping, so predicted `SPEAKER_xx` labels are matched to "
              f"officer/interpreter/client automatically.\n")

    rows = [["**overall**", o["der"], o["confusion"], o["missed"], o["false_alarm"], o["total"]],
            ["non-overlapping speech only", c["der"], c["confusion"], c["missed"],
             c["false_alarm"], c["total"]]]
    if v:
        rows.append([f"overlap region only ({overlap['start']:.2f}–{overlap['end']:.2f}s)",
                     v["der"], v["confusion"], v["missed"], v["false_alarm"], v["total"]])
    md.append(md_table(
        ["window", "DER", "confusion s", "missed s", "false alarm s", "ref speech s"], rows))
    md.append("")

    md.append(f"DER components as a fraction of reference speech in each window — "
              f"overall: confusion {o['confusion_pct']:.1%}, missed {o['missed_pct']:.1%}, "
              f"false alarm {o['false_alarm_pct']:.1%}.\n")

    if v:
        md.append(f"**Overlap region.** The session contains one deliberate 1.2 s overlap "
                  f"({overlap['start']:.2f}–{overlap['end']:.2f}s), where the "
                  f"{'/'.join(overlap['speakers'])} turns collide — the interpreter starts "
                  f"rendering before the client has finished. DER there is "
                  f"**{v['der']:.3f}** versus **{c['der']:.3f}** on non-overlapping speech. "
                  f"pyannote 3.1 does emit overlapping segments, but the single-label "
                  f"attribution the pipeline consumes (`diarize()` flattens to one speaker "
                  f"per turn) cannot represent two simultaneous speakers, so overlapped "
                  f"speech is necessarily charged as missed detection or confusion here.\n")
    else:
        md.append("⚠️  No overlap region recorded in the session metadata — the overlap-specific "
                  "figure could not be computed.\n")

    # ── Role confusion matrix ─────────────────────────────────────────────────
    # An aggregate DER hides *which* roles get mixed up, and for this tool the
    # identity of the confusion matters more than its size: alignment.py builds
    # client->officer pairs by walking back to the "nearest preceding client block",
    # so an officer/client swap silently pairs the wrong utterances and every
    # downstream score is computed on a pair that never existed. An
    # interpreter/officer swap is far less damaging. Report the breakdown.
    from collections import defaultdict

    mapping = DiarizationErrorRate().optimal_mapping(reference, hypothesis)
    matrix: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    ref_totals: dict[str, float] = defaultdict(float)
    for ref_seg, _, ref_lbl in reference.itertracks(yield_label=True):
        ref_totals[ref_lbl] += ref_seg.duration
        for hyp_seg, _, hyp_lbl in hypothesis.itertracks(yield_label=True):
            inter = ref_seg & hyp_seg
            if inter:
                matrix[ref_lbl][mapping.get(hyp_lbl, f"unmapped/{hyp_lbl}")] += inter.duration

    roles = sorted(ref_totals)
    cols = roles + sorted({k for v in matrix.values() for k in v if k not in roles})
    md.append("**Role confusion matrix** — seconds of each reference role's speech "
              "attributed to each role, after pyannote's optimal label mapping. "
              "`not detected` is reference speech the diarizer assigned to nobody. "
              "Rows can exceed their own duration where the hypothesis overlaps itself.\n")
    md.append(md_table(
        ["reference role", "ref s", *cols, "not detected"],
        [[role, f"{ref_totals[role]:.2f}",
          *(f"{matrix[role].get(c, 0.0):.2f}" for c in cols),
          f"{max(0.0, ref_totals[role] - sum(matrix[role].values())):.2f}"]
         for role in roles]))
    md.append("")

    # Name the worst cross-role leak explicitly. NB: distinct loop variable names —
    # `o`, `c` and `v` above hold the three metrics dicts and must not be shadowed.
    leaks = [(ref_role, hyp_role, secs)
             for ref_role, row in matrix.items() for hyp_role, secs in row.items()
             if hyp_role != ref_role and hyp_role in roles]
    numbers_confusion = {f"{a}->{b}": round(s, 3) for a, b, s in leaks}
    if leaks:
        worst_ref, worst_hyp, worst_s = max(leaks, key=lambda t: t[2])
        pct = worst_s / ref_totals[worst_ref] if ref_totals[worst_ref] else 0.0
        md.append(f"Largest cross-role leak: **{worst_s:.2f}s ({pct:.0%})** of `{worst_ref}` "
                  f"speech was attributed to `{worst_hyp}`.\n")
        if {worst_ref, worst_hyp} == {"officer", "client"}:
            md.append("⚠️  This is the officer/client pair specifically — the worst case for this "
                      "pipeline. `alignment.extract_pairs()` pairs each `to_officer` interpreter "
                      "block with the nearest preceding **client** block; if officer speech is "
                      "labelled client (or the reverse), the pipeline scores the interpreter "
                      "against the wrong source utterance and the resulting similarity score is "
                      "meaningless rather than merely noisy. Both are male voices in this "
                      "fixture, while the interpreter is female and separates cleanly — which "
                      "suggests the confusion is driven by voice similarity, not by the turn "
                      "structure. A real hearing offers no guarantee that the three parties "
                      "differ in gender, so this is a live risk and not a fixture artefact. It "
                      "also argues that the frontend's role-confirmation step is load-bearing "
                      "and cannot be automated away.\n")
    else:
        md.append("No cross-role confusion: every role's speech was attributed to that role.\n")

    md.append("**Predicted turns vs ground truth:**\n")
    md.append(md_table(["#", "predicted speaker", "start", "end", "dur"],
                       [[i, t["speaker"], f"{t['start']:.2f}", f"{t['end']:.2f}",
                         f"{t['end'] - t['start']:.2f}"]
                        for i, t in enumerate(sorted(turns, key=lambda t: t["start"]))]))
    md.append("")
    md.append(md_table(["#", "reference speaker", "start", "end", "dur"],
                       [[i, lbl, f"{seg.start:.2f}", f"{seg.end:.2f}", f"{seg.duration:.2f}"]
                        for i, (seg, _, lbl) in enumerate(reference.itertracks(yield_label=True))]))
    md.append("")

    n_pred, n_ref = len(hypothesis.labels()), len(reference.labels())
    if n_pred != n_ref:
        md.append(f"⚠️  pyannote returned {n_pred} speakers where the reference has {n_ref}, "
                  f"despite `num_speakers=3` being passed. Speaker-count errors are worse than "
                  f"boundary errors for this tool: role confirmation in the frontend assumes "
                  f"exactly three parties.\n")

    numbers = {
        "der_overall": o["der"],
        "der_non_overlap": c["der"],
        "der_overlap_region": v["der"] if v else None,
        "confusion_s": o["confusion"],
        "missed_s": o["missed"],
        "false_alarm_s": o["false_alarm"],
        "reference_speech_s": o["total"],
        "predicted_speakers": n_pred,
        "reference_speakers": n_ref,
        "predicted_turns": len(turns),
        "session_duration_s": meta.get("total_duration"),
        "cross_role_confusion_s": numbers_confusion,
        "optimal_mapping": {str(k): str(v) for k, v in mapping.items()},
    }
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
