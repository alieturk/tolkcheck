"""Speaker-block alignment for bidirectional consecutive interpretation.

IND hearings follow a strict two-direction protocol:

  OFFICER (nl) → INTERPRETER (nl→tr, relay) → CLIENT (tr)
               → INTERPRETER (tr→nl)         → OFFICER (nl) → …

Three public functions:
  build_blocks        — merge consecutive same-speaker segments into blocks
  classify_directions — annotate each interpreter block as to_client / to_officer
  extract_pairs       — emit two separate pair lists (c2o and o2c)
"""
from __future__ import annotations

import logging

log = logging.getLogger(__name__)


# ── ASR reliability thresholds ────────────────────────────────────────────────
# Whisper's own decode-failure gates, reused here. faster-whisper applies
# logprob_threshold=-1.0 and compression_ratio_threshold=2.4 internally to decide
# whether to retry a temperature; a segment that ends up past them anyway is one
# the decoder itself considers bad. no_speech_prob catches text emitted over
# silence — the "Subtitles by the Amara.org community" class of hallucination.
LOGPROB_FLOOR        = -1.0
COMPRESSION_CEILING  = 2.4
NO_SPEECH_CEILING    = 0.6


# ── Pairing bounds ──────────────────────────────────────────────────────
# In consecutive interpretation the interpreter speaks directly after the turn
# being interpreted. On a real hearing the observed gap between a source block
# ending and its interpretation starting is under 3 s, and the source is one or
# two blocks back. An unbounded search silently produces pairs far outside that:
# on session f1fae5ce a closing "Hei bedankt u!" was matched to a client answer
# 33 s and eight blocks earlier, because the true source had been misattributed
# by diarization and was no longer available. The bounds are set well above
# normal spacing so only that failure mode trips them.
MAX_PAIR_GAP_S         = 20.0
MAX_PAIR_BLOCK_DISTANCE = 6


def _block_asr(segments: list[dict]) -> dict:
    """Aggregate per-segment decode signals over a block.

    Worst-case rather than mean: one hallucinated segment inside an otherwise
    clean block still makes the block's text untrustworthy, and averaging would
    hide it. `unreliable` is the flag downstream reads to decide a block should
    not be scored as if it were speech.
    """
    logprobs   = [s["avg_logprob"]       for s in segments if s.get("avg_logprob") is not None]
    compress   = [s["compression_ratio"] for s in segments if s.get("compression_ratio") is not None]
    no_speech  = [s["no_speech_prob"]    for s in segments if s.get("no_speech_prob") is not None]

    min_logprob   = min(logprobs)  if logprobs  else None
    max_compress  = max(compress)  if compress  else None
    max_no_speech = max(no_speech) if no_speech else None

    reasons: list[str] = []
    if min_logprob is not None and min_logprob < LOGPROB_FLOOR:
        reasons.append("low_logprob")
    if max_compress is not None and max_compress > COMPRESSION_CEILING:
        reasons.append("repetitive")
    if max_no_speech is not None and max_no_speech > NO_SPEECH_CEILING:
        reasons.append("no_speech")

    return {
        "min_avg_logprob":       min_logprob,
        "max_compression_ratio": max_compress,
        "max_no_speech_prob":    max_no_speech,
        "unreliable":            bool(reasons),
        "reasons":               reasons,
    }


# ── Public API ────────────────────────────────────────────────────────────────

