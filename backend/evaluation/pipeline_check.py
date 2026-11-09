"""DEMO check of the whole pipeline on the labelled synthetic sessions (S20-S24).

Pushes each session's audio through the REAL backend and worker via the API (the
stack from eval/t8_privacy.py), then compares what the pipeline produced with the
labels in the session JSON. This is a sanity check, not a DV4 measurement: the
sessions are dev and unreviewed, so the report is always marked DEMO / "niet geldig
als resultaat". Nothing is calibrated and no code in app/ changes.

Run from backend/ (Postgres with pgvector on localhost:5433, as for T8):

    uv run --with "fakeredis[lua]==2.38.0" --with jiwer python evaluation/pipeline_check.py
    uv run --with "fakeredis[lua]==2.38.0" --with jiwer python evaluation/pipeline_check.py --sessions S20
    uv run --with jiwer python evaluation/pipeline_check.py --from-raw results/<map>/raw   # report only

Test-environment settings, as in T8: its own database (dropped and recreated each
run), fakeredis, COOKIE_SECURE=false and a work dir outside the repo. Unlike T8 the
Claude step is real: ANTHROPIC_API_KEY comes from backend/.env, with the current
defaults (LLM_SCORE_RULES=false, LLM_TEMPERATURE=0; pass --llm-score-rules true for
the variant with LaBSE rules). The knowledge base is ingested, because retrieval is
part of the feedback step. Only dev sessions are run; others are skipped.

How pipeline output is tied to the labels
-----------------------------------------
There are no timestamps in the JSON, so everything is matched on text:

* Roles: each diarization label gets the role whose JSON utterances, in the language
  Whisper detected, share the most words with that label's segments. The report
  states that roles were set this way, which a human reviewer would otherwise do.
* Pairs: each JSON pair goes to the pipeline pair of the same direction whose source
  block is most similar to the JSON source (difflib ratio on normalised text).

LaBSE scores: the pipeline stores only client->officer scores
(``semantic_similarity_scores``). The officer->client scores are computed and given
to the LLM but never stored, so they are read from the worker log.

Reporting constants, fixed before the first run: ``MIN_MATCH`` and ``HIGH_WER``
decide what counts as found or high, and the similarity and WER are always shown
next to them. The flag definitions are fixed by the assignment.
"""
from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import difflib
import itertools
import json
import os
import re
import secrets
import socket
import subprocess
import sys
import time
from dataclasses import asdict
from pathlib import Path

from dotenv import dotenv_values

import detection_check
from _common import RAN, RESULTS_DIR, md_table, mean, normalise_text, setup_logging
from detection_check import CATEGORY_NL, _ci, _fmt
from metrics import Counts, wilson
from sessions import CATEGORIES, Pair, Session, load_sessions

EVAL_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(EVAL_DIR.parents[1] / "eval"))
from t8_privacy import (  # noqa: E402
    API_PORT,
    BACKEND,
    REDIS_PORT,
    REPO,
    WORKER_LAUNCHER,
    poll,
    start_fake_redis,
    wait_for_line,
    wait_port,
)

NAME = "pipeline_check"
LABELS_DIR = detection_check.SESSIONS_DIR
AUDIO_DIR = REPO.parent / "sessions"
DEFAULT_WORKDIR = Path.home() / "tolkcheck-pipeline-check"
DB_NAME = "tolkcheck_pipeline_check"
PG_ADMIN = "postgresql://postgres:postgres@localhost:5433/postgres"
DB_URL = f"postgresql+asyncpg://postgres:postgres@localhost:5433/{DB_NAME}"
# Settings taken from backend/.env, so this runs the current configuration.
ENV_FROM_DOTENV = ("HF_TOKEN", "ANTHROPIC_API_KEY", "LLM_MODEL",
                   "WHISPER_MODEL", "WHISPER_DEVICE", "WHISPER_COMPUTE_TYPE")

# Fixed by the assignment; do not change.
LABSE_FLAG_BELOW = 0.70
LLM_FLAG_SEVERITIES = {"high", "critical"}
LLM_NOT_A_FLAG_TYPE = "false-negative"

MIN_MATCH = 0.50       # below this difflib ratio a JSON source counts as not found
MIN_CONTAINED = 0.60   # share of JSON source words inside a longer, merged block
HIGH_WER = 0.30

# The worker needs the torchcodec stub that scripts in evaluation/ get from _common
# on a machine without FFmpeg shared libraries (see README "Environment notes").
_STUB_PREFIX = f"import sys; sys.path.insert(0, {str(EVAL_DIR)!r}); import _common\n"
WORKER_WITH_STUB = _STUB_PREFIX + WORKER_LAUNCHER
INGEST_KNOWLEDGE = _STUB_PREFIX + (
    "import asyncio; from pathlib import Path; from app.cli import _ingest_knowledge; "
    "asyncio.run(_ingest_knowledge(Path('knowledge_base')))"
)
CREATE_USER = ("import asyncio,sys; from app.cli import _create_user; "
               "asyncio.run(_create_user(sys.argv[1], sys.argv[2]))")

_SCORE_LINE = re.compile(r"\[B\] (c2o|o2c)_score\[(\d+)\]\s+(-?\d+\.\d+)")
_API_DIRECTION = {"nl->tr": "officer_to_client", "tr->nl": "client_to_officer"}
_SOURCE_ROLE = {"nl->tr": "officer", "tr->nl": "client"}


