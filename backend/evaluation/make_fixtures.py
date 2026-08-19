"""Generate the synthetic gold-set audio fixtures for the DV2 evaluation.

Run this once before the audio-dependent checks (wer_check, diarization_check):

    uv run python evaluation/make_fixtures.py

Produces, under evaluation/data/:

    audio/tr_0*.wav + .txt   4 Turkish clips  + hand-written reference transcript
    audio/nl_0*.wav + .txt   4 Dutch clips    + hand-written reference transcript
    session/session_3spk.wav          3-speaker officer/interpreter/client session
    session/session_3spk.rttm         diarization ground truth
    session/session_3spk.script.json  turn-by-turn record of what was synthesised

⚠️  THESE ARE TTS (SYNTHETIC-VOICE) CLIPS, NOT HUMAN RECORDINGS.
    Microsoft Edge neural TTS via the `edge-tts` package. Consequences that must
    be carried into any write-up of the numbers:

      - WER on TTS audio is OPTIMISTIC. No accent variation, no disfluencies, no
        false starts, no crosstalk, no room acoustics, no telephone/handset
        bandwidth limiting, no background noise. A real IND hearing room has all
        of these. Treat the WER figures as a floor (best case), never as an
        estimate of field performance.
      - Whisper and TTS are both trained on read speech, so the two systems are
        unusually well matched here. This flatters the transcription step
        specifically.
      - The DIARIZATION ground truth is exact by construction (we know where each
        clip was placed) rather than hand-labelled — so DER carries no annotator
        error. But TTS voices are far more separable than real speakers: no shared
        accent, no similar pitch range, clean channel. DER here is a floor too.
        Clips are silence-trimmed before placement so that RTTM segments bound
        actual speech; skipping that step put ~8.8 s of padding inside the declared
        speech regions of this session and inflated measured DER from ~0.1 to
        ~0.41, all of it charged to pyannote as missed detection. See
        _trim_silence().
      - The INTERPRETER is voiced by a Turkish voice for BOTH its Turkish and its
        Dutch turns (see VOICES below). Speaker identity is therefore consistent,
        which is what diarization keys on, but the Dutch comes out
        Turkish-accented. That is arguably realistic for a Turkish-Dutch
        interpreter, but it was a constraint, not a design choice: edge-tts voices
        are locale-bound and no single voice covers both languages.

    Replacing these with real recorded audio (ideally actual anonymised hearing
    audio, or at minimum human volunteers reading the same scripts) is the single
    highest-value improvement to this evaluation.
"""
from __future__ import annotations

import asyncio
import json
import logging
import sys
from pathlib import Path

DATA = Path(__file__).parent / "data"
AUDIO = DATA / "audio"
SESSION = DATA / "session"

TARGET_SR = 16000  # Whisper's native rate; pyannote resamples internally anyway

log = logging.getLogger("make_fixtures")

# ── Voices ────────────────────────────────────────────────────────────────────
# One voice per hearing participant. officer and client are both male, which is
# deliberate: two same-gender speakers is the harder diarization case and the one
# worth measuring. The interpreter uses a Turkish voice for its Dutch turns too
# (see module docstring).
VOICES = {
    "officer":     "nl-NL-MaartenNeural",  # male, Dutch
    "interpreter": "tr-TR-EmelNeural",     # female, Turkish — also voices the NL turns
    "client":      "tr-TR-AhmetNeural",    # male, Turkish
}

# ── Single-language clips for WER ─────────────────────────────────────────────
# Reference transcripts are the exact input text. Deliberately free of
# spelled-out years: Whisper renders "bin dokuz yüz seksen beş" as "1985", which
# shows up as several substitutions and would measure the number formatting
# rather than the transcription. Small number words that remain ("üç", "iki") are
# handled by the normaliser in wer_check.py.
TR_CLIPS = {
    "tr_01": "Benim adım Mehmet Yılmaz. Türkiye'de gazeteci olarak çalıştım. "
             "Yazdığım yazılar yüzünden birçok kez tehdit aldım.",
    "tr_02": "Bir sabah evime polis geldi ve beni gözaltına aldılar. "
             "Üç gün karakolda tutuldum ve sürekli sorguya çekildim. "
             "Avukatımla görüşmeme izin vermediler.",
    "tr_03": "Ailem hâlâ Türkiye'de yaşıyor. Eşim ve iki çocuğum var. "
             "Onlarla telefonla konuşuyorum ama hatlarımızın dinlendiğini düşünüyorum.",
    "tr_04": "Ülkeden çıkmak için önce İstanbul'a gittim. "
             "Sonra bir kamyonla sınıra yakın bir köye geçtim. "
             "Pasaportum yanımda değildi, çünkü polis almıştı.",
}