def build_blocks(
    segments: list[dict],
    interpreter_speaker: str,
    client_speaker: str,
    gap_s: float = 3.0,
) -> list[dict]:
    """Merge consecutive same-speaker segments into speaker blocks.

    A new block starts when the speaker changes, the detected language
    changes, OR the gap between the end of the previous segment and the start
    of the next exceeds gap_s seconds.

    The language check matters because two diarization turns from the same
    speaker within gap_s of each other are transcribed independently (see
    pipeline.py's per-turn loop) and can genuinely disagree on detected
    language — e.g. the interpreter says something bilingual across a short
    pause, or one of the two turns was simply misdetected. Without this
    check they'd merge into one block carrying only the first turn's
    language tag (see below), and classify_directions — which reads that tag
    as its primary signal — would silently misclassify whichever part of the
    merged text didn't match it.

    Block shape::

        {
            "role":      "client" | "interpreter" | "officer",
            "speaker":   str,
            "start":     float,
            "end":       float,
            "text":      str,       # space-joined from all segments
            "language":  str,       # language of the first segment
            "direction": None,      # filled by classify_directions
            "segments":  list[dict],
        }
    """
    blocks: list[dict] = []
    for seg in sorted(segments, key=lambda s: s["start"]):
        role = _role(seg["speaker"], interpreter_speaker, client_speaker)

        if (blocks
                and blocks[-1]["speaker"] == seg["speaker"]
                and blocks[-1]["language"] == seg.get("language", "?")
                and seg["start"] - blocks[-1]["end"] <= gap_s):
            blocks[-1]["text"] += " " + seg["text"]
            blocks[-1]["end"] = seg["end"]
            blocks[-1]["segments"].append(seg)
        else:
            blocks.append({
                "role":      role,
                "speaker":   seg["speaker"],
                "start":     seg["start"],
                "end":       seg["end"],
                "text":      seg["text"],
                "language":  seg.get("language", "?"),
                "direction": None,
                "segments":  [seg],
                "asr":       None,   # filled after all segments are collected
            })

    for b in blocks:
        b["asr"] = _block_asr(b["segments"])
        if b["asr"]["unreliable"]:
            log.warning("build_blocks  UNRELIABLE  role=%-11s  %.1f–%.1fs  reasons=%s  "
                        "logprob=%s  compression=%s  no_speech=%s  %r",
                        b["role"], b["start"], b["end"], b["asr"]["reasons"],
                        b["asr"]["min_avg_logprob"], b["asr"]["max_compression_ratio"],
                        b["asr"]["max_no_speech_prob"],
                        b["text"][:60].replace(chr(10), " "))

    log.info("build_blocks  total=%d  unreliable=%d  speakers=%s",
             len(blocks),
             sum(1 for b in blocks if b["asr"]["unreliable"]),
             {r: sum(1 for b in blocks if b["role"] == r)
              for r in ("client", "interpreter", "officer")})
    for b in blocks:
        log.debug("build_blocks  block  role=%-11s  speaker=%-12s  %.1f–%.1fs  %r",
                  b["role"], b["speaker"], b["start"], b["end"],
                  b["text"][:60].replace("\n", " "))
    return blocks


def classify_directions(blocks: list[dict], client_lang: str) -> list[dict]:
    """Annotate each interpreter block with its translation direction.

    Primary signal: the block's own detected language (see build_blocks —
    every block carries the language Whisper detected for it).

    * language == client_lang → direction = "to_client"
      (interpreter switched into the client's language — relaying the
      officer's Dutch question so the client can respond)

    * language == "nl"        → direction = "to_officer"
      (interpreter switched into Dutch — translating the client's answer for
      the officer, the legally decisive direction)

    This is what the interpreter's own speech was detected as, not an
    inference from surrounding structure, so it survives diarization mistakes
    that the previous role-order-only heuristic did not (see
    TestClassifyDirections.test_language_overrides_next_role_heuristic for a
    concrete case this fixes).

    Fallback — used only when a block's language matches neither client_lang
    nor "nl" (a misdetected or unrecognised language): direction is inferred
    from the first non-interpreter block that follows, same as before this
    function took client_lang:

    * next role == "client"  → direction = "to_client"
    * next role == "officer" or no next → direction = "to_officer"

    Mutates and returns the same list.
    """
    for i, block in enumerate(blocks):
        if block["role"] != "interpreter":
            continue

        lang = block["language"]
        if lang == client_lang:
            block["direction"] = "to_client"
        elif lang == "nl":
            block["direction"] = "to_officer"
        else:
            next_role: str | None = None
            for j in range(i + 1, len(blocks)):
                if blocks[j]["role"] != "interpreter":
                    next_role = blocks[j]["role"]
                    break
            block["direction"] = "to_client" if next_role == "client" else "to_officer"
            log.warning(
                "classify_directions  interpreter  %.1f–%.1fs  language=%r matches neither "
                "client_lang=%r nor 'nl' — falling back to next-role heuristic (result=%s)",
                block["start"], block["end"], lang, client_lang, block["direction"],
            )

        log.info("classify_directions  interpreter  %.1f–%.1fs  language=%s  direction=%s",
                 block["start"], block["end"], lang, block["direction"])

    return blocks


