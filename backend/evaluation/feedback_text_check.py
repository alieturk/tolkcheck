"""DV4 variants A and B on text: the real feedback step on labelled sessions, no audio.

Per session, every pair gets its LaBSE score as in detection_check.py
(cross_lingual), then the existing ``app.services.feedback.generate_feedback`` is
called once for the session — as the pipeline does — with the officer->client
pairs (nl->tr) and the client->officer pairs (tr->nl), their source text, the
interpreter's rendering and the score. No audio, no pipeline, no database.

    A: LLM_SCORE_RULES=true   (the current tool: Claude with the LaBSE cut-offs)
    B: LLM_SCORE_RULES=false  (Claude without the cut-offs)

Same model (settings.llm_model) and LLM_TEMPERATURE=0 as the tool. Both are set in
the environment before ``app`` is imported, because feedback.py builds its system
prompt once at import.

Differences from the tool, by construction: no knowledge-base retrieval (no
database, so no ACHTERGRONDINFORMATIE in the prompt), and no Dutch helper
translation for client->officer pairs (the prompt then shows only the original).

Which pairs count as flagged
----------------------------
From ``structured_issues`` — the field the UI reads (EvaluationView.tsx keys it by
direction and pair_index). An issue of type "false-negative" is the model saying a
fragment cannot be assessed; the UI excludes it everywhere, and so does this script.

* ``high_critical`` (primary): an issue of severity high or critical. These are the
  pairs the UI counts in its "Kritieke problemen" and "Hoge prioriteit" tabs, and
  the rule pipeline_check.py uses for the LLM.
* ``any_issue`` (reported next to it): any issue of any severity. The UI colours
  such a segment (yellow for medium/low) but does not count it in a tab.

A pair the model leaves out of its answer counts as not flagged and is listed.

    uv run python evaluation/feedback_text_check.py --variant A --sessions-dir <dev-only dir>
    uv run python evaluation/feedback_text_check.py --variant B --sessions-dir <dev-only dir> --add-to results/dev_voorlopig_<date>.json

Only sessions of ``--split`` (default dev) are run; others in the folder are skipped
without being scored. Raw answers, tokens and cost are saved next to the report.
"""
from __future__ import annotations

import argparse
import asyncio
import datetime as _dt
import json
import math
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

EVAL_DIR = Path(__file__).resolve().parent
if str(EVAL_DIR) not in sys.path:
    sys.path.insert(0, str(EVAL_DIR))

VARIANTS = {"A": "true", "B": "false"}
DIRECTION_OF = {"nl->tr": "officer_to_client", "tr->nl": "client_to_officer"}
NOT_A_FLAG_TYPE = "false-negative"
RULES = {
    "high_critical": {"high", "critical"},
    "any_issue": {"low", "medium", "high", "critical"},
}
PRIMARY_RULE = "high_critical"
FLAGGED_SCORE, NOT_FLAGGED_SCORE, THRESHOLD = 0.0, 1.0, 0.5   # flag as a score, for metrics.py


# --------------------------------------------------------------------------- #
# Parsing the feedback (pure functions, unit-tested)
# --------------------------------------------------------------------------- #

def issues_by_pair(structured: list | None) -> dict[tuple[str, int], list[dict]]:
    """``structured_issues`` → {(direction, pair_index): issues}, as the UI keys it.
    Entries without a usable pair_index are ignored; a missing direction is
    client_to_officer, the UI's default."""
    out: dict[tuple[str, int], list[dict]] = {}
    for entry in structured or []:
        if not isinstance(entry, dict):
            continue
        try:
            index = int(entry.get("pair_index"))
        except (TypeError, ValueError):
            continue
        direction = entry.get("direction") or "client_to_officer"
        issues = [i for i in (entry.get("issues") or []) if isinstance(i, dict)]
        out.setdefault((direction, index), []).extend(issues)
    return out