NL_CLIPS = {
    "nl_01": "Goedemorgen. Ik ben medewerker van de Immigratie- en Naturalisatiedienst. "
             "Ik ga u vandaag een aantal vragen stellen over uw asielaanvraag.",
    "nl_02": "Kunt u mij vertellen wanneer en waarom u uw land van herkomst heeft verlaten? "
             "Neemt u rustig de tijd om te antwoorden.",
    "nl_03": "U verklaarde dat u drie dagen bent vastgehouden. "
             "Weet u nog wanneer dat begon en wie u heeft verhoord? "
             "Alle details kunnen belangrijk zijn.",
    "nl_04": "Ik wil benadrukken dat alles wat u hier vertelt vertrouwelijk is. "
             "De tolk vertaalt alleen wat er gezegd wordt en geeft geen eigen mening.",
}

# ── 3-speaker session for DER ─────────────────────────────────────────────────
# Full bidirectional IND turn cycle:
#   officer(nl) -> interpreter(nl->tr) -> client(tr) -> interpreter(tr->nl) -> ...
SESSION_TURNS: list[tuple[str, str, str]] = [
    # (role, language, text)
    ("officer",     "nl", "Kunt u mij vertellen waarom u Turkije heeft verlaten?"),
    ("interpreter", "tr", "Türkiye'yi neden terk ettiğinizi bana anlatabilir misiniz?"),
    ("client",      "tr", "Gazeteci olarak çalıştığım için tutuklandım. Üç gün karakolda kaldım."),
    ("interpreter", "nl", "Ik ben gearresteerd omdat ik als journalist werkte. "
                          "Ik heb drie dagen op het politiebureau gezeten."),
    ("officer",     "nl", "Weet u nog wanneer dat gebeurde?"),
    ("interpreter", "tr", "Bunun ne zaman olduğunu hatırlıyor musunuz?"),
    ("client",      "tr", "Yaz aylarıydı, ağustos ayında oldu."),
    ("interpreter", "nl", "Het was in de zomer, het gebeurde in augustus."),
]

GAP_S = 0.35        # silence between consecutive turns
OVERLAP_TURN = 3    # this turn starts OVERLAP_S before the previous one ends
OVERLAP_S = 1.20    # -> interpreter begins rendering while the client is still talking


# ── Synthesis helpers ─────────────────────────────────────────────────────────

async def _tts_to_mp3(text: str, voice: str, dest: Path) -> None:
    import edge_tts

    dest.parent.mkdir(parents=True, exist_ok=True)
    await edge_tts.Communicate(text, voice).save(str(dest))


def _load_mono_16k(path: Path):
    """Decode (MP3 or WAV) -> mono float32 torch tensor at TARGET_SR."""
    import soundfile as sf
    import torch
    import torchaudio.functional as AF

    data, sr = sf.read(str(path), dtype="float32", always_2d=True)
    wav = torch.from_numpy(data.T)          # (channels, samples)
    if wav.shape[0] > 1:
        wav = wav.mean(dim=0, keepdim=True)
    if sr != TARGET_SR:
        wav = AF.resample(wav, sr, TARGET_SR)
    return wav


def _write_wav(path: Path, wav) -> None:
    import soundfile as sf

    path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(path), wav.squeeze(0).numpy(), TARGET_SR, subtype="PCM_16")


# Silence trimming is REQUIRED for the RTTM to be correct, not a nicety.
# edge-tts pads each utterance with ~0.2 s of leading and up to ~1.1 s of trailing
# silence. Placing untrimmed clips and then declaring "speaker X speaks from clip
# start to clip end" puts ~8.8 s of silence inside the reference speech regions
# across this session. pyannote's VAD correctly reports no speech there, and DER
# charges every one of those seconds as missed detection — inflating DER from
# ~0.1 to ~0.41 and attributing our own padding to the diarizer. Trim first so the
# ground truth marks speech.
_SIL_FRAME_S = 0.02   # 20 ms analysis frame
_SIL_REL_THR = 0.02   # frame counts as speech above 2% of the clip's peak frame RMS
_SIL_MARGIN_S = 0.05  # keep 50 ms either side so onsets/codas aren't clipped


def _trim_silence(wav):
    """Trim leading/trailing silence so a clip's duration equals its speech extent."""
    import numpy as np

    x = wav.squeeze(0).numpy()
    fl = int(_SIL_FRAME_S * TARGET_SR)
    n = len(x) // fl
    if n < 2:
        return wav

    frames = x[: n * fl].reshape(n, fl)
    rms = np.sqrt((frames.astype(np.float64) ** 2).mean(axis=1))
    thr = max(rms.max() * _SIL_REL_THR, 1e-4)
    voiced = np.flatnonzero(rms > thr)
    if voiced.size == 0:
        return wav

    margin = int(_SIL_MARGIN_S * TARGET_SR)
    start = max(0, voiced[0] * fl - margin)
    end = min(len(x), (voiced[-1] + 1) * fl + margin)
    return wav[:, start:end]


