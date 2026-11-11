"""DV4 layer 1 — detection measured on text: recall per category, false alarms, precision.

Scores every labelled pair in evaluation/data/sessions/*.json with the REAL
LaBSE scoring code (no audio, no ASR, no diarization), chooses the flag
threshold on the dev sessions, and reports on the test sessions:

  * recall per deviation category, with a Wilson interval and a session-level
    bootstrap interval
  * the false-alarm rate on the control pairs
  * precision in this set, and recomputed for a realistic share of deviating
    pairs (5, 10, 20%), because the share in a synthetic set is the author's choice

This is layer 1 of DV4: it measures the detector itself. Layer 2 (audio through
the whole pipeline) measures what transcription, diarization and pairing lose on
top; compare the two.

Session selection is strict by default: only `reviewed: true` sessions with
split `dev` or `test` count. `--include-unreviewed` and `--include-drafts` exist
for trying the format out; the report then says the numbers are not valid.

    uv run python evaluation/detection_check.py
    uv run python evaluation/detection_check.py --criterion youden
    (default criterion: recall_at_fpr, i.e. highest recall at FPR <= 0.10, as fixed in
    eval/data/tolkcheck_dv4/TESTOPZET.md)
    uv run python evaluation/detection_check.py --threshold 0.70      # current production cut-off, no calibration
    uv run python evaluation/detection_check.py --path pseudo_reference  # needs ANTHROPIC_API_KEY
    uv run python evaluation/detection_check.py --include-drafts --include-unreviewed --threshold 0.70  # format demo only
    uv run python evaluation/detection_check.py --dry-run --include-unreviewed --threshold 0.70  # dev sessions only, DEMO

`--dry-run` scores only the dev sessions with the given --threshold (required),
chooses no threshold, leaves test sessions out, and marks the report DEMO / "niet
geldig". `--sessions-dir` reads the sessions from another folder.
"""
from __future__ import annotations

import argparse
import asyncio
import datetime as _dt
import json
import math
from pathlib import Path

from _common import (
    DATA,
    RAN,
    RESULTS_DIR,
    CheckResult,
    env_missing,
    log,
    md_table,
    setup_logging,
)
from metrics import (
    Row,
    choose_threshold,
    counts,
    precision_at_prevalence,
    session_bootstrap,
    wilson,
)
from sessions import CATEGORIES, Pair, Session, SessionFormatError, load_sessions

NAME = "detection_check"
SESSIONS_DIR = DATA / "sessions"
PATHS = ("cross_lingual", "pseudo_reference")
PREVALENCES = (0.05, 0.10, 0.20)

CATEGORY_NL = {
    "omissie": "Omissie",
    "toevoeging": "Toevoeging",
    "betekenisverschuiving": "Betekenisverschuiving",
    "entiteitsfout": "Entiteitsfout",
    "register_en_nadruk": "Register en nadruk",
}


def _fmt(x: float) -> str:
    return "–" if x is None or (isinstance(x, float) and math.isnan(x)) else f"{x:.2f}"


def _ci(ci: tuple[float, float]) -> str:
    lo, hi = ci
    return "–" if math.isnan(lo) else f"{lo:.2f}–{hi:.2f}"


def _select(sessions: list[Session], include_drafts: bool, include_unreviewed: bool
            ) -> tuple[list[Session], list[str]]:
    keep, notes = [], []
    for s in sessions:
        if s.split == "draft" and not include_drafts:
            notes.append(f"{s.session_id}: split=draft, niet meegeteld")
            continue
        if not s.reviewed and not include_unreviewed:
            notes.append(f"{s.session_id}: reviewed=false, niet meegeteld")
            continue
        keep.append(s)
    return keep, notes


async def _score(pairs: list[Pair], path: str) -> list[float | None]:
    from app.services import scoring

    if path == "cross_lingual":
        vals = await scoring.score_segments([p.source_text for p in pairs],
                                            [p.rendering_text for p in pairs])
        return [float(v) for v in vals]

    # pseudo_reference: the same route as resume_scoring for c2o, mirrored for o2c
    # (see scoring_check.py, which this reuses so the two scripts cannot diverge).
    import scoring_check

    legacy = [{
        "pair_id": p.pair_id,
        "source_lang": p.source_lang,
        "target_lang": p.target_lang,
        "source_text": p.source_text,
        "interpreter_text": p.rendering_text,
    } for p in pairs]
    vals, _ = await scoring_check._path_pseudo_reference(legacy)
    return [None if v is None else float(v) for v in vals]