# ── Text comparison ──────────────────────────────────────────────────────────

def similarity(a: str, b: str) -> float:
    """difflib ratio (0-1) of two texts after the WER normalisation."""
    return difflib.SequenceMatcher(None, normalise_text(a), normalise_text(b), autojunk=False).ratio()


def _shared_words(a: list[str], b: list[str]) -> int:
    matcher = difflib.SequenceMatcher(None, a, b, autojunk=False)
    return sum(m.size for m in matcher.get_matching_blocks())


def contained_share(needle: str, haystack: str) -> float:
    """Share of the words of `needle` found, in order, inside `haystack`."""
    words = normalise_text(needle).split()
    return _shared_words(words, normalise_text(haystack).split()) / len(words) if words else 0.0


def word_error_rate(reference: str, hypothesis: str) -> float:
    from wer_check import _score

    return _score(reference, hypothesis)["wer"]


# ── Roles ────────────────────────────────────────────────────────────────────

def _role_utterances(pairs: list[Pair]) -> dict[str, dict[str, list[list[str]]]]:
    """Per role and language, the JSON utterances as word lists."""
    roles: dict[str, dict[str, list[list[str]]]] = {"officer": {}, "client": {}, "interpreter": {}}
    for p in pairs:
        roles[_SOURCE_ROLE[p.direction]].setdefault(p.source_lang, []).append(
            normalise_text(p.source_text).split())
        roles["interpreter"].setdefault(p.target_lang, []).append(
            normalise_text(p.rendering_text).split())
    return roles


def choose_roles(transcript: list[dict], pairs: list[Pair]) -> dict:
    """Give each diarization label the role it overlaps most with in language and text.

    Overlap of a label with a role: for every segment of that label, the words shared
    with the best JSON utterance of that role in the segment's detected language,
    summed. Each role goes to one label; the combination with the largest total wins.
    """
    utterances = _role_utterances(pairs)
    labels = sorted({s["speaker"] for s in transcript})
    overlap: dict[str, dict[str, int]] = {label: dict.fromkeys(utterances, 0) for label in labels}
    languages: dict[str, dict[str, int]] = {label: {} for label in labels}
    for seg in transcript:
        lang = seg.get("language", "?")
        languages[seg["speaker"]][lang] = languages[seg["speaker"]].get(lang, 0) + 1
        words = normalise_text(seg["text"]).split()
        for role, by_lang in utterances.items():
            overlap[seg["speaker"]][role] += max(
                (_shared_words(words, u) for u in by_lang.get(lang, [])), default=0)

    slots = labels + [None] * max(0, 3 - len(labels))
    best, best_total = None, -1
    for officer, client, interpreter in itertools.permutations(slots, 3):
        total = sum(overlap[label][role] for label, role in (
            (officer, "officer"), (client, "client"), (interpreter, "interpreter")) if label)
        if total > best_total:
            best, best_total = (officer, client, interpreter), total
    officer, client, interpreter = best
    return {"officer": officer, "client": client, "interpreter": interpreter,
            "word_overlap": overlap, "languages": languages,
            "rule": "automatisch: per label de rol met de meeste woordoverlap met de JSON, "
                    "in de door Whisper herkende taal"}


# ── Reading the pipeline's output ────────────────────────────────────────────

def pipeline_pairs(blocks: list[dict]) -> list[dict]:
    """The pipeline's pairs, rebuilt from the links alignment stored on the blocks."""
    out = []
    for block in blocks:
        if block.get("role") != "interpreter" or block.get("source_index") is None:
            continue
        direction = "tr->nl" if block.get("direction") == "to_officer" else "nl->tr"
        out.append({"direction": direction, "pair_index": block["pair_index"],
                    "source_index": block["source_index"],
                    "source": blocks[block["source_index"]], "interp": block})
    return out


def score_lines(log_text: str) -> dict[str, dict[int, float]]:
    """``[B] c2o_score[i]`` / ``o2c_score[i]`` from one session's part of the worker log."""
    out: dict[str, dict[int, float]] = {"c2o": {}, "o2c": {}}
    for kind, index, value in _SCORE_LINE.findall(log_text):
        out[kind][int(index)] = float(value)
    return out


def llm_issues_by_pair(structured: list[dict] | None) -> dict[tuple[str, int], list[dict]]:
    out: dict[tuple[str, int], list[dict]] = {}
    for entry in structured or []:
        if isinstance(entry, dict) and entry.get("pair_index") is not None:
            out[(entry.get("direction"), int(entry["pair_index"]))] = entry.get("issues") or []
    return out


def llm_flagged(issues: list[dict]) -> bool:
    return any(i.get("severity") in LLM_FLAG_SEVERITIES and i.get("type") != LLM_NOT_A_FLAG_TYPE
               for i in issues)


def is_unassessable(source: dict, interp: dict) -> bool:
    """The rule of pipeline._pair_unassessable, on the blocks the API returns."""
    return any((b.get("asr") or {}).get("unreliable") for b in (source, interp))