async def _synth_clip(clip_id: str, text: str, voice: str, out_dir: Path) -> float:
    """Synthesise one clip, write .wav + .txt, return duration in seconds."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        mp3 = Path(tmp) / f"{clip_id}.mp3"
        await _tts_to_mp3(text, voice, mp3)
        wav = _trim_silence(_load_mono_16k(mp3))

    _write_wav(out_dir / f"{clip_id}.wav", wav)
    (out_dir / f"{clip_id}.txt").write_text(text, encoding="utf-8")
    dur = wav.shape[-1] / TARGET_SR
    log.info("[clip] id=%s voice=%s dur=%.2fs chars=%d", clip_id, voice, dur, len(text))
    return dur


# ── Session assembly ──────────────────────────────────────────────────────────

async def _build_session() -> None:
    import tempfile

    import torch

    clips: list[dict] = []
    with tempfile.TemporaryDirectory() as tmp:
        for idx, (role, lang, text) in enumerate(SESSION_TURNS):
            mp3 = Path(tmp) / f"turn{idx}.mp3"
            await _tts_to_mp3(text, VOICES[role], mp3)
            # Trim before placing: the RTTM start/duration is derived from where each
            # clip lands, so padding inside a clip becomes silence inside a declared
            # speech region and is charged to the diarizer as missed detection.
            wav = _trim_silence(_load_mono_16k(mp3))
            clips.append({
                "index": idx, "role": role, "language": lang, "text": text,
                "voice": VOICES[role], "wav": wav,
                "duration": wav.shape[-1] / TARGET_SR,
            })

        # Lay turns out on a timeline. Every turn follows the previous one after
        # GAP_S, except OVERLAP_TURN which is pulled back so it starts while the
        # previous speaker is still going.
        cursor = 0.0
        for c in clips:
            if c["index"] == OVERLAP_TURN:
                prev = clips[c["index"] - 1]
                start = prev["start"] + prev["duration"] - OVERLAP_S
            else:
                start = cursor
            c["start"] = start
            c["end"] = start + c["duration"]
            cursor = max(cursor, c["end"]) + GAP_S

        total = max(c["end"] for c in clips)
        mix = torch.zeros(1, int(total * TARGET_SR) + TARGET_SR // 2)
        for c in clips:
            s = int(c["start"] * TARGET_SR)
            seg = c["wav"]
            mix[:, s:s + seg.shape[-1]] += seg          # additive -> real overlap

        peak = mix.abs().max().item()
        if peak > 0.99:                                  # only if mixing clipped
            mix = mix * (0.99 / peak)
            log.info("[session] peak=%.3f -> normalised", peak)

    _write_wav(SESSION / "session_3spk.wav", mix)

    # RTTM ground truth. Exact by construction: these are the offsets we placed
    # the clips at, not a human annotation.
    lines = [
        f"SPEAKER session_3spk 1 {c['start']:.3f} {c['duration']:.3f} "
        f"<NA> <NA> {c['role']} <NA> <NA>"
        for c in sorted(clips, key=lambda c: c["start"])
    ]
    (SESSION / "session_3spk.rttm").write_text("\n".join(lines) + "\n", encoding="utf-8")

    ov = clips[OVERLAP_TURN]
    prev = clips[OVERLAP_TURN - 1]
    overlap_region = {
        "start": round(ov["start"], 3),
        "end": round(prev["end"], 3),
        "speakers": [prev["role"], ov["role"]],
        "note": "Deliberate overlap: the interpreter starts rendering before the "
                "client has finished. Real hearings do this constantly; the rest "
                "of this session is artificially clean turn-taking.",
    }
    (SESSION / "session_3spk.script.json").write_text(
        json.dumps(
            {
                "sample_rate": TARGET_SR,
                "total_duration": round(total, 3),
                "gap_between_turns_s": GAP_S,
                "overlap_region": overlap_region,
                "voices": VOICES,
                "synthetic": True,
                "tts_engine": "edge-tts (Microsoft Edge neural TTS)",
                "turns": [
                    {k: (round(c[k], 3) if isinstance(c[k], float) else c[k])
                     for k in ("index", "role", "language", "voice", "start", "end", "duration", "text")}
                    for c in sorted(clips, key=lambda c: c["start"])
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    log.info("[session] turns=%d duration=%.2fs overlap=%.2f–%.2fs (%s)",
             len(clips), total, overlap_region["start"], overlap_region["end"],
             "+".join(overlap_region["speakers"]))


async def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    try:
        import edge_tts  # noqa: F401
    except ImportError:
        print("ERROR: edge-tts is not installed. Install the eval extra:\n"
              "         uv pip install -e '.[eval]'\n"
              "       or just:  uv pip install edge-tts", file=sys.stderr)
        return 1

    log.info("[make_fixtures] target_sr=%d out=%s", TARGET_SR, DATA)

    for clip_id, text in TR_CLIPS.items():
        await _synth_clip(clip_id, text, VOICES["client"], AUDIO)
    for clip_id, text in NL_CLIPS.items():
        await _synth_clip(clip_id, text, VOICES["officer"], AUDIO)

    await _build_session()

    log.info("[make_fixtures] DONE  tr_clips=%d  nl_clips=%d  session=1",
             len(TR_CLIPS), len(NL_CLIPS))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
