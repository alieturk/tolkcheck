"""Check labelled sessions against the rules of prompt ``tolkcheck-sessies-v2``.

Reports, per session, every way it departs from the generation prompt. It reads
the raw JSON rather than going through sessions.py, so a session the loader would
refuse still gets a full list of findings instead of one exception. Standard
library only; no scores are computed here.

Only sessions written with prompt v2 are checked, because the rules describe that
prompt. Older sessions (S12) are listed as skipped, and so are ``test`` sessions:
nothing derived from them should reach the person writing or tuning the set.

    uv run python evaluation/session_lint.py
    uv run python evaluation/session_lint.py --sessions-dir path/to/sessions

Exit code 0 when every checked session is clean, 1 when there are findings.

Readings of the prompt that the rules leave open
------------------------------------------------
* The first pair is a question (``nl->tr``), then directions alternate.
* Rounds never decrease, and each of 1, 2, 3 and 4 occurs.
* Length bands are inclusive as the prompt words them, so an answer of exactly 15
  or 35 words counts for both bands it touches.
* Words are whitespace-separated tokens, the same count as ``Pair.source_words``.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

PROMPT_VERSION = "tolkcheck-sessies-v2"
DEFAULT_DIR = Path(__file__).resolve().parent / "data" / "sessions"

N_PAIRS = 8
ROUNDS = {1, 2, 3, 4}
QUESTION, ANSWER = "nl->tr", "tr->nl"

OM, TOE, BET, ENT, REG = (
    "omissie",
    "toevoeging",
    "betekenisverschuiving",
    "entiteitsfout",
    "register_en_nadruk",
)
DEVIATIONS = {OM, TOE, BET, ENT, REG}
# Deviation categories a session must contain, by the last digit of its number.
BY_LAST_DIGIT: dict[int, tuple[str, ...]] = {
    0: (OM, TOE, BET, ENT),
    1: (REG, OM, TOE),
    2: (BET, ENT, REG, OM),
    3: (TOE, BET, ENT),
    4: (REG, OM, TOE, BET),
    5: (ENT, REG, OM),
    6: (TOE, BET, ENT, REG),
    7: (OM, TOE, BET),
    8: (ENT, REG, OM, TOE),
    9: (BET, ENT, REG),
}

LITERAL, PARAPHRASE = "controle_letterlijk", "controle_parafrase"
# The one permitted-exception control a session must contain, by number modulo 3.
EXCEPTION_BY_MOD3 = {
    0: "controle_gemelde_omschrijving",
    1: "controle_verzoek_herhaling",
    2: "controle_taalvariant",
}
EXCEPTIONS = set(EXCEPTION_BY_MOD3.values())
CONTROLS = {LITERAL, PARAPHRASE} | EXCEPTIONS

MAX_SOURCE_WORDS = 60
LENGTH_BANDS = (("kort (≤15)", 0, 15), ("middellang (15–35)", 15, 35), ("lang (35–60)", 35, 60))
OWN_QUESTION = "eigen_vraag_tolk"
OWN_QUESTION_SEVERITIES = {"major", "critical"}


def _session_number(data: dict) -> int | None:
    match = re.fullmatch(r"S(\d+)", str(data.get("session_id", "")))
    return int(match.group(1)) if match else None


def _text(pair: dict, side: str) -> str:
    part = pair.get(side)
    return str(part.get("text", "")) if isinstance(part, dict) else ""


def _words(text: str) -> int:
    return len(text.split())


def _pair_name(pair: dict, index: int) -> str:
    return str(pair.get("pair_id", f"paar #{index + 1}"))


def _check_structure(pairs: list[dict]) -> list[str]:
    out: list[str] = []
    if len(pairs) != N_PAIRS:
        out.append(f"{len(pairs)} paren, verwacht precies {N_PAIRS}")

    for i, pair in enumerate(pairs):
        expected = QUESTION if i % 2 == 0 else ANSWER
        if pair.get("direction") != expected:
            out.append(f"{_pair_name(pair, i)}: richting {pair.get('direction')!r}, "
                       f"verwacht {expected} (afwisselend, beginnend met {QUESTION})")

    rounds = [p.get("round") for p in pairs]
    if not all(isinstance(r, int) and not isinstance(r, bool) for r in rounds):
        out.append(f"round ontbreekt of is geen geheel getal: {rounds}")
        return out
    if any(a > b for a, b in zip(rounds, rounds[1:])):
        out.append(f"round loopt niet op: {rounds}")
    if set(rounds) != ROUNDS:
        out.append(f"rondes zijn {sorted(set(rounds))}, verwacht 1 t/m 4")
    return out


def _check_labels(number: int | None, pairs: list[dict]) -> list[str]:
    out: list[str] = []
    labels = [str(p.get("label")) for p in pairs]
    for i, (pair, label) in enumerate(zip(pairs, labels)):
        if label not in DEVIATIONS | CONTROLS:
            out.append(f"{_pair_name(pair, i)}: onbekend label {label!r}")

    if number is None:
        out.append("session_id heeft niet de vorm S<nummer>; categorieën en uitzondering niet getoetst")
    else:
        digit = number % 10
        wanted = Counter(BY_LAST_DIGIT[digit])
        found = Counter(label for label in labels if label in DEVIATIONS)
        if found != wanted:
            missing = sorted((wanted - found).elements())
            extra = sorted((found - wanted).elements())
            out.append(f"afwijkingen passen niet bij laatste cijfer {digit}: "
                       f"ontbrekend {missing or '–'}, teveel {extra or '–'}")

        expected_exception = EXCEPTION_BY_MOD3[number % 3]
        exceptions = [label for label in labels if label in EXCEPTIONS]
        if exceptions != [expected_exception]:
            out.append(f"uitzondering: gevonden {exceptions or '–'}, verwacht precies één "
                       f"{expected_exception} (nummer modulo 3 = {number % 3})")

    for control in (LITERAL, PARAPHRASE):
        if control not in labels:
            out.append(f"geen {control}")
    return out


def _check_direction_spread(pairs: list[dict]) -> list[str]:
    directions = {p.get("direction") for p in pairs if p.get("label") in DEVIATIONS}
    out = []
    if QUESTION not in directions:
        out.append(f"geen afwijking in een vraag ({QUESTION})")
    if ANSWER not in directions:
        out.append(f"geen afwijking in een antwoord ({ANSWER})")
    return out


def _check_lengths(pairs: list[dict]) -> list[str]:
    out = []
    for i, pair in enumerate(pairs):
        n = _words(_text(pair, "source"))
        if n > MAX_SOURCE_WORDS:
            out.append(f"{_pair_name(pair, i)}: bronuiting van {n} woorden, maximum {MAX_SOURCE_WORDS}")
    answers = [_words(_text(p, "source")) for p in pairs if p.get("direction") == ANSWER]
    for name, low, high in LENGTH_BANDS:
        if not any(low <= n <= high for n in answers):
            out.append(f"geen antwoord in lengteklasse {name}; lengtes: {answers}")
    return out


def _check_pair_fields(pairs: list[dict]) -> list[str]:
    out = []
    for i, pair in enumerate(pairs):
        name = _pair_name(pair, i)
        label = pair.get("label")
        reference = pair.get("reference_rendering")
        if label in DEVIATIONS and not reference:
            out.append(f"{name}: afwijking zonder reference_rendering")
        if label in CONTROLS and reference:
            out.append(f"{name}: controle met reference_rendering")
        if pair.get("subtype") == OWN_QUESTION and pair.get("severity") not in OWN_QUESTION_SEVERITIES:
            out.append(f"{name}: {OWN_QUESTION} met severity {pair.get('severity')!r}, "
                       "verwacht major of critical")
    return out


def lint_session(data: dict) -> list[str]:
    """Return every departure from prompt v2; an empty list means the session is clean."""
    pairs = data.get("pairs")
    if not isinstance(pairs, list) or not all(isinstance(p, dict) for p in pairs):
        return ["pairs ontbreekt of is geen lijst van objecten"]
    return (
        _check_structure(pairs)
        + _check_labels(_session_number(data), pairs)
        + _check_direction_spread(pairs)
        + _check_lengths(pairs)
        + _check_pair_fields(pairs)
    )


def lint_directory(directory: Path) -> tuple[dict[str, list[str]], dict[str, str]]:
    """Return ``(findings per checked session, reason per skipped session)``."""
    findings: dict[str, list[str]] = {}
    skipped: dict[str, str] = {}
    for path in sorted(Path(directory).glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            findings[path.stem] = [f"geen geldige JSON: {exc}"]
            continue
        if not isinstance(data, dict):
            findings[path.stem] = ["bestand bevat geen JSON-object"]
            continue
        name = str(data.get("session_id", path.stem))
        if data.get("split") == "test":
            skipped[name] = "split=test, niet bekeken"
        elif data.get("prompt_version") != PROMPT_VERSION:
            skipped[name] = f"prompt_version={data.get('prompt_version')!r}, regels gelden niet"
        else:
            findings[name] = lint_session(data)
    return findings, skipped


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Toets sessies aan prompt tolkcheck-sessies-v2.")
    parser.add_argument("--sessions-dir", type=Path, default=DEFAULT_DIR,
                        help="map met sessies (standaard: evaluation/data/sessions)")
    args = parser.parse_args(argv)

    if not args.sessions_dir.is_dir():
        print(f"map niet gevonden: {args.sessions_dir}", file=sys.stderr)
        return 2
    findings, skipped = lint_directory(args.sessions_dir)
    for name, problems in findings.items():
        print(f"{name}: {'OK' if not problems else f'{len(problems)} afwijking(en)'}")
        for problem in problems:
            print(f"  - {problem}")
    for name, reason in skipped.items():
        print(f"{name}: overgeslagen ({reason})")
    total = sum(len(p) for p in findings.values())
    print(f"\n{len(findings)} sessie(s) getoetst, {total} afwijking(en), {len(skipped)} overgeslagen.")
    return 1 if total else 0


if __name__ == "__main__":
    raise SystemExit(main())