def _pipeline_score(raw: dict, candidate: dict) -> float | None:
    stored = candidate["interp"].get("similarity_score")
    if stored is not None:
        return float(stored)
    index = candidate["pair_index"]  # runs from before the score was kept on the block
    if candidate["direction"] == "tr->nl":
        scores = (raw.get("evaluation") or {}).get("semantic_similarity_scores") or []
        return float(scores[index]) if index < len(scores) else None
    # JSON turned the integer keys into strings if this raw file was read back.
    o2c = raw.get("o2c_scores") or {}
    value = o2c.get(index, o2c.get(str(index)))
    return None if value is None else float(value)


# ── Comparing with the labels ────────────────────────────────────────────────

def _best_match(pair: Pair, candidates: list[dict]) -> tuple[dict | None, float]:
    """Highest source similarity; a tie (one source, two renderings) goes on the rendering."""
    best, best_key = None, (-1.0, -1.0)
    for c in candidates:
        key = (similarity(pair.source_text, c["source"]["text"]),
               similarity(pair.rendering_text, c["interp"]["text"]))
        if key > best_key:
            best, best_key = c, key
    return best, max(best_key[0], 0.0)


def _why_not_found(pair: Pair, blocks: list[dict], other_sim: float) -> str:
    if other_sim >= MIN_MATCH:
        return f"verkeerde richting: brontekst staat in een paar van de andere richting ({other_sim:.2f})"
    if not blocks:
        return "geen blokken in de evaluatie"
    expected = _SOURCE_ROLE[pair.direction]
    best = max(blocks, key=lambda b: similarity(pair.source_text, b["text"]))
    best_sim = similarity(pair.source_text, best["text"])
    if best_sim >= MIN_MATCH:
        if best["role"] != expected:
            return (f"diarisatie/rol: brontekst staat in een blok met rol {best['role']}, "
                    f"verwacht {expected} ({best_sim:.2f})")
        return f"koppeling: brontekst staat in een {expected}-blok zonder vertolking ({best_sim:.2f})"
    widest = max(blocks, key=lambda b: contained_share(pair.source_text, b["text"]))
    share = contained_share(pair.source_text, widest["text"])
    if share >= MIN_CONTAINED:
        return (f"samengevoegd: {share:.0%} van de bronwoorden zit in een langer "
                f"{widest['role']}-blok")
    return f"transcriptie: brontekst niet herkend (beste overeenkomst {best_sim:.2f})"


def evaluate_session(session: Session, raw: dict, layer1: dict[str, float]) -> tuple[list[dict], dict]:
    """One row per JSON pair, plus the per-session figures."""
    evaluation = raw.get("evaluation") or {}
    blocks = evaluation.get("aligned_blocks") or []
    candidates = pipeline_pairs(blocks)
    issues = llm_issues_by_pair(evaluation.get("structured_issues"))
    completed = raw.get("status") == "completed"

    rows: list[dict] = []
    for p in session.pairs:
        row = {
            "pair_id": p.pair_id, "session_id": p.session_id, "label": p.label,
            "category": p.category, "expected_flag": p.expected_flag, "direction": p.direction,
            "found": False, "direction_ok": None, "match_similarity": None,
            "wer_source": None, "wer_rendering": None, "pipeline_labse": None,
            "layer1_labse": layer1.get(p.pair_id), "unassessable": None, "llm_issues": [],
            "labse_flagged": False, "llm_flagged": False, "loss_reason": None,
            "pipeline_index": None, "shared_match": False,
        }
        rows.append(row)
        if not completed:
            row["loss_reason"] = f"sessie niet voltooid ({raw.get('status')}: {raw.get('error')})"
            continue

        same, same_sim = _best_match(p, [c for c in candidates if c["direction"] == p.direction])
        _other, other_sim = _best_match(p, [c for c in candidates if c["direction"] != p.direction])
        row["match_similarity"] = same_sim
        row["direction_ok"] = same_sim >= other_sim
        if same is None or same_sim < MIN_MATCH or not row["direction_ok"]:
            row["loss_reason"] = _why_not_found(p, blocks, other_sim)
            continue

        score = _pipeline_score(raw, same)
        pair_issues = issues.get((_API_DIRECTION[p.direction], same["pair_index"]), [])
        row.update({
            "found": True,
            "pipeline_index": same["pair_index"],
            "wer_source": word_error_rate(p.source_text, same["source"]["text"]),
            "wer_rendering": word_error_rate(p.rendering_text, same["interp"]["text"]),
            "pipeline_labse": score,
            "unassessable": is_unassessable(same["source"], same["interp"]),
            "llm_issues": [{"type": i.get("type"), "severity": i.get("severity")} for i in pair_issues],
            "labse_flagged": score is not None and score < LABSE_FLAG_BELOW,
            "llm_flagged": llm_flagged(pair_issues),
            "pipeline_source": same["source"]["text"],
            "pipeline_rendering": same["interp"]["text"],
            "source_language": same["source"].get("language"),
            "rendering_language": same["interp"].get("language"),
            "renderings_for_source": sum(
                1 for c in candidates if c["source_index"] == same["source_index"]),
        })

    taken: dict[tuple, int] = {}
    for r in rows:
        if r["found"]:
            key = (r["direction"], r["pipeline_index"])
            taken[key] = taken.get(key, 0) + 1
    for r in rows:
        if r["found"] and taken[(r["direction"], r["pipeline_index"])] > 1:
            r["shared_match"] = True

    warnings = (evaluation.get("role_warnings") or {}).get("warnings") or []
    stats = {
        "session_id": session.session_id,
        "status": raw.get("status"),
        "error": raw.get("error"),
        "speakers": len({s["speaker"] for s in raw.get("phase_a_transcript") or []}),
        "role_warnings_ok": (evaluation.get("role_warnings") or {}).get("ok"),
        "role_warnings": warnings,
        "unpaired_interpreter_blocks": sum(
            1 for b in blocks if b.get("role") == "interpreter" and b.get("source_index") is None),
        "pairs_without_match": sum(1 for r in rows if not r["found"]),
        "roles": raw.get("roles"),
    }
    return rows, stats