async def _reference_scores(pairs: list[Pair]) -> dict[str, float]:
    """LaBSE(source, reference rendering) for deviant pairs that carry one.
    Not used for detection — the tool is reference-free — only to show how far a
    deviation moves the score away from what a correct rendering gets."""
    from app.services import scoring

    with_ref = [p for p in pairs if p.reference_text]
    if not with_ref:
        return {}
    vals = await scoring.score_segments([p.source_text for p in with_ref],
                                        [p.reference_text for p in with_ref])
    return {p.pair_id: float(v) for p, v in zip(with_ref, vals)}


def _results_table(rows: list[Row], threshold: float, boot: dict) -> tuple[str, dict]:
    table, numbers = [], {}
    for c in CATEGORIES:
        k = counts(rows, threshold, c)
        n = k.tp + k.fn
        table.append([CATEGORY_NL[c], _fmt(k.recall), _ci(wilson(k.tp, n)),
                      _ci(boot.get(f"recall:{c}", (math.nan, math.nan))), n])
        numbers[c] = {"recall": k.recall, "tp": k.tp, "n": n,
                      "wilson": wilson(k.tp, n), "bootstrap": boot.get(f"recall:{c}")}
    total = counts(rows, threshold)
    n_dev = total.tp + total.fn
    n_ctrl = total.fp + total.tn
    table.append(["**Alle afwijkingen**", _fmt(total.recall), _ci(wilson(total.tp, n_dev)),
                  _ci(boot.get("recall:all", (math.nan, math.nan))), n_dev])
    md = md_table(["Foutcategorie", "Recall", "95% Wilson", "95% sessie-bootstrap", "n"], table)

    share = n_dev / (n_dev + n_ctrl) if n_dev + n_ctrl else math.nan
    flagged_n = total.tp + total.fp
    overall = [
        ["Valse alarmen (FPR) op controleparen", _fmt(total.fpr), _ci(wilson(total.fp, n_ctrl)),
         _ci(boot.get("fpr", (math.nan, math.nan))), n_ctrl],
        [f"Precision in deze set ({share:.0%} afwijkend)", _fmt(total.precision),
         _ci(wilson(total.tp, flagged_n)), _ci(boot.get("precision", (math.nan, math.nan))),
         flagged_n],
    ]
    for prev in PREVALENCES:
        overall.append([f"Precision bij {prev:.0%} afwijkende paren",
                        _fmt(precision_at_prevalence(total.recall, total.fpr, prev)),
                        "–", "–", "berekend"])
    md += "\n\n" + md_table(["Hele set", "Waarde", "95% Wilson", "95% sessie-bootstrap", "n"], overall)
    numbers["all"] = {"recall": total.recall, "fpr": total.fpr, "precision": total.precision,
                      "tp": total.tp, "fn": total.fn, "fp": total.fp, "tn": total.tn,
                      "share_deviant": share,
                      "precision_at_prevalence": {
                          str(p): precision_at_prevalence(total.recall, total.fpr, p)
                          for p in PREVALENCES}}
    return md, numbers


