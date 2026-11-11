"""DV4 test set, sealed: predictions now, metrics only after the labels are reviewed.

    # 1. predictions on the test sessions, twice — no labels used, no metrics, nothing shown
    uv run python evaluation/test_sealed.py predict --run run1 --sessions-dir ../eval/data/tolkcheck_dv4/sessions_v4
    uv run python evaluation/test_sealed.py predict --run run2 --sessions-dir ../eval/data/tolkcheck_dv4/sessions_v4

    # 2. later, after review: metrics from the sealed predictions and the reviewed labels
    uv run python evaluation/test_sealed.py score --sealed evaluation/results/test_sealed_<date> \\
        --sessions-dir ../eval/data/tolkcheck_dv4/sessions_v4

Two runs, fixed before either was made
--------------------------------------
``predict`` is run twice on the same commit, into ``<sealed>/run1`` and
``<sealed>/run2``. **run1 is primary: every reported metric comes from run1.** run2
is used for one thing only, stability: per variant, the share of test pairs whose
decision (flagged or not) is the same in run1 and run2. It never replaces, averages
or selects run1 results. A run2 on another commit than run1 is reported as such and
makes the stability figures invalid.

predict
-------
Refuses to run with uncommitted changes to tracked files, and records the commit.
Only sessions with split ``test`` are read. Per pair it stores the LaBSE score
(cross_lingual, as detection_check.py) and the issues of variant A
(LLM_SCORE_RULES=true) and variant B (false) from the existing generate_feedback,
called once per session as in feedback_text_check.py. A and B each run in a child
process (feedback.py fixes its system prompt at import); their console output goes
to logs/ in the sealed folder and is not shown. Also stored: the raw API answers,
tokens, cost, the SHA-256 of every session file and a hash of every pair's text.
No label is written and no metric is computed. The folder must not exist yet.

score
-----
Reads the sealed predictions and the REVIEWED session files (dev and test; every
session must have reviewed = true, unless --allow-unreviewed, which marks the report
invalid). Pairs whose source or rendering text changed since sealing are left out
and listed: their predictions belong to other text. Then:

* C: the threshold is chosen again on the reviewed dev sessions with
  metrics.choose_threshold (recall_at_fpr, max FPR 0.10, as TESTOPZET.md), and
  applied to the sealed LaBSE scores of the test pairs.
* A and B: a pair is flagged when it has an issue of severity high or critical that
  is not of type false-negative (feedback_text_check.PRIMARY_RULE); "any issue" is
  reported next to it.

Metrics are those of detection_check.py: recall per category with Wilson and
session-bootstrap intervals, FPR, precision in the set and at 5/10/20% prevalence.
"""
from __future__ import annotations

import argparse
import asyncio
import datetime as _dt
import hashlib
import json
import math
import os
import subprocess
import sys
from pathlib import Path