# ── Summaries ────────────────────────────────────────────────────────────────

def flag_counts(rows: list[dict], flagged) -> Counts:
    tp = sum(1 for r in rows if r["expected_flag"] and flagged(r))
    fn = sum(1 for r in rows if r["expected_flag"] and not flagged(r))
    fp = sum(1 for r in rows if not r["expected_flag"] and flagged(r))
    tn = sum(1 for r in rows if not r["expected_flag"] and not flagged(r))
    return Counts(tp, fn, fp, tn)


def layer1_flagged(row: dict) -> bool:
    return row["layer1_labse"] is not None and row["layer1_labse"] < LABSE_FLAG_BELOW


def transcript_damaged(row: dict) -> bool:
    """The pair's text is not what was said, so a flag on it says little about the interpreter."""
    return row["found"] and (row["wer_source"] > HIGH_WER or row["wer_rendering"] > HIGH_WER
                             or bool(row["unassessable"]))


def pair_problems(row: dict) -> str:
    """Why a matched pair lost quality in an earlier step, in words."""
    parts = []
    if row["wer_source"] > HIGH_WER:
        parts.append(f"bron WER {row['wer_source']:.2f} (herkend als {row['source_language']})")
    if row["wer_rendering"] > HIGH_WER:
        parts.append(f"vertolking WER {row['wer_rendering']:.2f} (herkend als {row['rendering_language']})")
    if row["unassessable"]:
        parts.append("ASR onbetrouwbaar")
    if row["renderings_for_source"] > 1:
        parts.append(f"vertolking verdeeld over {row['renderings_for_source']} tolkblokken")
    return "; ".join(parts)


def _rate(k: int, n: int) -> str:
    return f"{k}/{n} = {k / n:.2f} ({_ci(wilson(k, n))})" if n else "–"


def _loss_steps() -> list[tuple[str, callable]]:
    return [
        ("Niet gevonden (geen transcriptie, rol of koppeling)",
         lambda r: not r["found"] and "verkeerde richting" not in (r["loss_reason"] or "")),
        ("Verkeerde richting", lambda r: not r["found"] and "verkeerde richting" in (r["loss_reason"] or "")),
        (f"Hoge WER bron (> {HIGH_WER:.2f})", lambda r: r["found"] and r["wer_source"] > HIGH_WER),
        (f"Hoge WER vertolking (> {HIGH_WER:.2f})", lambda r: r["found"] and r["wer_rendering"] > HIGH_WER),
        ("Onbeoordeelbaar (ASR onbetrouwbaar)", lambda r: r["found"] and r["unassessable"]),
        ("Alle stappen zonder probleem", lambda r: r["found"] and r["wer_source"] <= HIGH_WER
         and r["wer_rendering"] <= HIGH_WER and not r["unassessable"]),
    ]


def summarise(rows: list[dict]) -> dict:
    found = [r for r in rows if r["found"]]
    detectors = {
        "Laag 1 LaBSE (JSON-tekst)": layer1_flagged,
        "Pipeline LaBSE (< 0.70)": lambda r: r["labse_flagged"],
        "Pipeline taalmodel (high/critical)": lambda r: r["llm_flagged"],
    }
    summary: dict = {"n": len(rows), "n_found": len(found), "steps": {}, "detection": {}}
    for name, test in _loss_steps():
        summary["steps"][name] = {
            "alle": sum(1 for r in rows if test(r)),
            "afwijkingen": sum(1 for r in rows if test(r) and r["expected_flag"]),
            "controles": sum(1 for r in rows if test(r) and not r["expected_flag"]),
        }
    for name, flagged in detectors.items():
        summary["detection"][name] = {
            "alle_paren": asdict(flag_counts(rows, flagged)),
            "gekoppeld": asdict(flag_counts(found, flagged)),
            "per_categorie": {c: sum(1 for r in rows if r["category"] == c and flagged(r))
                              for c in CATEGORIES},
        }
    return summary


# ── Report ───────────────────────────────────────────────────────────────────

def _yes(value) -> str:
    return "–" if value is None else ("ja" if value else "nee")


def _issues_text(issues: list[dict]) -> str:
    return ", ".join(f"{i['type']}/{i['severity']}" for i in issues) or "–"


def _warnings_text(stats: dict) -> str:
    if stats["role_warnings_ok"] is None:
        return "–"
    if not stats["role_warnings"]:
        return "geen"
    return "; ".join(f"{w.get('code')} ({w.get('severity')}, {w.get('speaker')})" for w in stats["role_warnings"])


