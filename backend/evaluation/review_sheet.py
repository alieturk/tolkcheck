"""Review sheet for the native speaker: one Excel file per batch of sessions, and back.

    # make the sheet (all deviations + a fixed 30% sample of the controls)
    uv run python evaluation/review_sheet.py make --from 20 --to 29 --sessions-dir <dir>
    # read the filled-in sheet back into the session files
    uv run python evaluation/review_sheet.py apply review_dev_S20-S29.xlsx --reviewer "Naam" --sessions-dir <dir>

``make`` writes one row per pair to review: every deviation, and per session a
sample of the controls — round(30%) of them, at least one. The sample is drawn
with ``random.Random(f"{seed}:{session_id}")``, so it depends only on the seed and
the session, not on which other sessions are in the batch. The seed, the fraction,
the sampled pair_ids and a SHA-256 of every session file are written to the sheet
"steekproef".

Filling in a row — every row needs one judgement:

* "akkoord (ja/nee)" = ja: the label, subtype and severity are right. The
  correction columns stay empty.
* "akkoord" = nee, plus at least one of "gecorrigeerd label", "gecorrigeerd
  subtype", "gecorrigeerde severity": the pair gets the corrected values.
* "weglaten (ja/leeg)" = ja, with the reason in "opmerking reviewer": the pair is
  left out of every measurement (for instance: the rendering is wrong in a way the
  labels cannot express). Its text is not touched.

``apply`` works per session and all-or-nothing: only when every row of the session
has a judgement (and every deviation and sampled control has a row, and the file is
unchanged since the sheet was made) does it write the session, with

* corrected values in ``label``/``subtype``/``severity``; ``expected_flag`` follows
  the label (``controle_*`` = false); the old values are kept in ``label_origineel``,
  ``subtype_origineel`` and ``severity_origineel``. A deviation that becomes a
  control keeps its reference rendering as ``reference_rendering_origineel``.
* ``excluded: true`` and ``excluded_reason`` for left-out pairs;
* the reviewer's remark as ``opmerking_reviewer`` on any pair that has one;
* ``reviewed: true`` and ``reviewed_by``.

Source and rendering text are never changed, so sealed predictions stay valid.
Controls outside the sample are left as they are.
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

from session_lint import (  # noqa: E402
    CONTROLS,
    DEVIATIONS,
    EXCEPTIONS,
    SUBTYPES,
    describe_diff,
)
from sessions import CONTROL_PREFIX, Pair, Session, load_session  # noqa: E402

DEFAULT_SESSIONS_DIR = EVAL_DIR.parent.parent / "eval" / "data" / "tolkcheck_dv4" / "sessions_v4"
DEFAULT_SEED = 20261111
DEFAULT_FRACTION = 0.30

REVIEW_SHEET = "review"
META_SHEET = "steekproef"
AGREE, REMARK = "akkoord (ja/nee)", "opmerking reviewer"
OLD_REMARK = "opmerking"   # header in sheets made before the rename; still read back
DIFFS = "woordverschillen"
FIX_LABEL, FIX_SUBTYPE, FIX_SEVERITY = "gecorrigeerd label", "gecorrigeerd subtype", "gecorrigeerde severity"
OMIT = "weglaten (ja/leeg)"
COLUMNS = ("sessie", "pair_id", "richting", "bron", "vertolking", "reference_rendering",
           DIFFS, "label", "subtype", "severity", AGREE,
           FIX_LABEL, FIX_SUBTYPE, FIX_SEVERITY, OMIT, REMARK)
WIDTHS = (8, 10, 8, 60, 60, 50, 16, 28, 24, 10, 16, 28, 24, 14, 12, 40)

LABELS = sorted(DEVIATIONS) + sorted(CONTROLS | EXCEPTIONS)
SEVERITIES = ("none", "minor", "major", "critical")
NO_SUBTYPE = {"", "-", "–", "none", "null", "geen"}


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

def _col(name: str) -> str:
    return chr(ord("A") + COLUMNS.index(name))


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
        for p in rows_for(s, seed, fraction):
            ws.append([s.session_id, p.pair_id, p.direction, p.source_text, p.rendering_text,
                       p.reference_text or "", diffs_cell(p), p.label, p.subtype or "",
                       p.severity, "", "", "", "", "", ""])
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
        last = ws.max_row
        for column, options in ((AGREE, ("ja", "nee")), (FIX_LABEL, LABELS),
                                (FIX_SEVERITY, SEVERITIES), (OMIT, ("ja",))):
            dv = DataValidation(type="list", formula1='"' + ",".join(options) + '"', allow_blank=True)
            dv.add(f"{_col(column)}2:{_col(column)}{last}")
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

    help_ws = wb.create_sheet("uitleg")
    for line in (
        "Elke rij in 'review' heeft één oordeel nodig:",
        "1. akkoord = ja: label, subtype en severity kloppen. Laat de correctiekolommen leeg.",
        "2. akkoord = nee: vul minstens één van 'gecorrigeerd label', 'gecorrigeerd subtype', "
        "'gecorrigeerde severity' in.",
        "3. weglaten = ja: het paar telt nergens mee. Zet de reden in 'opmerking reviewer'.",
        "Een controle (label controle_*) heeft geen subtype en severity 'none'.",
        "Subtypes per categorie: " + "; ".join(f"{c}: {', '.join(s)}" for c, s in SUBTYPES.items()),
        "Bron- en vertolkingstekst worden nooit aangepast.",
    ):
        help_ws.append([line])
    help_ws.column_dimensions["A"].width = 140

    out.parent.mkdir(parents=True, exist_ok=True)
    wb.save(out)
    return summary


# --------------------------------------------------------------------------- #
# apply
# --------------------------------------------------------------------------- #

@dataclass
class RowAnswer:
    pair_id: str
    agree: str
    remark: str
    label: str
    subtype: str
    severity: str
    omit: str

    @property
    def has_correction(self) -> bool:
        return bool(self.label or self.subtype or self.severity)


@dataclass
class Change:
    session_id: str
    pair_id: str
    before: dict
    after: dict
    remark: str


@dataclass
class ApplyReport:
    approved: list[str] = field(default_factory=list)                         # sessions written
    corrected: list[Change] = field(default_factory=list)
    excluded: list[tuple[str, str, str]] = field(default_factory=list)        # sid, pid, reason
    rejected_pairs: list[tuple[str, str, str]] = field(default_factory=list)  # nee without correction
    problems: dict[str, list[str]] = field(default_factory=dict)              # sid → rows without a valid judgement
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


def _text(value) -> str:
    return "" if value is None else str(value).strip()


def _answer(value) -> str:
    return _text(value).lower()


def judge(row: RowAnswer, pair: Pair) -> tuple[dict | None, str | None]:
    """(new values for the pair, or None to leave it; problem text, or None).

    New values hold label/subtype/severity/expected_flag for a correction, or
    {"excluded": True, "excluded_reason": ...} for a left-out pair."""
    if row.omit:
        if row.omit != "ja":
            return None, f"{row.pair_id}: 'weglaten' is {row.omit!r}, verwacht 'ja' of leeg"
        if not row.remark:
            return None, f"{row.pair_id}: weglaten zonder reden in '{REMARK}'"
        return {"excluded": True, "excluded_reason": row.remark}, None
    if row.agree == "ja":
        if row.has_correction:
            return None, f"{row.pair_id}: akkoord = ja, maar er staat ook een correctie"
        return {}, None
    if row.agree == "nee":
        if not row.has_correction:
            return None, f"{row.pair_id}: akkoord = nee zonder correctie of weglaten"
    elif row.has_correction:
        return None, f"{row.pair_id}: correctie zonder akkoord = nee"
    else:
        return None, f"{row.pair_id}: geen oordeel ({AGREE!r} is {row.agree or 'leeg'!r})"

    label = row.label or pair.label
    if label not in LABELS:
        return None, f"{row.pair_id}: onbekend label {label!r}"
    is_control = label.startswith(CONTROL_PREFIX)
    severity = (row.severity or ("none" if is_control and not pair.is_control else pair.severity)).lower()
    if severity not in SEVERITIES:
        return None, f"{row.pair_id}: onbekende severity {severity!r}"
    if is_control:
        if row.subtype and row.subtype.lower() not in NO_SUBTYPE:
            return None, f"{row.pair_id}: controle met subtype {row.subtype!r}"
        if severity != "none":
            return None, f"{row.pair_id}: controle met severity {severity!r}, verwacht 'none'"
        subtype = None
    else:
        subtype = row.subtype or pair.subtype
        if subtype not in SUBTYPES[label]:
            return None, (f"{row.pair_id}: subtype {subtype!r} hoort niet bij {label}; kies uit "
                          f"{', '.join(SUBTYPES[label])}")
        if severity == "none":
            return None, f"{row.pair_id}: afwijking met severity 'none'"
    new = {"label": label, "subtype": subtype, "severity": severity, "expected_flag": not is_control}
    old = {"label": pair.label, "subtype": pair.subtype, "severity": pair.severity,
           "expected_flag": pair.expected_flag}
    if new == old:
        return None, f"{row.pair_id}: akkoord = nee, maar de correctie is gelijk aan het huidige label"
    return new, None


def _apply_to_pair(raw: dict, new: dict, remark: str) -> None:
    if remark:
        raw["opmerking_reviewer"] = remark
    if not new:
        return
    if new.get("excluded"):
        raw["excluded"] = True
        raw["excluded_reason"] = new["excluded_reason"]
        return
    for key in ("label", "subtype", "severity"):
        raw.setdefault(f"{key}_origineel", raw.get(key))
    was_deviation = not str(raw.get("label", "")).startswith(CONTROL_PREFIX)
    raw.update(new)
    if was_deviation and not new["expected_flag"] and raw.get("reference_rendering") is not None:
        raw["reference_rendering_origineel"] = raw.pop("reference_rendering")


def read_sheet(sheet: Path) -> tuple[dict[str, dict], dict[str, list[RowAnswer]]]:
    from openpyxl import load_workbook

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
    opt = {name: header.index(name) if name in header else None
           for name in (FIX_LABEL, FIX_SUBTYPE, FIX_SEVERITY, OMIT)}

    def cell(row, name):
        i = opt[name]
        return _text(row[i]) if i is not None and i < len(row) else ""

    by_session: dict[str, list[RowAnswer]] = {sid: [] for sid in meta}
    for row in rows[1:]:
        if not row or row[idx["sessie"]] is None:
            continue
        by_session.setdefault(str(row[idx["sessie"]]), []).append(RowAnswer(
            pair_id=_text(row[idx["pair_id"]]), agree=_answer(row[idx[AGREE]]),
            remark=_text(row[idx[REMARK]]), label=cell(row, FIX_LABEL), subtype=cell(row, FIX_SUBTYPE),
            severity=cell(row, FIX_SEVERITY).lower(), omit=cell(row, OMIT).lower()))
    return meta, by_session


def apply_sheet(sheet: Path, sessions_dir: Path, reviewer: str, write: bool = True) -> ApplyReport:
    if not reviewer.strip():
        raise ValueError("reviewer mag niet leeg zijn")
    meta, by_session = read_sheet(sheet)

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
        pairs = {p.pair_id: p for p in session.pairs}
        expected = {p.pair_id for p in session.pairs if not p.is_control} | set(info["sampled"])
        present = {a.pair_id for a in answers}

        problems, decided = [], []
        for a in answers:
            if a.pair_id not in pairs:
                problems.append(f"{a.pair_id}: paar bestaat niet in {info['file']}")
                continue
            if a.agree == "nee" and not a.has_correction and not a.omit:
                report.rejected_pairs.append((sid, a.pair_id, a.remark))
            new, problem = judge(a, pairs[a.pair_id])
            if problem:
                problems.append(problem)
            else:
                decided.append((a, new))
        if expected - present:
            problems.append(f"rijen ontbreken: {', '.join(sorted(expected - present))}")
        if problems:
            report.problems[sid] = problems
            report.not_updated[sid] = f"{len(problems)} rij(en) zonder geldig oordeel"
            continue

        data = json.loads(path.read_text(encoding="utf-8"))
        raw_by_id = {p["pair_id"]: p for p in data["pairs"]}
        for a, new in decided:
            pair = pairs[a.pair_id]
            if new.get("excluded"):
                report.excluded.append((sid, a.pair_id, new["excluded_reason"]))
            elif new:
                report.corrected.append(Change(
                    sid, a.pair_id, {"label": pair.label, "subtype": pair.subtype, "severity": pair.severity},
                    {k: new[k] for k in ("label", "subtype", "severity")}, a.remark))
            _apply_to_pair(raw_by_id[a.pair_id], new, a.remark)
        data["reviewed"] = True
        data["reviewed_by"] = reviewer
        if write:
            path.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
            load_session(path)   # the result must still load
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
    note = " (dry-run, niet geschreven)" if args.dry_run else ""
    for sid in report.approved:
        print(f"{sid}: reviewed = true, reviewed_by = {args.reviewer}{note}")
    for sid, reason in report.not_updated.items():
        print(f"{sid}: niet aangepast — {reason}")
        for problem in report.problems.get(sid, []):
            print(f"    - {problem}")
    print(f"\nGecorrigeerd: {len(report.corrected)}")
    for c in report.corrected:
        print(f"  {c.pair_id}: {c.before['label']}/{c.before['subtype']}/{c.before['severity']} → "
              f"{c.after['label']}/{c.after['subtype']}/{c.after['severity']}"
              + (f" — {c.remark}" if c.remark else ""))
    print(f"Weggelaten: {len(report.excluded)}")
    for sid, pid, reason in report.excluded:
        print(f"  {pid}: {reason}")
    return 0 if not report.not_updated else 1


if __name__ == "__main__":
    raise SystemExit(main())