EVAL_DIR = Path(__file__).resolve().parent
BACKEND_ROOT = EVAL_DIR.parent
REPO_ROOT = BACKEND_ROOT.parent
for _p in (EVAL_DIR, BACKEND_ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import feedback_text_check as ftc  # noqa: E402
from sessions import Session, load_sessions  # noqa: E402

VARIANTS = ("A", "B")
PRIMARY_RUN, STABILITY_RUN = "run1", "run2"
RUNS = (PRIMARY_RUN, STABILITY_RUN)
DEFAULT_CRITERION, DEFAULT_MAX_FPR = "recall_at_fpr", 0.10


# --------------------------------------------------------------------------- #
# Helpers (unit-tested)
# --------------------------------------------------------------------------- #

def text_hash(pair) -> str:
    """What a prediction depends on: direction, source and rendering text."""
    blob = "\x00".join((pair.direction, pair.source_text, pair.rendering_text))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def file_hash(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def tracked_changes(repo: Path = REPO_ROOT) -> list[str]:
    out = subprocess.run(["git", "status", "--porcelain", "--untracked-files=no"], cwd=repo,
                         capture_output=True, text=True, check=True).stdout
    return [line for line in out.splitlines() if line.strip()]


def head_commit(repo: Path = REPO_ROOT) -> str:
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True,
                          text=True, check=True).stdout.strip()


def run_dirs(sealed: Path) -> tuple[Path, Path | None]:
    """(primary run, stability run or None). A folder with its own manifest.json is
    a single run and is used as the primary one."""
    if (sealed / "manifest.json").exists():
        return sealed, None
    primary = sealed / PRIMARY_RUN
    if not (primary / "manifest.json").exists():
        raise SystemExit(f"geen {PRIMARY_RUN}/manifest.json in {sealed}")
    second = sealed / STABILITY_RUN
    return primary, second if (second / "manifest.json").exists() else None


def decisions(predictions: list[dict], threshold: float) -> dict[str, dict[str, bool]]:
    """Per variant and rule: pair_id → flagged, from sealed predictions alone."""
    out: dict[str, dict[str, bool]] = {"C": {p["pair_id"]: p["labse"] < threshold
                                             for p in predictions if p["labse"] is not None}}
    for v in VARIANTS:
        for rule in ftc.RULES:
            out[f"{v}:{rule}"] = {p["pair_id"]: ftc.is_flagged(p[f"issues_{v}"] or [], rule) for p in predictions}
    return out


def stability(run1: list[dict], run2: list[dict], threshold: float, pair_ids: set[str] | None = None) -> dict:
    """Share of pairs with the same decision in both runs, per variant (and rule).
    Only pairs present in both runs with the same text count; ``pair_ids`` narrows
    it further (e.g. to the pairs kept for the metrics)."""
    second = {p["pair_id"]: p for p in run2}
    common = [p for p in run1 if p["pair_id"] in second and second[p["pair_id"]]["text_hash"] == p["text_hash"]
              and (pair_ids is None or p["pair_id"] in pair_ids)]
    ids = [p["pair_id"] for p in common]
    d1 = decisions(common, threshold)
    d2 = decisions([second[i] for i in ids], threshold)
    out = {}
    for key in d1:
        both = [i for i in ids if i in d1[key] and i in d2[key]]
        same = sum(d1[key][i] == d2[key][i] for i in both)
        out[key] = {"n": len(both), "same": same, "share": same / len(both) if both else None,
                    "differ": [i for i in both if d1[key][i] != d2[key][i]]}
    return out


def issues_per_pair_id(session: Session, structured) -> dict[str, list[dict] | None]:
    """The model's issues by pair_id (None when the answer has no entry for the pair)."""
    by_key = ftc.issues_by_pair(structured)
    o2c, c2o = ftc.session_layout(session.pairs)
    out = {}
    for direction, group in (("officer_to_client", o2c), ("client_to_officer", c2o)):
        for index, p in enumerate(group):
            out[p.pair_id] = by_key.get((direction, index))
    return out


# --------------------------------------------------------------------------- #
# predict
# --------------------------------------------------------------------------- #

def _test_sessions(sessions_dir: Path) -> list[Session]:
    sessions = [s for s in load_sessions(sessions_dir) if s.split == "test"]
    if not sessions:
        raise SystemExit(f"geen test-sessies in {sessions_dir}")
    return sessions


async def _variant_child(variant: str, sessions_dir: Path, out: Path) -> None:
    """Runs in its own process: environment first, then app."""
    os.environ["LLM_SCORE_RULES"] = ftc.VARIANTS[variant]
    os.environ["LLM_TEMPERATURE"] = "0"
    import anthropic
    import generate_sessions as gs

    from app.config import settings
    from app.services import feedback

    assert settings.llm_score_rules is (variant == "A") and settings.llm_temperature == 0
    assert ("Score ≥" in feedback._SYSTEM_PROMPT) is (variant == "A")

    labse = json.loads((out / "labse.json").read_text(encoding="utf-8"))
    client = ftc.RecordingClient(anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key))
    feedback._client = client
    raw_dir = out / f"raw_{variant}"
    raw_dir.mkdir(parents=True, exist_ok=True)
    pairs_out, per_session = {}, []
    for s in _test_sessions(sessions_dir):
        o2c, c2o = ftc.session_layout(s.pairs)
        block = lambda p: {"source_block": {"text": p.source_text}, "interp_block": {"text": p.rendering_text}}  # noqa: E731
        before = len(client.calls)
        fb = await feedback.generate_feedback(
            [block(p) for p in c2o], [labse[p.pair_id] or 0.0 for p in c2o],
            [block(p) for p in o2c], [labse[p.pair_id] or 0.0 for p in o2c], db=None)
        calls = client.calls[before:]
        usage: dict[str, int] = {}
        for c in calls:
            for k, v in c["usage"].items():
                usage[k] = usage.get(k, 0) + v
        model = calls[-1]["model"] if calls else settings.llm_model
        issues = issues_per_pair_id(s, fb.get("structured_issues"))
        pairs_out.update(issues)
        (raw_dir / f"{s.session_id}.json").write_text(json.dumps(
            {"session_id": s.session_id, "variant": variant, "calls": calls, "parsed": fb},
            indent=1, ensure_ascii=False), encoding="utf-8")
        per_session.append({"session_id": s.session_id, "model": model, **usage,
                            "cost_usd_estimate": gs.cost_usd(model, usage),
                            "pairs_without_answer": sum(v is None for v in issues.values()),
                            "stop_reasons": [c["stop_reason"] for c in calls]})
    (out / f"variant_{variant}.json").write_text(json.dumps({
        "variant": variant, "model": settings.llm_model, "llm_temperature": settings.llm_temperature,
        "llm_score_rules": settings.llm_score_rules, "issues": pairs_out, "per_session": per_session,
    }, indent=1, ensure_ascii=False), encoding="utf-8")