def _session_table(all_stats: list[dict]) -> str:
    rows = []
    for s in all_stats:
        roles = s["roles"] or {}
        rows.append([s["session_id"], s["status"], s["speakers"], _warnings_text(s),
                     s["unpaired_interpreter_blocks"], s["pairs_without_match"],
                     f"ambtenaar={roles.get('officer')}, cliënt={roles.get('client')}, "
                     f"tolk={roles.get('interpreter')}"])
    return md_table(["Sessie", "Status", "Sprekers", "role_warnings", "Ongekoppelde tolkblokken",
                     "JSON-paren zonder match", "Automatisch gegeven rollen"], rows)


def _pair_table(rows: list[dict]) -> str:
    return md_table(
        ["Paar", "Label", "Verwacht", "Gevonden", "Richting ok", "Overeenkomst", "WER bron", "WER vert.",
         "LaBSE pipeline", "LaBSE laag 1", "Onbeoordeelbaar", "Meldingen taalmodel",
         "Sign. LaBSE", "Sign. taalmodel"],
        [[r["pair_id"] + (" (*)" if r["shared_match"] else ""), r["label"], _yes(r["expected_flag"]),
          _yes(r["found"]), _yes(r["direction_ok"]), _fmt(r["match_similarity"]), _fmt(r["wer_source"]),
          _fmt(r["wer_rendering"]), _fmt(r["pipeline_labse"]), _fmt(r["layer1_labse"]),
          _yes(r["unassessable"]), _issues_text(r["llm_issues"]),
          _yes(r["labse_flagged"]) if r["found"] else "–", _yes(r["llm_flagged"]) if r["found"] else "–"]
         for r in rows])


def _steps_table(summary: dict) -> str:
    return md_table(["Stap", "Alle paren", "Afwijkingen", "Controles"],
                    [[name, v["alle"], v["afwijkingen"], v["controles"]]
                     for name, v in summary["steps"].items()])


def _detection_table(rows: list[dict], only_found: bool) -> str:
    subset = [r for r in rows if r["found"]] if only_found else rows
    table = []
    for name, flagged in (("Laag 1 LaBSE (JSON-tekst)", layer1_flagged),
                          ("Pipeline LaBSE (< 0.70)", lambda r: r["labse_flagged"]),
                          ("Pipeline taalmodel (high/critical)", lambda r: r["llm_flagged"])):
        c = flag_counts(subset, flagged)
        table.append([name, _rate(c.tp, c.tp + c.fn), _rate(c.fp, c.fp + c.tn)])
    return md_table(["Detector", "Recall (95% Wilson)", "Valse alarmen (95% Wilson)"], table)


def _damaged_flags_table(rows: list[dict]) -> str:
    table = []
    for name, flagged in (("Pipeline LaBSE (< 0.70)", lambda r: r["labse_flagged"]),
                          ("Pipeline taalmodel (high/critical)", lambda r: r["llm_flagged"])):
        hits = [r for r in rows if flagged(r)]
        damaged = [r for r in hits if transcript_damaged(r)]
        table.append([name, len(hits), len(damaged),
                      sum(1 for r in damaged if r["expected_flag"]),
                      sum(1 for r in damaged if not r["expected_flag"])])
    return md_table(["Detector", "Signaleringen", "Waarvan op beschadigde transcriptie",
                     "… op een afwijking", "… op een controle"], table)


def _damaged_pairs_table(rows: list[dict]) -> str:
    damaged = [r for r in rows if r["found"] and (transcript_damaged(r) or r["renderings_for_source"] > 1)]
    if not damaged:
        return "Geen.\n"
    return md_table(["Paar", "Label", "Probleem", "LaBSE pipeline", "LaBSE laag 1", "Meldingen taalmodel"],
                    [[r["pair_id"], r["label"], pair_problems(r), _fmt(r["pipeline_labse"]),
                      _fmt(r["layer1_labse"]), _issues_text(r["llm_issues"])] for r in damaged])


def _category_table(rows: list[dict]) -> str:
    table = []
    for c in CATEGORIES:
        subset = [r for r in rows if r["category"] == c]
        table.append([CATEGORY_NL[c], len(subset),
                      sum(1 for r in subset if layer1_flagged(r)),
                      sum(1 for r in subset if r["labse_flagged"]),
                      sum(1 for r in subset if r["llm_flagged"])])
    return md_table(["Categorie", "n", "Laag 1 LaBSE", "Pipeline LaBSE", "Pipeline taalmodel"], table)