def is_flagged(issues: list[dict], rule: str = PRIMARY_RULE) -> bool:
    severities = RULES[rule]
    return any(str(i.get("severity", "")).lower() in severities and i.get("type") != NOT_A_FLAG_TYPE
               for i in issues)


@dataclass
class PairResult:
    pair_id: str
    session_id: str
    category: str | None
    label: str
    direction: str
    score: float | None
    issues: list[dict] | None          # None: the model's answer had no entry for this pair
    flags: dict[str, bool] = field(default_factory=dict)


def session_layout(pairs: list) -> tuple[list, list]:
    """Split a session's pairs into (officer_to_client, client_to_officer), in order;
    the position in each list is the pair_index the model answers with."""
    o2c = [p for p in pairs if p.direction == "nl->tr"]
    c2o = [p for p in pairs if p.direction == "tr->nl"]
    return o2c, c2o


def assign_flags(pairs: list, scores: dict[str, float | None], structured: list | None) -> list[PairResult]:
    """Tie the model's issues back to the labelled pairs and decide each flag."""
    by_key = issues_by_pair(structured)
    o2c, c2o = session_layout(pairs)
    out = []
    for direction, group in (("officer_to_client", o2c), ("client_to_officer", c2o)):
        for index, p in enumerate(group):
            issues = by_key.get((direction, index))
            out.append(PairResult(
                p.pair_id, p.session_id, p.category, p.label, p.direction, scores.get(p.pair_id), issues,
                {rule: is_flagged(issues or [], rule) for rule in RULES},
            ))
    order = {p.pair_id: i for i, p in enumerate(pairs)}
    return sorted(out, key=lambda r: order[r.pair_id])


def rows_for(results: list[PairResult], rule: str, skip: set[str] | frozenset = frozenset()) -> list:
    """metrics.Row per pair, with the flag encoded as a score below/above THRESHOLD.
    Pairs in ``skip`` (left out by the reviewer) are not counted."""
    from metrics import Row
    return [Row(r.session_id, r.category, FLAGGED_SCORE if r.flags[rule] else NOT_FLAGGED_SCORE)
            for r in results if r.pair_id not in skip]


# --------------------------------------------------------------------------- #
# Recording the API answers without changing feedback.py
# --------------------------------------------------------------------------- #

class _RecordingMessages:
    def __init__(self, inner, sink: list):
        self._inner, self._sink = inner, sink

    async def create(self, **kwargs):
        message = await self._inner.create(**kwargs)
        u = message.usage
        self._sink.append({
            "model": message.model,
            "stop_reason": message.stop_reason,
            "text": "".join(getattr(b, "text", "") for b in message.content),
            "usage": {
                "input_tokens": u.input_tokens or 0,
                "output_tokens": u.output_tokens or 0,
                "cache_creation_input_tokens": getattr(u, "cache_creation_input_tokens", 0) or 0,
                "cache_read_input_tokens": getattr(u, "cache_read_input_tokens", 0) or 0,
            },
            "temperature": kwargs.get("temperature"),
        })
        return message


class RecordingClient:
    """Wraps an AsyncAnthropic client; every messages.create answer lands in ``calls``."""

    def __init__(self, inner):
        self.calls: list[dict] = []
        self.messages = _RecordingMessages(inner.messages, self.calls)


# --------------------------------------------------------------------------- #
# Run
# --------------------------------------------------------------------------- #