async def predict(sessions_dir: Path, out: Path, force_dirty: bool = False, run: str = "run1") -> dict:
    dirty = tracked_changes()
    if dirty and not force_dirty:
        raise SystemExit("niet-gecommitte wijzigingen in gevolgde bestanden; commit eerst:\n" + "\n".join(dirty))
    if out.exists():
        raise SystemExit(f"{out} bestaat al; een verzegelde run wordt niet overschreven")
    commit = head_commit()
    sessions = _test_sessions(sessions_dir)
    out.mkdir(parents=True)
    (out / "logs").mkdir()

    from _common import neutralise_broken_torchcodec
    neutralise_broken_torchcodec()
    import detection_check as dc

    pairs = [p for s in sessions for p in s.pairs]
    scores = await dc._score(pairs, "cross_lingual")
    (out / "labse.json").write_text(json.dumps({p.pair_id: v for p, v in zip(pairs, scores)}, indent=1),
                                    encoding="utf-8")

    for variant in VARIANTS:
        with open(out / "logs" / f"variant_{variant}.log", "w", encoding="utf-8") as log:
            code = subprocess.run([sys.executable, "-W", "ignore", str(Path(__file__).resolve()), "_variant",
                                   "--variant", variant, "--sessions-dir", str(sessions_dir), "--out", str(out)],
                                  cwd=BACKEND_ROOT, stdout=log, stderr=subprocess.STDOUT).returncode
        if code != 0:
            raise SystemExit(f"variant {variant} faalde (exitcode {code}); zie {out / 'logs'}")

    labse = json.loads((out / "labse.json").read_text(encoding="utf-8"))
    variants = {v: json.loads((out / f"variant_{v}.json").read_text(encoding="utf-8")) for v in VARIANTS}
    predictions = [{
        "pair_id": p.pair_id, "session_id": p.session_id, "direction": p.direction,
        "text_hash": text_hash(p), "labse": labse[p.pair_id],
        **{f"issues_{v}": variants[v]["issues"].get(p.pair_id) for v in VARIANTS},
    } for p in pairs]
    (out / "predictions.json").write_text(json.dumps(predictions, indent=1, ensure_ascii=False), encoding="utf-8")

    run_info = {v: {"model": variants[v]["model"], "llm_temperature": variants[v]["llm_temperature"],
                    "llm_score_rules": variants[v]["llm_score_rules"],
                    "tokens": {k: sum(s.get(k, 0) for s in variants[v]["per_session"])
                               for k in ("input_tokens", "output_tokens", "cache_creation_input_tokens",
                                         "cache_read_input_tokens")},
                    "cost_usd_estimate": sum(s["cost_usd_estimate"] or 0 for s in variants[v]["per_session"]),
                    "pairs_without_answer": sum(s["pairs_without_answer"] for s in variants[v]["per_session"]),
                    "stop_reasons": sorted({r for s in variants[v]["per_session"] for r in s["stop_reasons"]})}
                for v in VARIANTS}
    manifest = {
        "status": "verzegeld: alleen voorspellingen, geen metrics; labels niet gebruikt",
        "run": run,
        "role": "primair" if run == PRIMARY_RUN else "alleen stabiliteit",
        "date": _dt.date.today().isoformat(),
        "commit": commit,
        "uncommitted_tracked_changes": dirty,
        "scoring_path": "cross_lingual (LaBSE)",
        "flag_rule_for_scoring": ftc.PRIMARY_RULE,
        "sessions": {s.session_id: {"file": s.path.name, "sha256": file_hash(s.path),
                                    "pairs": [p.pair_id for p in s.pairs]} for s in sessions},
        "variants": run_info,
        "differences_from_tool": ["geen kennisbank (geen database)",
                                  "geen Nederlandse hulpvertaling bij cliënt→ambtenaar"],
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1, ensure_ascii=False), encoding="utf-8")
    return manifest