def _layer_difference(rows: list[dict]) -> str:
    table = []
    for direction, method in (("nl->tr", "cross-lingual, gelijk aan laag 1"),
                              ("tr->nl", "via Claude-vertaling naar Nederlands (pseudo-referentie)")):
        both = [r for r in rows if r["direction"] == direction and r["pipeline_labse"] is not None
                and r["layer1_labse"] is not None]
        if both:
            deltas = [r["pipeline_labse"] - r["layer1_labse"] for r in both]
            table.append([direction, method, len(both), mean([r["layer1_labse"] for r in both]),
                          mean([r["pipeline_labse"] for r in both]), mean(deltas), min(deltas), max(deltas)])
    text = md_table(["Richting", "Methode pipeline", "n", "gem. laag 1", "gem. pipeline",
                     "gem. verschil", "min", "max"], table) if table else "(geen gekoppelde paren)"
    changed = [[r["pair_id"], r["label"], _fmt(r["layer1_labse"]), _fmt(r["pipeline_labse"]),
                _yes(layer1_flagged(r)), _yes(r["labse_flagged"])]
               for r in rows if r["found"] and layer1_flagged(r) != r["labse_flagged"]]
    text += "\n\n**Paren waar de LaBSE-signalering verschilt**\n\n"
    text += md_table(["Paar", "Label", "Score laag 1", "Score pipeline", "Laag 1 gesignaleerd",
                      "Pipeline gesignaleerd"], changed) if changed else "Geen.\n"
    return text


def render(rows: list[dict], all_stats: list[dict], summary: dict, meta: dict) -> str:
    lost = [r for r in rows if not r["found"]]
    md = [
        "# DEMO — niet geldig als resultaat: pipelinecontrole S20–S24 "
        f"({dt.date.today().isoformat()})\n",
        "> **Niet geldig als resultaat.** Controle van de werking op synthetische dev-sessies die "
        "nog niet zijn nagekeken. Geen meting voor DV4. Er is niets afgesteld.\n",
        f"**Opzet:** echte backend en worker via de API. Run `{meta.get('label') or 'standaard'}`: "
        f"LLM_SCORE_RULES={meta.get('llm_score_rules', '?')}, "
        f"LLM_TEMPERATURE=0, model `{meta.get('llm_model')}`, Whisper `{meta.get('whisper_model')}`. "
        f"Commit `{meta.get('commit')}`"
        f"{', met niet-gecommitte wijzigingen in backend/app (zie app.diff)' if meta.get('app_diff') else ''}.\n",
        "**Rollen zijn automatisch gegeven**, op basis van de overlap met de JSON (zie tabel), niet "
        "door een mens. Een rolfout van een echte gebruiker valt hier dus buiten.\n",
        f"**Definities:** gevonden = bronuiting binnen dezelfde richting met overeenkomst ≥ {MIN_MATCH:.2f}. "
        f"Hoge WER = > {HIGH_WER:.2f}. Gesignaleerd LaBSE = score < {LABSE_FLAG_BELOW:.2f}. Gesignaleerd "
        "taalmodel = melding met severity high of critical, type niet false-negative. Niet gevonden paren "
        "tellen niet als gesignaleerd.\n",
        "**LaBSE-scores in de pipeline:** cliënt→ambtenaar komt uit `semantic_similarity_scores`, "
        "ambtenaar→cliënt uit het workerlog, omdat de pipeline die niet opslaat.\n",
        "## Per sessie\n", _session_table(all_stats),
        "\n## Waar het misgaat\n", _steps_table(summary),
        f"\n\n{summary['n_found']} van de {summary['n']} JSON-paren zijn gekoppeld.\n",
        "\n## Detectie, end-to-end (alle JSON-paren)\n", _detection_table(rows, only_found=False),
        "\n\n## Detectie, alleen gekoppelde paren\n", _detection_table(rows, only_found=True),
        "\n\n## Signaleringen op een beschadigde transcriptie\n",
        "Een signalering op een pair met hoge WER of onbetrouwbare ASR kan door de transcriptie komen "
        "in plaats van door de vertolking, ook als het label toevallig klopt.\n",
        _damaged_flags_table(rows),
        "\n\n## Gesignaleerde afwijkingen per categorie\n", _category_table(rows),
        "\n\n## Verloren paren\n",
        md_table(["Paar", "Label", "Reden"], [[r["pair_id"], r["label"], r["loss_reason"]] for r in lost])
        if lost else "Geen.\n",
        "\n\n## Gekoppeld, maar met verlies in een eerdere stap\n", _damaged_pairs_table(rows),
        "\n\n## Laag 1 tegenover de pipeline\n", _layer_difference(rows),
        "\n\n## Per paar\n", _pair_table(rows),
        "\n\n(*) = meerdere JSON-paren kwamen op hetzelfde pipeline-paar uit.\n",
    ]
    return "\n".join(md)


# ── Running the stack ────────────────────────────────────────────────────────

def _dotenv_settings() -> dict[str, str]:
    values = dotenv_values(BACKEND / ".env")
    return {key: str(values[key]) for key in ENV_FROM_DOTENV if values.get(key)}


async def _prepare_database() -> None:
    import asyncpg

    conn = await asyncpg.connect(PG_ADMIN)
    try:
        await conn.execute(f'DROP DATABASE IF EXISTS "{DB_NAME}" WITH (FORCE)')
        await conn.execute(f'CREATE DATABASE "{DB_NAME}"')
    finally:
        await conn.close()


