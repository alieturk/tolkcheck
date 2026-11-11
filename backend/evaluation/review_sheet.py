"""Review sheet for the native speaker: one Excel file per batch of sessions, and back.

    # make the sheet (all deviations + a fixed 30% sample of the controls)
    uv run python evaluation/review_sheet.py make --from 25 --to 26
    # read the filled-in sheet back; fully approved sessions get reviewed = true
    uv run python evaluation/review_sheet.py apply review_S25-S26.xlsx --reviewer "Naam"

``make`` writes one row per pair to review: every deviation, and per session a
sample of the controls — round(30%) of them, at least one. The sample is drawn
with ``random.Random(f"{seed}:{session_id}")``, so it depends only on the seed and
the session, not on which other sessions are in the batch. The seed, the fraction,
the sampled pair_ids and a SHA-256 of every session file are written to the sheet
"steekproef".

``apply`` reads the "akkoord (ja/nee)" column back. A session whose rows are all
"ja" gets ``reviewed: true`` and ``reviewed_by: <name>``. A session with any "nee"
is not changed and its rejected pairs are listed; neither is a session with empty
answers, missing rows, or a file that changed since the sheet was made. Nothing
else in the session files is edited.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import random
import sys
from dataclasses import dataclass, field
from pathlib import Path

EVAL_DIR = Path(__file__).resolve().parent
if str(EVAL_DIR) not in sys.path:
    sys.path.insert(0, str(EVAL_DIR))

from session_lint import describe_diff  # noqa: E402
from sessions import Pair, Session, load_session  # noqa: E402

DEFAULT_SESSIONS_DIR = EVAL_DIR.parent.parent / "eval" / "data" / "tolkcheck_dv4" / "sessions_v2"
DEFAULT_SEED = 20261111
DEFAULT_FRACTION = 0.30

REVIEW_SHEET = "review"
META_SHEET = "steekproef"
AGREE, REMARK = "akkoord (ja/nee)", "opmerking reviewer"
OLD_REMARK = "opmerking"   # header in sheets made before the rename; still read back
DIFFS = "woordverschillen"
COLUMNS = ("sessie", "pair_id", "richting", "bron", "vertolking", "reference_rendering",
           DIFFS, "label", "subtype", "severity", AGREE, REMARK)
WIDTHS = (8, 10, 8, 60, 60, 50, 16, 28, 24, 10, 16, 40)


def diffs_cell(p: Pair) -> str:
    """Contiguous word differences between rendering and reference (deviations only),
    as session_lint counts them: "1", or "2 (3 ertussen)" for two runs 3 words apart."""
    if p.is_control or not p.reference_text:
        return ""
    return describe_diff(p.rendering_text, p.reference_text)


# --------------------------------------------------------------------------- #
# Selection
# --------------------------------------------------------------------------- #

def sample_controls(session: Session, seed: int, fraction: float = DEFAULT_FRACTION) -> list[str]:
    """pair_ids of the sampled controls of one session, in session order."""
    controls = [p.pair_id for p in session.pairs if p.is_control]
    if not controls:
        return []
    k = min(len(controls), max(1, round(fraction * len(controls))))
    chosen = set(random.Random(f"{seed}:{session.session_id}").sample(controls, k))
    return [pid for pid in controls if pid in chosen]


def rows_for(session: Session, seed: int, fraction: float = DEFAULT_FRACTION) -> list[Pair]:
    """Every deviation plus the sampled controls, in session order."""
    sampled = set(sample_controls(session, seed, fraction))
    return [p for p in session.pairs if not p.is_control or p.pair_id in sampled]


def sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


# --------------------------------------------------------------------------- #
# make
# --------------------------------------------------------------------------- #

def make_sheet(paths: list[Path], out: Path, seed: int = DEFAULT_SEED,
               fraction: float = DEFAULT_FRACTION) -> dict:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font
    from openpyxl.worksheet.datavalidation import DataValidation

    sessions = [load_session(p) for p in paths]
    wb = Workbook()
    ws = wb.active
    ws.title = REVIEW_SHEET
    ws.append(list(COLUMNS))
    for cell in ws[1]:
        cell.font = Font(bold=True)
    summary: dict[str, dict] = {}
    for s, path in zip(sessions, paths):
        sampled = sample_controls(s, seed, fraction)
        rows = rows_for(s, seed, fraction)
        for p in rows:
            ws.append([s.session_id, p.pair_id, p.direction, p.source_text, p.rendering_text,
                       p.reference_text or "", diffs_cell(p), p.label, p.subtype or "",
                       p.severity, "", ""])
        summary[s.session_id] = {
            "file": Path(path).name,
            "sha256": sha256(path),
            "deviations": [p.pair_id for p in s.pairs if not p.is_control],
            "controls_total": sum(p.is_control for p in s.pairs),
            "controls_sampled": sampled,
        }

    wrap = Alignment(wrap_text=True, vertical="top")
    for row in ws.iter_rows(min_row=2):
        for cell in row:
            cell.alignment = wrap
    for i, width in enumerate(WIDTHS):
        ws.column_dimensions[chr(ord("A") + i)].width = width
    ws.freeze_panes = "A2"
    if ws.max_row > 1:
        agree_col = chr(ord("A") + COLUMNS.index(AGREE))
        dv = DataValidation(type="list", formula1='"ja,nee"', allow_blank=True)
        dv.add(f"{agree_col}2:{agree_col}{ws.max_row}")
        ws.add_data_validation(dv)

    meta = wb.create_sheet(META_SHEET)
    meta.append(["seed", seed])
    meta.append(["fractie controles", fraction])
    meta.append(["regel", "alle afwijkingen; per sessie round(fractie × controles) controles, "
                          "minstens één; random.Random(f'{seed}:{session_id}')"])
    meta.append(["gemaakt", _dt.datetime.now().isoformat(timespec="seconds")])
    meta.append([])
    meta.append(["sessie", "bestand", "sha256", "afwijkingen", "controles totaal",
                 "controles in steekproef", "pair_ids steekproef"])
    for cell in meta[6]:
        cell.font = Font(bold=True)
    for sid, info in summary.items():
        meta.append([sid, info["file"], info["sha256"], len(info["deviations"]),
                     info["controls_total"], len(info["controls_sampled"]),
                     ",".join(info["controls_sampled"])])
    meta.column_dimensions["C"].width = 66
    meta.column_dimensions["G"].width = 40

    out.parent.mkdir(parents=True, exist_ok=True)
    wb.save(out)
    return summary


# --------------------------------------------------------------------------- #
# apply
# --------------------------------------------------------------------------- #

@dataclass
class ApplyReport:
    approved: list[str] = field(default_factory=list)
    rejected_pairs: list[tuple[str, str, str]] = field(default_factory=list)  # sid, pid, remark
    not_updated: dict[str, str] = field(default_factory=dict)                 # sid → reason


def _read_meta(wb) -> dict[str, dict]:
    ws = wb[META_SHEET]
    out: dict[str, dict] = {}
    header_seen = False
    for row in ws.iter_rows(values_only=True):
        if row and row[0] == "sessie":
            header_seen = True
            continue
        if header_seen and row and row[0]:
            sid, file, digest, _, _, _, sampled = row[:7]
            out[str(sid)] = {"file": str(file), "sha256": str(digest),
                             "sampled": [x for x in str(sampled or "").split(",") if x]}
    return out


def _answer(value) -> str:
    return str(value or "").strip().lower()


def apply_sheet(sheet: Path, sessions_dir: Path, reviewer: str, write: bool = True) -> ApplyReport:
    from openpyxl import load_workbook

    if not reviewer.strip():
        raise ValueError("reviewer mag niet leeg zijn")
    wb = load_workbook(sheet, read_only=True)
    try:
        meta = _read_meta(wb)
        rows = list(wb[REVIEW_SHEET].iter_rows(values_only=True))
    finally:
        wb.close()   # read-only mode keeps the file open (and locked on Windows) until closed
    header = [str(h) for h in rows[0]]
    if REMARK not in header and OLD_REMARK in header:
        header[header.index(OLD_REMARK)] = REMARK
    idx = {name: header.index(name) for name in ("sessie", "pair_id", AGREE, REMARK)}

    by_session: dict[str, list[tuple[str, str, str]]] = {sid: [] for sid in meta}
    for row in rows[1:]:
        if not row or row[idx["sessie"]] is None:
            continue
        sid = str(row[idx["sessie"]])
        by_session.setdefault(sid, []).append(
            (str(row[idx["pair_id"]]), _answer(row[idx[AGREE]]), str(row[idx[REMARK]] or "").strip()))

    report = ApplyReport()
    for sid, answers in by_session.items():
        info = meta.get(sid)
        if info is None:
            report.not_updated[sid] = "staat niet in het blad 'steekproef'"
            continue
        path = Path(sessions_dir) / info["file"]
        if not path.exists():
            report.not_updated[sid] = f"bestand {info['file']} niet gevonden"
            continue
        if sha256(path) != info["sha256"]:
            report.not_updated[sid] = "sessiebestand is gewijzigd sinds het blad is gemaakt"
            continue
        session = load_session(path)
        expected = {p.pair_id for p in session.pairs if not p.is_control} | set(info["sampled"])
        present = {pid for pid, _, _ in answers}
        rejected = [(sid, pid, remark) for pid, ans, remark in answers if ans == "nee"]
        report.rejected_pairs += rejected
        unknown = sorted(a for pid, a, _ in answers if a not in ("ja", "nee"))
        if rejected:
            report.not_updated[sid] = f"{len(rejected)} paar/paren afgekeurd"
        elif expected - present:
            report.not_updated[sid] = f"rijen ontbreken: {', '.join(sorted(expected - present))}"
        elif unknown:
            report.not_updated[sid] = f"{len(unknown)} rij(en) zonder 'ja' of 'nee'"
        else:
            if write:
                data = json.loads(path.read_text(encoding="utf-8"))
                data["reviewed"] = True
                data["reviewed_by"] = reviewer
                path.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
            report.approved.append(sid)
    return report


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def _session_paths(sessions_dir: Path, first: int, last: int) -> list[Path]:
    paths, missing = [], []
    for n in range(first, last + 1):
        p = sessions_dir / f"S{n}.json"
        (paths if p.exists() else missing).append(p)
    if missing:
        print(f"niet gevonden, overgeslagen: {', '.join(p.stem for p in missing)}", file=sys.stderr)
    return paths


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):   # Windows consoles default to cp1252
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="Review-sheet voor de moedertaalspreker.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    mk = sub.add_parser("make", help="maak het Excel-bestand")
    mk.add_argument("--from", dest="first", type=int, required=True)
    mk.add_argument("--to", dest="last", type=int, required=True)
    mk.add_argument("--sessions-dir", type=Path, default=DEFAULT_SESSIONS_DIR)
    mk.add_argument("--out", type=Path, default=None,
                    help="standaard <sessions-dir>/review/review_S<from>-S<to>.xlsx")
    mk.add_argument("--seed", type=int, default=DEFAULT_SEED)
    mk.add_argument("--fraction", type=float, default=DEFAULT_FRACTION)

    apl = sub.add_parser("apply", help="lees het ingevulde bestand terug")
    apl.add_argument("sheet", type=Path)
    apl.add_argument("--reviewer", required=True, help="naam voor reviewed_by")
    apl.add_argument("--sessions-dir", type=Path, default=DEFAULT_SESSIONS_DIR)
    apl.add_argument("--dry-run", action="store_true", help="niets wegschrijven")
    args = ap.parse_args(argv)

    if args.cmd == "make":
        paths = _session_paths(args.sessions_dir, args.first, args.last)
        if not paths:
            print("geen sessies gevonden", file=sys.stderr)
            return 2
        out = args.out or args.sessions_dir / "review" / f"review_S{args.first}-S{args.last}.xlsx"
        summary = make_sheet(paths, out, args.seed, args.fraction)
        for sid, info in summary.items():
            print(f"{sid}: {len(info['deviations'])} afwijking(en), "
                  f"{len(info['controls_sampled'])}/{info['controls_total']} controles "
                  f"({', '.join(info['controls_sampled'])})")
        n_rows = sum(len(i["deviations"]) + len(i["controls_sampled"]) for i in summary.values())
        print(f"\n{n_rows} rijen, seed {args.seed} → {out}")
        return 0

    report = apply_sheet(args.sheet, args.sessions_dir, args.reviewer, write=not args.dry_run)
    for sid in report.approved:
        print(f"{sid}: akkoord → reviewed = true, reviewed_by = {args.reviewer}"
              + (" (dry-run, niet geschreven)" if args.dry_run else ""))
    for sid, reason in report.not_updated.items():
        print(f"{sid}: niet aangepast — {reason}")
    if report.rejected_pairs:
        print("\nAfgekeurde paren:")
        for sid, pid, remark in report.rejected_pairs:
            print(f"  {pid}: {remark or '(geen opmerking)'}")
    return 0 if not report.not_updated else 1


if __name__ == "__main__":
    raise SystemExit(main())