def extract_pairs(
    blocks: list[dict],
) -> tuple[list[dict], list[dict]]:
    """Build two separate pair lists from classified blocks.

    Returns ``(c2o_pairs, o2c_pairs)``.

    **c2o_pairs** (client → officer, highest legal priority):
      Each ``to_officer`` interpreter block is paired with the nearest preceding
      client block.

    **o2c_pairs** (officer → client, relay quality):
      Each ``to_client`` interpreter block is paired with the nearest preceding
      officer block.

    Pair shape (identical for both lists)::

        {
            "direction":    "client_to_officer" | "officer_to_client",
            "source_block": dict,   # client block (c2o) or officer block (o2c)
            "interp_block": dict,
            "pair_index":   int,    # index within its own list
        }

    Note ``pair_index`` is per-direction: a c2o pair and an o2c pair can both
    carry index 0. Anything keying on it (scores, translations, LLM issues)
    must key on ``(direction, pair_index)``, never on pair_index alone.

    As a side effect each paired interpreter block is annotated in place with
    ``pair_index`` and ``source_index`` (the position of its source block in
    ``blocks``). That makes the block list stored in Evaluation.aligned_blocks
    self-sufficient: a consumer holding only the blocks can reconstruct every
    pair without re-deriving the pairing rules. Interpreter blocks that could
    not be paired keep ``pair_index``/``source_index`` unset.
    """
    c2o_pairs: list[dict] = []
    o2c_pairs: list[dict] = []

    for i, block in enumerate(blocks):
        if block["role"] != "interpreter":
            continue

        if block["direction"] == "to_officer":
            src_i = _find_preceding(blocks, i, "client")
            if src_i is None:
                log.warning("extract_pairs  to_officer block at %.1fs has no preceding client block — skipped",
                            block["start"])
                continue
            source = blocks[src_i]
            block["pair_index"]   = len(c2o_pairs)
            block["source_index"] = src_i
            pair: dict = {
                "direction":    "client_to_officer",
                "source_block": source,
                "interp_block": block,
                "pair_index":   len(c2o_pairs),
            }
            c2o_pairs.append(pair)
            log.info("extract_pairs  c2o[%d]  client=%.1fs %r  →  interp=%.1fs %r",
                     pair["pair_index"],
                     source["start"], source["text"][:60].replace("\n", " "),
                     block["start"],  block["text"][:60].replace("\n", " "))

        elif block["direction"] == "to_client":
            src_i = _find_preceding(blocks, i, "officer")
            if src_i is None:
                log.warning("extract_pairs  to_client block at %.1fs has no preceding officer block — skipped",
                            block["start"])
                continue
            source = blocks[src_i]
            block["pair_index"]   = len(o2c_pairs)
            block["source_index"] = src_i
            pair = {
                "direction":    "officer_to_client",
                "source_block": source,
                "interp_block": block,
                "pair_index":   len(o2c_pairs),
            }
            o2c_pairs.append(pair)
            log.info("extract_pairs  o2c[%d]  officer=%.1fs %r  →  interp=%.1fs %r",
                     pair["pair_index"],
                     source["start"], source["text"][:60].replace("\n", " "),
                     block["start"],  block["text"][:60].replace("\n", " "))

    log.info("extract_pairs  c2o_pairs=%d  o2c_pairs=%d", len(c2o_pairs), len(o2c_pairs))
    return c2o_pairs, o2c_pairs


# ── Internal helpers ──────────────────────────────────────────────────────────

def _role(speaker: str, interpreter_speaker: str, client_speaker: str) -> str:
    if speaker == interpreter_speaker:
        return "interpreter"
    if speaker == client_speaker:
        return "client"
    return "officer"


def _find_preceding(blocks: list[dict], from_index: int, role: str) -> int | None:
    """Index of the nearest block before from_index with this role, or None.

    Bounded by MAX_PAIR_BLOCK_DISTANCE and MAX_PAIR_GAP_S (see above): a match
    further back than either is treated as no match at all. Returning nothing is
    the right answer when the real source is missing — an unpaired interpreter
    turn is visible as such, whereas a pair built from an unrelated block reads
    as a confident finding about the interpreter.
    """
    interp_start = blocks[from_index]["start"]

    for j in range(from_index - 1, -1, -1):
        if from_index - j > MAX_PAIR_BLOCK_DISTANCE:
            return None
        if blocks[j]["role"] != role:
            continue
        gap = interp_start - blocks[j]["end"]
        if gap > MAX_PAIR_GAP_S:
            log.warning(
                "_find_preceding  nearest %s block for the interpreter turn at %.1fs "
                "ended %.1fs earlier (limit %.1fs) — left unpaired",
                role, interp_start, gap, MAX_PAIR_GAP_S,
            )
            return None
        return j
    return None