async def _drive_session(client, pairs: list[Pair], audio: Path, worker_log: Path, log) -> dict:
    with open(audio, "rb") as f:
        r = await client.post("/sessions", data={"language": "tr"},
                              files={"audio": (audio.name, f, "audio/wav")})
    r.raise_for_status()
    sid = r.json()["session_id"]
    raw: dict = {"api_session_id": sid, "audio": audio.name, "started": time.time()}
    (await client.post(f"/sessions/{sid}/start")).raise_for_status()

    async def finish(status: str) -> dict:
        raw["status"] = status
        session = (await client.get(f"/sessions/{sid}")).json()
        raw["error"] = session.get("error_code") or session.get("error_message")
        response = await client.get(f"/evaluations/{sid}")
        raw["evaluation"] = response.json() if response.status_code == 200 else None
        raw["seconds"] = round(time.time() - raw["started"], 1)
        return raw

    status = await poll(client, sid, {"awaiting_role_confirmation", "failed"}, log)
    if status == "failed":
        return await finish(status)
    evaluation = (await client.get(f"/evaluations/{sid}")).json()
    raw["phase_a_transcript"] = evaluation.get("transcript") or []
    raw["roles"] = choose_roles(raw["phase_a_transcript"], pairs)
    log(f"rollen: ambtenaar={raw['roles']['officer']} cliënt={raw['roles']['client']} "
        f"tolk={raw['roles']['interpreter']}")
    if not raw["roles"]["interpreter"] or not raw["roles"]["client"]:
        raw["error"] = "rollen niet te bepalen uit de diarisatie"
        return await finish("failed")

    offset = worker_log.stat().st_size
    (await client.post(f"/sessions/{sid}/confirm-roles",
                       json={"interpreter_speaker": raw["roles"]["interpreter"],
                             "client_speaker": raw["roles"]["client"]})).raise_for_status()
    status = await poll(client, sid, {"completed", "failed"}, log)
    await asyncio.sleep(3)  # let the worker flush its last log lines
    with open(worker_log, "rb") as f:
        f.seek(offset)
        scores = score_lines(f.read().decode("utf-8", errors="replace"))
    raw["o2c_scores"] = scores["o2c"]
    raw["c2o_scores_in_log"] = scores["c2o"]
    return await finish(status)


async def _drive_all(todo: list[tuple[Session, Path]], email: str, password: str,
                     raw_dir: Path, worker_log: Path, log) -> None:
    import httpx

    async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{API_PORT}", timeout=300) as client:
        (await client.post("/auth/login", json={"email": email, "password": password})).raise_for_status()
        for session, audio in todo:
            log(f"=== {session.session_id}: {audio.name}")
            try:
                raw = await _drive_session(client, session.pairs, audio, worker_log, log)
            except Exception as exc:  # one broken session must not cost the others their run
                log(f"{session.session_id} afgebroken: {type(exc).__name__}: {exc}")
                raw = {"status": "harness_error", "error": f"{type(exc).__name__}: {exc}"}
            (raw_dir / f"{session.session_id}.json").write_text(
                json.dumps(raw, indent=1, ensure_ascii=False), encoding="utf-8")
            log(f"{session.session_id}: {raw.get('status')} in {raw.get('seconds')} s")


def run_stack(todo: list[tuple[Session, Path]], out_dir: Path, workdir: Path, log,
              llm_score_rules: str = "true") -> dict:
    """Start backend + worker on an isolated database, run every session, stop them."""
    secrets_from_env = _dotenv_settings()
    missing = [k for k in ("HF_TOKEN", "ANTHROPIC_API_KEY") if k not in secrets_from_env]
    if missing:
        raise SystemExit(f"ontbreekt in backend/.env: {', '.join(missing)}")
    for port in (API_PORT, REDIS_PORT):
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", port)) == 0:
                raise SystemExit(f"poort {port} is al in gebruik")

    work = workdir / dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    (work / "uploads").mkdir(parents=True)
    raw_dir = out_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith("ANTHROPIC")}
    env.update(secrets_from_env)
    env.update({
        "DATABASE_URL": DB_URL, "REDIS_URL": f"redis://127.0.0.1:{REDIS_PORT}",
        "SECRET_KEY": secrets.token_hex(32), "COOKIE_SECURE": "false", "LOG_LEVEL": "INFO",
        "LLM_SCORE_RULES": llm_score_rules, "LLM_TEMPERATURE": "0",
        "PYTHONPATH": str(BACKEND), "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1",
    })

    asyncio.run(_prepare_database())
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], env=env, cwd=BACKEND,
                   check=True, capture_output=True)
    log("database klaar; kennisbank inlezen")
    subprocess.run([sys.executable, "-c", INGEST_KNOWLEDGE], env=env, cwd=BACKEND,
                   check=True, capture_output=True)
    email, password = "pipeline-check@example.test", secrets.token_urlsafe(16)
    subprocess.run([sys.executable, "-c", CREATE_USER, email, password], env=env, cwd=BACKEND,
                   check=True, capture_output=True)

    start_fake_redis()
    wait_port(REDIS_PORT, 10)
    api_log, worker_log = out_dir / "api.log", out_dir / "worker.log"
    procs: list[subprocess.Popen] = []
    try:
        procs.append(subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1",
             "--port", str(API_PORT)], env=env, cwd=work,
            stdout=open(api_log, "w", encoding="utf-8"), stderr=subprocess.STDOUT))
        procs.append(subprocess.Popen(
            [sys.executable, "-c", WORKER_WITH_STUB], env=env, cwd=work,
            stdout=open(worker_log, "w", encoding="utf-8"), stderr=subprocess.STDOUT))
        wait_port(API_PORT, 120)
        log("api draait; wachten tot de worker LaBSE en Whisper heeft geladen")
        wait_for_line(worker_log, "Whisper ready.", procs[1], timeout=3600)
        log("worker klaar")
        asyncio.run(_drive_all(todo, email, password, raw_dir, worker_log, log))
    finally:
        for p in procs:
            p.terminate()
        for p in procs:
            try:
                p.wait(30)
            except subprocess.TimeoutExpired:
                p.kill()
    return {"llm_model": secrets_from_env.get("LLM_MODEL"),
            "whisper_model": secrets_from_env.get("WHISPER_MODEL"),
            "llm_score_rules": llm_score_rules}