# --------------------------------------------------------------------------- #
# score
# --------------------------------------------------------------------------- #

def _clean(x):
    if isinstance(x, float) and math.isnan(x):
        return None
    if isinstance(x, dict):
        return {k: _clean(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_clean(v) for v in x]
    return x


def compute_metrics(test_sessions: list[Session], dev_sessions: list[Session], predictions: list[dict],
                    dev_scores: dict[str, float | None], criterion: str = DEFAULT_CRITERION,
                    max_fpr: float = DEFAULT_MAX_FPR, n_boot: int = 2000) -> dict:
    """Metrics for A, B and C on the test pairs, with the labels of ``test_sessions``
    and the C threshold chosen on ``dev_sessions``. Pure: no API, no LaBSE."""
    import detection_check as dc
    from metrics import Row, choose_threshold, session_bootstrap
    from sessions import CATEGORIES

    pred = {p["pair_id"]: p for p in predictions}
    test_pairs = [p for s in test_sessions for p in s.pairs]
    excluded = {}
    for p in test_pairs:
        if p.pair_id not in pred:
            excluded[p.pair_id] = "geen verzegelde voorspelling"
        elif pred[p.pair_id]["text_hash"] != text_hash(p):
            excluded[p.pair_id] = "tekst gewijzigd sinds verzegeling"
        elif pred[p.pair_id]["labse"] is None:
            excluded[p.pair_id] = "geen LaBSE-score"
    for pid in pred:
        if pid not in {p.pair_id for p in test_pairs}:
            excluded[pid] = "paar bestaat niet meer in de sessies"
    kept = [p for p in test_pairs if p.pair_id not in excluded]

    dev_rows = [Row(p.session_id, p.category, dev_scores[p.pair_id])
                for s in dev_sessions for p in s.pairs if dev_scores.get(p.pair_id) is not None]
    threshold = choose_threshold(dev_rows, criterion, max_fpr=max_fpr)

    def report(rows, thr):
        boot = session_bootstrap(rows, thr, CATEGORIES, n_boot=n_boot)
        md, numbers = dc._results_table(rows, thr, boot)
        return {"markdown": md, "numbers": numbers}

    out = {"C": {"threshold": threshold, "criterion": criterion, "max_fpr": max_fpr,
                 "n_dev_pairs": len(dev_rows),
                 **report([Row(p.session_id, p.category, pred[p.pair_id]["labse"]) for p in kept], threshold)}}
    for v in VARIANTS:
        out[v] = {}
        for rule in ftc.RULES:
            rows = [Row(p.session_id, p.category,
                        ftc.FLAGGED_SCORE if ftc.is_flagged(pred[p.pair_id][f"issues_{v}"] or [], rule)
                        else ftc.NOT_FLAGGED_SCORE) for p in kept]
            out[v][rule] = report(rows, ftc.THRESHOLD)
        out[v]["pairs_without_answer"] = sum(pred[p.pair_id][f"issues_{v}"] is None for p in kept)
    return {"variants": out, "excluded_pairs": excluded, "n_test_pairs": len(kept)}


async def score(sealed: Path, sessions_dir: Path, out: Path | None, criterion: str, max_fpr: float,
                allow_unreviewed: bool, n_boot: int) -> Path:
    primary, second = run_dirs(sealed)
    manifest = json.loads((primary / "manifest.json").read_text(encoding="utf-8"))
    predictions = json.loads((primary / "predictions.json").read_text(encoding="utf-8"))
    sessions = load_sessions(sessions_dir)
    test = [s for s in sessions if s.split == "test" and s.session_id in manifest["sessions"]]
    dev = [s for s in sessions if s.split == "dev"]
    missing = sorted(set(manifest["sessions"]) - {s.session_id for s in test})
    unreviewed = sorted(s.session_id for s in test + dev if not s.reviewed)
    if unreviewed and not allow_unreviewed:
        raise SystemExit(f"niet gereviewd: {', '.join(unreviewed)} (gebruik --allow-unreviewed alleen om te testen)")

    from _common import RESULTS_DIR, neutralise_broken_torchcodec
    neutralise_broken_torchcodec()
    import detection_check as dc
    dev_pairs = [p for s in dev for p in s.pairs]
    dev_scores = dict(zip([p.pair_id for p in dev_pairs], await dc._score(dev_pairs, "cross_lingual")))

    result = compute_metrics(test, dev, predictions, dev_scores, criterion, max_fpr, n_boot)
    valid = not unreviewed and not missing and not result["excluded_pairs"]

    kept = {p.pair_id for s in test for p in s.pairs} - set(result["excluded_pairs"])
    if second is not None:
        manifest2 = json.loads((second / "manifest.json").read_text(encoding="utf-8"))
        run2 = json.loads((second / "predictions.json").read_text(encoding="utf-8"))
        result["stability"] = {
            "role": f"{STABILITY_RUN} alleen voor stabiliteit; alle metrics komen uit {PRIMARY_RUN}",
            "same_commit": manifest2["commit"] == manifest["commit"],
            "commit_run2": manifest2["commit"],
            "per_variant": stability(predictions, run2, result["variants"]["C"]["threshold"], kept),
        }
    else:
        result["stability"] = None
    today = _dt.date.today().isoformat()
    result.update({
        "status": "definitief" if valid else "NIET GELDIG",
        "valid": valid, "date": today, "sealed": str(sealed), "primary_run": str(primary),
        "sealed_commit": manifest["commit"],
        "sealed_date": manifest["date"], "scored_with_commit": head_commit(),
        "unreviewed_sessions": unreviewed, "sealed_sessions_missing": missing,
        "dev_sessions": [s.session_id for s in dev],
    })
    out = out or RESULTS_DIR / f"test_final_{today}"
    out.mkdir(parents=True, exist_ok=True)
    (out / "result.json").write_text(json.dumps(_clean(result), indent=1, ensure_ascii=False, default=str),
                                     encoding="utf-8")
    md = [f"# DV4 testset — {result['status']} ({today})\n",
          f"Verzegeld op {manifest['date']} met commit `{manifest['commit']}`; gescoord met commit "
          f"`{result['scored_with_commit']}`. {result['n_test_pairs']} testparen.\n"]
    if not valid:
        md.append("> **Niet geldig:** " + "; ".join(x for x in (
            f"niet gereviewd: {', '.join(unreviewed)}" if unreviewed else "",
            f"ontbrekende sessies: {', '.join(missing)}" if missing else "",
            f"{len(result['excluded_pairs'])} paren uitgesloten" if result["excluded_pairs"] else "") if x) + "\n")
    c = result["variants"]["C"]
    md += [f"\n## C — LaBSE, drempel {c['threshold']:.3f} ({c['criterion']}, max FPR {c['max_fpr']}, "
           f"gekozen op {c['n_dev_pairs']} gereviewde dev-paren)\n", c["markdown"]]
    for v in VARIANTS:
        for rule in ftc.RULES:
            md += [f"\n## {v} — gesignaleerd = {rule}" + (" (primair)" if rule == ftc.PRIMARY_RULE else "") + "\n",
                   result["variants"][v][rule]["markdown"]]
    st = result["stability"]
    if st:
        md.append(f"\n## Stabiliteit ({STABILITY_RUN} tegen {PRIMARY_RUN})\n\n{st['role']}."
                  + ("" if st["same_commit"] else f" **Let op: {STABILITY_RUN} draaide op een andere commit "
                     f"({st['commit_run2']}); deze cijfers zijn niet geldig.**") + "\n")
        md.append("| variant | paren | zelfde beslissing | aandeel |\n|---|---|---|---|")
        for key, v in st["per_variant"].items():
            share = "–" if v["share"] is None else f"{v['share']:.3f}"
            md.append(f"| {key} | {v['n']} | {v['same']} | {share} |")
    else:
        md.append(f"\n_Geen {STABILITY_RUN} gevonden; stabiliteit niet berekend._\n")
    if result["excluded_pairs"]:
        md.append("\n**Uitgesloten paren**\n\n" + "\n".join(f"- {k}: {v}" for k, v in result["excluded_pairs"].items()))
    (out / "result.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    return out


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="DV4 testset: verzegelde voorspellingen en latere metrics.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    pr = sub.add_parser("predict")
    pr.add_argument("--sessions-dir", type=Path, required=True)
    pr.add_argument("--run", choices=RUNS, default=PRIMARY_RUN,
                    help=f"{PRIMARY_RUN} is primair, {STABILITY_RUN} alleen voor stabiliteit")
    pr.add_argument("--out", type=Path, default=None, help="standaard results/test_sealed_<datum>/<run>/")
    ch = sub.add_parser("_variant")   # internal: one variant in its own process
    ch.add_argument("--variant", choices=VARIANTS, required=True)
    ch.add_argument("--sessions-dir", type=Path, required=True)
    ch.add_argument("--out", type=Path, required=True)
    sc = sub.add_parser("score")
    sc.add_argument("--sealed", type=Path, required=True)
    sc.add_argument("--sessions-dir", type=Path, required=True)
    sc.add_argument("--out", type=Path, default=None)
    sc.add_argument("--criterion", default=DEFAULT_CRITERION)
    sc.add_argument("--max-fpr", type=float, default=DEFAULT_MAX_FPR)
    sc.add_argument("--allow-unreviewed", action="store_true")
    sc.add_argument("--bootstrap", type=int, default=2000)
    args = ap.parse_args(argv)

    if args.cmd == "_variant":
        asyncio.run(_variant_child(args.variant, args.sessions_dir, args.out))
        return 0
    if args.cmd == "predict":
        from _common import RESULTS_DIR
        out = args.out or RESULTS_DIR / f"test_sealed_{_dt.date.today().isoformat()}" / args.run
        m = asyncio.run(predict(args.sessions_dir, out, run=args.run))
        print(f"verzegeld: {out} ({m['run']}, {m['role']})\ncommit {m['commit']} · {len(m['sessions'])} sessies")
        for v, info in m["variants"].items():
            print(f"{v}: tokens {info['tokens']} · kosten ≈ ${info['cost_usd_estimate']:.4f} · "
                  f"stop {info['stop_reasons']} · paren zonder antwoord {info['pairs_without_answer']}")
        return 0
    out = asyncio.run(score(args.sealed, args.sessions_dir, args.out, args.criterion, args.max_fpr,
                            args.allow_unreviewed, args.bootstrap))
    print(f"rapport: {out / 'result.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