def _clean(x):
    if isinstance(x, float) and math.isnan(x):
        return None
    if isinstance(x, dict):
        return {k: _clean(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_clean(v) for v in x]
    return x


async def run(variant: str, sessions_dir: Path, split: str, out_dir: Path, n_boot: int) -> dict:
    os.environ["LLM_SCORE_RULES"] = VARIANTS[variant]
    os.environ["LLM_TEMPERATURE"] = "0"

    from _common import neutralise_broken_torchcodec, setup_logging
    setup_logging()
    neutralise_broken_torchcodec()

    import anthropic
    import detection_check as dc
    import generate_sessions as gs
    from metrics import counts, precision_at_prevalence, session_bootstrap
    from sessions import CATEGORIES, load_sessions

    from app.config import settings
    from app.services import feedback

    assert settings.llm_score_rules is (variant == "A"), "LLM_SCORE_RULES not applied"
    assert settings.llm_temperature == 0
    assert ("Score ≥" in feedback._SYSTEM_PROMPT) is (variant == "A"), "system prompt does not match variant"

    sessions = [s for s in load_sessions(sessions_dir) if s.split == split]
    if not sessions:
        raise SystemExit(f"geen {split}-sessies in {sessions_dir}")
    pairs = [p for s in sessions for p in s.pairs]
    scores_list = await dc._score(pairs, "cross_lingual")
    scores = {p.pair_id: v for p, v in zip(pairs, scores_list)}

    client = RecordingClient(anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key))
    feedback._client = client
    raw_dir = out_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    results: list[PairResult] = []
    per_session = []
    for s in sessions:
        o2c, c2o = session_layout(s.pairs)
        block = lambda p: {"source_block": {"text": p.source_text}, "interp_block": {"text": p.rendering_text}}  # noqa: E731
        before = len(client.calls)
        started = time.monotonic()
        fb = await feedback.generate_feedback(
            [block(p) for p in c2o], [scores[p.pair_id] or 0.0 for p in c2o],
            [block(p) for p in o2c], [scores[p.pair_id] or 0.0 for p in o2c],
            db=None,
        )
        duration = time.monotonic() - started
        calls = client.calls[before:]
        usage: dict[str, int] = {}
        for c in calls:
            for k, v in c["usage"].items():
                usage[k] = usage.get(k, 0) + v
        model = calls[-1]["model"] if calls else settings.llm_model
        cost = gs.cost_usd(model, usage)
        session_results = assign_flags(s.pairs, scores, fb.get("structured_issues"))
        results += session_results
        missing = [r.pair_id for r in session_results if r.issues is None]
        (raw_dir / f"{s.session_id}.json").write_text(json.dumps({
            "session_id": s.session_id, "variant": variant, "calls": calls,
            "parsed": fb, "pair_order": {"officer_to_client": [p.pair_id for p in o2c],
                                         "client_to_officer": [p.pair_id for p in c2o]},
        }, indent=1, ensure_ascii=False), encoding="utf-8")
        per_session.append({"session_id": s.session_id, "model": model, **usage,
                            "cost_usd_estimate": cost, "duration_s": round(duration, 1),
                            "missing_pairs": missing,
                            "stop_reasons": [c["stop_reason"] for c in calls]})
        print(f"[{variant}] {s.session_id} · {gs.usage_summary(usage)} · kosten ≈ "
              f"{'?' if cost is None else f'${cost:.4f}'} · {duration:.0f} s"
              + (f" · ontbrekend: {', '.join(missing)}" if missing else ""), flush=True)

    # The whole session still goes to the model (as in the tool); pairs the reviewer
    # left out (excluded: true) are only left out of the counts.
    left_out = {p.pair_id: p.excluded_reason for p in pairs if p.excluded}
    reports = {}
    for rule in RULES:
        rows = rows_for(results, rule, set(left_out))
        boot = session_bootstrap(rows, THRESHOLD, CATEGORIES, n_boot=n_boot)
        table_md, numbers = dc._results_table(rows, THRESHOLD, boot)
        total = counts(rows, THRESHOLD)
        numbers["all"]["precision_at_prevalence"] = {
            str(p): precision_at_prevalence(total.recall, total.fpr, p) for p in dc.PREVALENCES}
        reports[rule] = {"markdown": table_md, "numbers": numbers}

    tokens: dict[str, int] = {}
    for row in per_session:
        for k in ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"):
            tokens[k] = tokens.get(k, 0) + row.get(k, 0)
    return {
        "variant": variant,
        "description": {"A": "Claude met drempelregels (LLM_SCORE_RULES=true)",
                        "B": "Claude zonder drempelregels (LLM_SCORE_RULES=false)"}[variant],
        "model": settings.llm_model, "llm_temperature": settings.llm_temperature,
        "llm_score_rules": settings.llm_score_rules,
        "labse_cutoffs": {"correct": settings.labse_correct_threshold,
                          "likely_issue": settings.labse_likely_issue_threshold,
                          "no_addition": settings.labse_no_addition_threshold},
        "split": split, "sessions": [s.session_id for s in sessions],
        "reviewed": sorted({s.reviewed for s in sessions}),
        "flag_rule_primary": PRIMARY_RULE, "flag_rules": {k: sorted(v) for k, v in RULES.items()},
        "differences_from_tool": ["geen kennisbank (geen database)",
                                  "geen Nederlandse hulpvertaling bij cliënt→ambtenaar"],
        "reports": reports,
        "excluded_by_reviewer": left_out,
        "per_session": per_session,
        "tokens_total": tokens,
        "cost_usd_estimate_total": sum(r["cost_usd_estimate"] or 0 for r in per_session),
        "pairs": [{"pair_id": r.pair_id, "label": r.label, "category": r.category, "score": r.score,
                   "flags": r.flags, "issues": r.issues} for r in results],
        "raw_dir": str(raw_dir),
    }


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="Variant A/B (feedbackmodel) op tekst.")
    ap.add_argument("--variant", choices=sorted(VARIANTS), required=True)
    ap.add_argument("--sessions-dir", type=Path, required=True)
    ap.add_argument("--split", default="dev", choices=("dev", "test"))
    ap.add_argument("--bootstrap", type=int, default=2000)
    ap.add_argument("--out-dir", type=Path, default=None,
                    help="standaard results/feedback_text_<variant>_<datum>/")
    ap.add_argument("--add-to", type=Path, default=None,
                    help="voeg het resultaat toe aan dit JSON-rapport (bijv. dev_voorlopig_<datum>.json)")
    args = ap.parse_args(argv)

    from _common import RESULTS_DIR
    today = _dt.date.today().isoformat()
    out_dir = args.out_dir or RESULTS_DIR / f"feedback_text_{args.variant}_{today}"
    result = asyncio.run(run(args.variant, args.sessions_dir, args.split, out_dir, args.bootstrap))
    result = _clean(result)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "result.json").write_text(json.dumps(result, indent=1, ensure_ascii=False), encoding="utf-8")
    md = [f"# Variant {args.variant} op tekst — {result['description']} ({today})\n",
          f"Model `{result['model']}`, temperature {result['llm_temperature']}, split {args.split}, "
          f"{len(result['sessions'])} sessies. Verschillen met de tool: "
          + "; ".join(result["differences_from_tool"]) + ".\n"]
    for rule, rep in result["reports"].items():
        md.append(f"\n## Gesignaleerd = {rule}" + (" (primair)" if rule == PRIMARY_RULE else "") + "\n")
        md.append(rep["markdown"])
    md.append(f"\nTokens: {result['tokens_total']} · kosten ≈ ${result['cost_usd_estimate_total']:.4f}\n")
    (out_dir / "result.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print(f"\nrapport: {out_dir / 'result.md'} · kosten ≈ ${result['cost_usd_estimate_total']:.4f}")

    if args.add_to:
        data = json.loads(args.add_to.read_text(encoding="utf-8"))
        data.setdefault("variants", {})[args.variant] = {
            k: v for k, v in result.items() if k not in ("pairs",)} | {"result_file": str(out_dir / "result.json")}
        args.add_to.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
        md_path = args.add_to.with_suffix(".md")
        if md_path.exists():
            md_path.write_text(md_path.read_text(encoding="utf-8") + "\n" + "\n".join(md) + "\n",
                               encoding="utf-8")
        print(f"toegevoegd aan {args.add_to}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