def build_report(sessions: list[Session], raw_dir: Path, labels_dir: Path, meta: dict) -> tuple[str, dict]:
    result = asyncio.run(detection_check.run(
        threshold=LABSE_FLAG_BELOW, include_unreviewed=True, dry_run=True, sessions_dir=labels_dir))
    if result.status != RAN:
        raise SystemExit(f"laag 1 niet gedraaid: {result.reason}")
    layer1 = result.numbers["scores"]

    rows: list[dict] = []
    all_stats: list[dict] = []
    for session in sessions:
        path = raw_dir / f"{session.session_id}.json"
        raw = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"status": "niet gedraaid"}
        session_rows, stats = evaluate_session(session, raw, layer1)
        rows += session_rows
        all_stats.append(stats)
    summary = summarise(rows)
    numbers = {"valid": False, "demo": True, "meta": meta, "summary": summary,
               "sessions": all_stats, "pairs": rows,
               "constants": {"MIN_MATCH": MIN_MATCH, "HIGH_WER": HIGH_WER,
                             "LABSE_FLAG_BELOW": LABSE_FLAG_BELOW}}
    return render(rows, all_stats, summary, meta), numbers


def _git_commit() -> str:
    return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=REPO,
                          capture_output=True, text=True).stdout.strip()


def main() -> int:
    setup_logging()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--labels-dir", type=Path, default=LABELS_DIR)
    ap.add_argument("--audio-dir", type=Path, default=AUDIO_DIR)
    ap.add_argument("--sessions", nargs="*", default=None, help="session ids; default: all in --labels-dir")
    ap.add_argument("--workdir", type=Path, default=DEFAULT_WORKDIR)
    ap.add_argument("--from-raw", type=Path, default=None,
                    help="skip the stack and rebuild the report from an earlier run's raw/ folder")
    ap.add_argument("--label", default="", help="name of this run; goes into the report's file name")
    ap.add_argument("--llm-score-rules", choices=("true", "false"), default="false",
                    help="LLM_SCORE_RULES for the worker; true = LaBSE cut-offs in the prompt")
    args = ap.parse_args()

    sessions = load_sessions(args.labels_dir)
    if args.sessions:
        sessions = [s for s in sessions if s.session_id in set(args.sessions)]
    skipped = [s.session_id for s in sessions if s.split != "dev"]
    if skipped:
        print(f"overgeslagen, geen dev-sessie: {', '.join(skipped)}")
    sessions = [s for s in sessions if s.split == "dev"]
    if not sessions:
        print("geen dev-sessies gevonden", file=sys.stderr)
        return 2

    label = f"-{args.label}" if args.label else ""
    stem = f"{dt.date.today().isoformat()}-pipeline_check{label}-DEMO"
    out_dir = RESULTS_DIR / stem
    out_dir.mkdir(parents=True, exist_ok=True)
    progress = open(out_dir / "progress.log", "a", encoding="utf-8")

    def log(message: str) -> None:
        line = f"{dt.datetime.now():%H:%M:%S} {message}"
        print(line, flush=True)
        progress.write(line + "\n")
        progress.flush()

    meta_path = out_dir / "meta.json"
    if args.from_raw:
        raw_dir = args.from_raw
        earlier = raw_dir.parent / "meta.json"
        meta = json.loads(earlier.read_text(encoding="utf-8")) if earlier.exists() else {}
    else:
        todo = []
        for s in sessions:
            audio = args.audio_dir / f"{s.session_id.lower()}.wav"
            if not audio.exists():
                print(f"audio ontbreekt: {audio}", file=sys.stderr)
                return 2
            todo.append((s, audio.resolve()))
        meta = run_stack(todo, out_dir, args.workdir, log, args.llm_score_rules)
        meta["commit"] = _git_commit()
        meta["label"] = args.label
        diff = subprocess.run(["git", "diff", "HEAD", "--", "backend/app"], cwd=REPO,
                              capture_output=True, text=True, encoding="utf-8").stdout
        meta["app_diff"] = bool(diff)
        (out_dir / "app.diff").write_text(diff, encoding="utf-8")
        meta_path.write_text(json.dumps(meta, indent=1), encoding="utf-8")
        raw_dir = out_dir / "raw"

    markdown, numbers = build_report(sessions, raw_dir, args.labels_dir, meta)
    (RESULTS_DIR / f"{stem}.md").write_text(markdown, encoding="utf-8")
    (RESULTS_DIR / f"{stem}.json").write_text(
        json.dumps(numbers, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    print(markdown)
    log(f"rapport: {RESULTS_DIR / (stem + '.md')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