async def run(
    path: str = "cross_lingual",
    criterion: str = "recall_at_fpr",
    threshold: float | None = None,
    include_drafts: bool = False,
    include_unreviewed: bool = False,
    n_boot: int = 2000,
    dry_run: bool = False,
    sessions_dir: Path = SESSIONS_DIR,
) -> CheckResult:
    if path not in PATHS:
        return CheckResult.failed(NAME, f"unknown path {path!r}")
    if dry_run and threshold is None:
        return CheckResult.failed(NAME, "--dry-run needs --threshold; it never chooses one")
    if not sessions_dir.exists():
        return CheckResult.skipped(NAME, f"{sessions_dir} not found")
    try:
        all_sessions = load_sessions(sessions_dir)
    except SessionFormatError as exc:
        return CheckResult.failed(NAME, f"session format: {exc}")
    sessions, excluded = _select(all_sessions, include_drafts, include_unreviewed)
    if dry_run:
        # Test and draft sessions stay out of the run entirely: not scored, not reported.
        excluded += [f"{s.session_id}: split={s.split}, niet meegeteld (--dry-run rekent alleen dev door)"
                     for s in sessions if s.split != "dev"]
        sessions = [s for s in sessions if s.split == "dev"]
    if not sessions:
        return CheckResult.skipped(
            NAME, f"no usable sessions in {sessions_dir.name}/ ({'; '.join(excluded) or 'empty'})")
    if path == "pseudo_reference" and env_missing("anthropic_api_key"):
        return CheckResult.skipped(NAME, "pseudo_reference needs ANTHROPIC_API_KEY")

    demo = include_drafts or include_unreviewed or dry_run
    dev = [p for s in sessions if s.split == "dev" for p in s.pairs]
    test = [p for s in sessions if s.split in ("test", "draft") for p in s.pairs]
    if not test and not dry_run:
        return CheckResult.skipped(NAME, "no test (or, with --include-drafts, draft) sessions")
    if threshold is None and not dev:
        return CheckResult.skipped(
            NAME, "no dev sessions to choose a threshold on; add dev sessions or pass --threshold")

    reported = dev if dry_run else test
    set_name = "ontwikkelset" if dry_run else "testset"
    all_pairs = dev + test
    log.info("[%s] path=%s sessions=%d dev_pairs=%d test_pairs=%d",
             NAME, path, len(sessions), len(dev), len(test))
    try:
        scores = await _score(all_pairs, path)
        ref = await _reference_scores(all_pairs)
    except Exception as exc:
        return CheckResult.failed(NAME, f"scoring raised {type(exc).__name__}: {exc}")
    by_id = {p.pair_id: s for p, s in zip(all_pairs, scores)}
    unscored = [p.pair_id for p in all_pairs if by_id[p.pair_id] is None]

    def rows_of(pairs: list[Pair]) -> list[Row]:
        return [Row(p.session_id, p.category, by_id[p.pair_id])
                for p in pairs if by_id[p.pair_id] is not None]

    dev_rows, reported_rows = rows_of(dev), rows_of(reported)
    if threshold is None:
        try:
            threshold = choose_threshold(dev_rows, criterion)
        except ValueError as exc:
            return CheckResult.skipped(NAME, f"cannot choose threshold on dev: {exc}")
        how = f"gekozen op de ontwikkelset ({len(dev_rows)} paren, criterium `{criterion}`)"
    else:
        how = "vooraf opgegeven, niet afgesteld"
    boot = session_bootstrap(reported_rows, threshold, CATEGORIES, n_boot=n_boot)
    table_md, numbers = _results_table(reported_rows, threshold, boot)

    md: list[str] = []
    if dry_run:
        md.append("> **DEMO — niet geldig als resultaat.** Gedraaid met --dry-run: alleen "
                  "ontwikkelsessies zijn doorgerekend, met een vooraf opgegeven drempel. Er is geen "
                  "drempel gekozen en er zijn geen testsessies bekeken."
                  + (" Niet-gecontroleerde sessies tellen mee." if include_unreviewed else "") + "\n")
    elif demo:
        md.append("> **Niet geldig als resultaat.** Gedraaid met "
                  + ", ".join(f for f, on in (("--include-drafts", include_drafts),
                                              ("--include-unreviewed", include_unreviewed)) if on)
                  + ": niet-gecontroleerde of conceptsessies tellen mee. Alleen om het formaat te testen.\n")
    md.append(f"**Scoringsroute:** `{path}`. **Drempel:** {threshold:.3f}, {how}. "
              f"Een paar wordt gesignaleerd als de score onder de drempel ligt. "
              f"**{set_name.capitalize()}:** {len(reported_rows)} paren uit "
              f"{len({r.session_id for r in reported_rows})} sessie(s).\n")
    md.append(table_md)
    md.append("\nRecall per categorie; valse alarmen en precision alleen voor de hele set, "
              "omdat de detector geen categorie geeft. De bootstrap trekt hele sessies "
              f"({n_boot}×); bij weinig sessies is dat interval breed of ontbreekt het.\n")

    if ref:
        shift_rows = []
        for c in CATEGORIES:
            deltas = [ref[p.pair_id] - by_id[p.pair_id] for p in reported
                      if p.category == c and p.pair_id in ref and by_id[p.pair_id] is not None]
            if deltas:
                shift_rows.append([CATEGORY_NL[c], len(deltas), sum(deltas) / len(deltas),
                                   min(deltas), max(deltas)])
        if shift_rows:
            md.append("\n**Hoeveel beweegt de score?** Score van de referentievertaling min de score "
                      "van de vertolking, per categorie (alleen analyse; de tool gebruikt geen referentie). "
                      "Rond 0 betekent dat de afwijking de score niet verandert.\n")
            md.append(md_table(["Categorie", "n", "gem. verschil", "min", "max"], shift_rows))

    detail = [[p.pair_id, CATEGORY_NL.get(p.category, "controle"), p.subtype or "",
               _fmt(by_id[p.pair_id]), "ja" if (by_id[p.pair_id] is not None
                                                 and by_id[p.pair_id] < threshold) else "nee",
               p.source_words] for p in reported]
    md.append(f"\n**Per paar ({set_name})**\n")
    md.append(md_table(["paar", "categorie", "subtype", "score", "gesignaleerd", "woorden bron"], detail))

    notes = excluded + [w for s in sessions for w in s.warnings]
    if unscored:
        notes.append(f"niet gescoord (vertaling mislukt): {', '.join(unscored)}")
    if notes:
        md.append("\n**Opmerkingen**\n\n" + "\n".join(f"- {n}" for n in notes))

    numbers.update({"path": path, "threshold": threshold, "criterion": criterion if how.startswith("gekozen") else None,
                    "valid": not demo, "n_dev": len(dev_rows),
                    "n_test": 0 if dry_run else len(reported_rows),
                    "scores": {k: v for k, v in by_id.items()}, "reference_scores": ref,
                    "notes": notes})
    if dry_run:
        numbers["dry_run"] = True
    return CheckResult(name=NAME, status=RAN, markdown="\n".join(md), numbers=numbers)


def _main() -> int:
    setup_logging()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--path", default="cross_lingual", choices=PATHS)
    ap.add_argument("--criterion", default="recall_at_fpr",
                    help="recall_at_fpr (TESTOPZET: max FPR 0.10) | recall_at_fpr:0.05 | f1 | youden | recall:0.8")
    ap.add_argument("--threshold", type=float, default=None, help="fixed threshold; skips calibration")
    ap.add_argument("--include-drafts", action="store_true")
    ap.add_argument("--include-unreviewed", action="store_true")
    ap.add_argument("--bootstrap", type=int, default=2000)
    ap.add_argument("--dry-run", action="store_true",
                    help="score only dev sessions with --threshold (required); report is DEMO / niet geldig")
    ap.add_argument("--sessions-dir", type=Path, default=SESSIONS_DIR,
                    help="folder with session files (default: evaluation/data/sessions)")
    args = ap.parse_args()
    if args.dry_run and args.threshold is None:
        ap.error("--dry-run requires --threshold")

    res = asyncio.run(run(args.path, args.criterion, args.threshold,
                          args.include_drafts, args.include_unreviewed, args.bootstrap,
                          dry_run=args.dry_run, sessions_dir=args.sessions_dir))
    print("\n" + "=" * 70)
    print(f"{res.name}: {res.status}" + (f" — {res.reason}" if res.reason else ""))
    print("=" * 70)
    print(res.markdown or "(no output)")
    if res.status == RAN:
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        stem = f"{_dt.date.today().isoformat()}-detection-{args.path}"
        if not res.numbers.get("valid"):
            stem += "-DEMO"
        (RESULTS_DIR / f"{stem}.md").write_text(
            f"# {'DEMO — ' if args.dry_run else ''}DV4 laag 1 — detectie op tekst "
            f"({_dt.date.today().isoformat()})\n\n" + res.markdown + "\n",
            encoding="utf-8")
        (RESULTS_DIR / f"{stem}.json").write_text(
            json.dumps(res.numbers, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
        print(f"\nreport: {RESULTS_DIR / (stem + '.md')}")
    return 0 if res.status == RAN else 1


if __name__ == "__main__":
    raise SystemExit(_main())
