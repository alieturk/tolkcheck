"""Check labelled sessions against the rules of prompt ``tolkcheck-sessies-v2``.

Reports, per session, every way it departs from the generation prompt. It reads
the raw JSON rather than going through sessions.py, so a session the loader would
refuse still gets a full list of findings instead of one exception. Standard
library only; no scores are computed here.

Only sessions written with prompt v2 or v3 are checked, because the rules describe
those prompts. Older sessions (S12) are listed as skipped, and so are ``test`` sessions:
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
* "reference_rendering differs only at the labelled spot" is checked on words:
  difflib aligns rendering and reference token by token. One contiguous run of
  changed tokens is fine; so are two runs at most 6 unchanged words apart, because
  one deviation often shows in two places (a Dutch negation, a verb that moves).
  More runs, or two further apart, is a finding. Allowed two-run pairs, and
  references identical to the rendering, are listed as notes, not findings.
  Punctuation stays attached to its word, so "gün." against "gün" is a change.
* Subtypes are checked against the rotation (expected_subtypes) only for prompt v3;
  earlier sessions chose their own.
* controle_taalvariant must sit in an answer (tr->nl): the client uses the dialect
  word. This holds for every prompt version.
* Prompt v4 replaces controle_taalvariant by controle_zelfcorrectie for n mod 3 == 2.
  Its normbron must be "Wbtv regel 18" (a finding); a rendering without the
  interpreter's announcement ("corrigeert", "De tolk", or Turkish "tercüman",
  "düzelt") is only a warning, listed with the notes.
"""
from __future__ import annotations

import argparse
import difflib
import json
import re
import sys
from collections import Counter
from pathlib import Path

PROMPT_VERSION = "tolkcheck-sessies-v2"
# v3 keeps v2's structure, distribution and lengths and only adds content rules
# (one contiguous change per deviation, varied wording, subtype definitions), so
# the same checks apply to both.
V3, V4 = "tolkcheck-sessies-v3", "tolkcheck-sessies-v4"
# v4 = v3 with controle_zelfcorrectie in place of controle_taalvariant (n mod 3 == 2).
PROMPT_VERSIONS = (PROMPT_VERSION, V3, V4)
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
SELF_CORRECTION = "controle_zelfcorrectie"
SELF_CORRECTION_NORM = "Wbtv regel 18"
# Words that show the interpreter announcing the self-correction (Dutch or Turkish).
# Missing them is a warning (a note), not a finding.
SELF_CORRECTION_MARKERS = ("corrigeert", "de tolk", "tercüman", "düzelt")
EXCEPTION_BY_MOD3_V4 = {**EXCEPTION_BY_MOD3, 2: SELF_CORRECTION}
EXCEPTIONS = set(EXCEPTION_BY_MOD3.values()) | {SELF_CORRECTION}
CONTROLS = {LITERAL, PARAPHRASE} | EXCEPTIONS

# Subtypes per category. From prompt v3 on, the generator assigns them per session
# by rotation (expected_subtypes) and the lint checks the session uses exactly those.
SUBTYPES: dict[str, tuple[str, ...]] = {
    OM: ("kernfeit", "detail", "bijzin", "voorwaarde"),
    TOE: ("eigen_vraag_tolk", "eigen_uitleg_tolk", "verzonnen_detail", "eigen_oordeel"),
    BET: ("ontkenning_omgekeerd", "tijd_of_volgorde", "oorzaak_gevolg", "wie_deed_wat",
          "sterker_of_zwakker_gemaakt"),
    ENT: ("naam", "datum", "plaats", "aantal", "tijdsduur"),
    REG: ("voorzichtigheidswoord_weg", "nadruk_weg", "twijfel_weg", "beleefdheid_of_toon"),
}
FIRST_SESSION = 20
SUBTYPE_ROTATION_VERSIONS = {"tolkcheck-sessies-v3", "tolkcheck-sessies-v4"}
DIALECT = "controle_taalvariant"

# Word-level comparison of rendering and reference_rendering per deviation.
MAX_DIFF_RUNS = 2
MAX_DIFF_GAP = 6     # two runs may be at most this many unchanged words apart

MAX_SOURCE_WORDS = 60
LENGTH_BANDS = (("kort (≤15)", 0, 15), ("middellang (15–35)", 15, 35), ("lang (35–60)", 35, 60))
OWN_QUESTION = "eigen_vraag_tolk"
OWN_QUESTION_SEVERITIES = {"major", "critical"}


def exceptions_for(version: object) -> dict[int, str]:
    """The permitted-exception control per number modulo 3, for this prompt version."""
    return EXCEPTION_BY_MOD3_V4 if version == V4 else EXCEPTION_BY_MOD3


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


def _check_labels(number: int | None, pairs: list[dict], version: object = None) -> list[str]:
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

        expected_exception = exceptions_for(version)[number % 3]
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


def expected_subtypes(number: int) -> dict[str, str]:
    """The subtype per deviation category for session ``number``.

    Each category goes round its subtypes in the order of SUBTYPES, counting only
    the sessions from FIRST_SESSION on that contain the category. So over any run of
    sessions starting at S20 every subtype of a category occurs equally often (give
    or take one)."""
    out = {}
    for category in BY_LAST_DIGIT[number % 10]:
        seen = sum(1 for m in range(FIRST_SESSION, number) if category in BY_LAST_DIGIT[m % 10])
        options = SUBTYPES[category]
        out[category] = options[seen % len(options)]
    return out


def word_diff(rendering: str, reference: str) -> tuple[list[tuple[str, str]], list[int]]:
    """Contiguous runs of differing words, as (rendering part, reference part), and
    the number of unchanged words between consecutive runs."""
    a, b = rendering.split(), reference.split()
    runs: list[tuple[str, str]] = []
    gaps: list[int] = []
    in_run = False
    pending_gap = 0
    matcher = difflib.SequenceMatcher(None, a, b, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            in_run = False
            pending_gap = i2 - i1
            continue
        part = (" ".join(a[i1:i2]), " ".join(b[j1:j2]))
        if in_run:   # two non-equal opcodes next to each other are still one run
            prev = runs[-1]
            runs[-1] = (" ".join(x for x in (prev[0], part[0]) if x),
                        " ".join(x for x in (prev[1], part[1]) if x))
        else:
            if runs:
                gaps.append(pending_gap)
            runs.append(part)
        in_run = True
    return runs, gaps


def diff_runs(rendering: str, reference: str) -> list[tuple[str, str]]:
    """Contiguous runs of differing words, as (rendering part, reference part)."""
    return word_diff(rendering, reference)[0]


def diff_allowed(runs: list, gaps: list[int]) -> bool:
    """One run, or two runs at most MAX_DIFF_GAP unchanged words apart."""
    if len(runs) <= 1:
        return True
    return len(runs) <= MAX_DIFF_RUNS and all(g <= MAX_DIFF_GAP for g in gaps)


def describe_diff(rendering: str, reference: str) -> str:
    """Short text for reports: number of runs and, with two or more, the words between."""
    runs, gaps = word_diff(rendering, reference)
    if len(runs) == 2:
        return f"2 ({gaps[0]} ertussen)"
    if len(runs) > 2:
        return f"{len(runs)} ({', '.join(map(str, gaps))} ertussen)"
    return str(len(runs))


def _show(runs: list[tuple[str, str]]) -> str:
    return "; ".join(f"«{r or '–'}» ↔ «{f or '–'}»" for r, f in runs)


def _deviations_with_reference(pairs: list[dict]):
    for i, pair in enumerate(pairs):
        reference = pair.get("reference_rendering")
        if pair.get("label") in DEVIATIONS and reference:
            yield i, pair, str(reference)


def _check_reference_diff(pairs: list[dict]) -> list[str]:
    out = []
    for i, pair, reference in _deviations_with_reference(pairs):
        runs, gaps = word_diff(_text(pair, "rendering"), reference)
        if not diff_allowed(runs, gaps):
            if len(runs) > MAX_DIFF_RUNS:
                why = f"{len(runs)} plaatsen, hooguit {MAX_DIFF_RUNS}"
            else:
                why = f"2 plaatsen die {gaps[0]} woorden uit elkaar liggen, hooguit {MAX_DIFF_GAP}"
            out.append(f"{_pair_name(pair, i)}: rendering en reference_rendering verschillen op "
                       f"{why}: {_show(runs)}")
    return out


def _check_subtypes(number: int | None, version: object, pairs: list[dict]) -> list[str]:
    if number is None or version not in SUBTYPE_ROTATION_VERSIONS:
        return []
    wanted = expected_subtypes(number)
    out = []
    for i, pair in enumerate(pairs):
        label = pair.get("label")
        if label in wanted and pair.get("subtype") != wanted[label]:
            out.append(f"{_pair_name(pair, i)}: subtype {pair.get('subtype')!r} bij {label}, "
                       f"verwacht {wanted[label]!r} (rotatie voor S{number})")
    return out


def _check_dialect_direction(pairs: list[dict]) -> list[str]:
    return [f"{_pair_name(pair, i)}: {DIALECT} in een {pair.get('direction')}-paar; "
            f"de cliënt gebruikt het dialectwoord, dus verwacht {ANSWER}"
            for i, pair in enumerate(pairs)
            if pair.get("label") == DIALECT and pair.get("direction") != ANSWER]


def _check_self_correction(pairs: list[dict]) -> list[str]:
    return [f"{_pair_name(pair, i)}: {SELF_CORRECTION} met normbron {pair.get('normbron')!r}, "
            f"verwacht {SELF_CORRECTION_NORM!r}"
            for i, pair in enumerate(pairs)
            if pair.get("label") == SELF_CORRECTION and pair.get("normbron") != SELF_CORRECTION_NORM]


def lint_session(data: dict) -> list[str]:
    """Return every departure from the prompt; an empty list means the session is clean."""
    pairs = data.get("pairs")
    if not isinstance(pairs, list) or not all(isinstance(p, dict) for p in pairs):
        return ["pairs ontbreekt of is geen lijst van objecten"]
    number = _session_number(data)
    return (
        _check_structure(pairs)
        + _check_labels(number, pairs, data.get("prompt_version"))
        + _check_direction_spread(pairs)
        + _check_lengths(pairs)
        + _check_pair_fields(pairs)
        + _check_reference_diff(pairs)
        + _check_subtypes(number, data.get("prompt_version"), pairs)
        + _check_dialect_direction(pairs)
        + _check_self_correction(pairs)
    )


def session_notes(data: dict) -> list[str]:
    """Worth recording, not findings: deviations whose reference differs in two places
    close together (allowed), or not at all. Never sent to the model."""
    pairs = data.get("pairs")
    if not isinstance(pairs, list) or not all(isinstance(p, dict) for p in pairs):
        return []
    out = []
    for i, pair, reference in _deviations_with_reference(pairs):
        runs, gaps = word_diff(_text(pair, "rendering"), reference)
        if len(runs) == 2 and diff_allowed(runs, gaps):
            out.append(f"{_pair_name(pair, i)}: 2 woordverschillen, {gaps[0]} woord(en) ertussen "
                       f"(toegestaan): {_show(runs)}")
        elif not runs:
            out.append(f"{_pair_name(pair, i)}: reference_rendering gelijk aan de rendering")
    for i, pair in enumerate(pairs):
        if pair.get("label") == SELF_CORRECTION:
            text = _text(pair, "rendering").lower()
            if not any(marker in text for marker in SELF_CORRECTION_MARKERS):
                out.append(f"{_pair_name(pair, i)}: waarschuwing: {SELF_CORRECTION} zonder melding "
                           f"van de tolk in de rendering (gezocht: {', '.join(SELF_CORRECTION_MARKERS)})")
    return out


def lint_directory(directory: Path, notes: dict[str, list[str]] | None = None
                   ) -> tuple[dict[str, list[str]], dict[str, str]]:
    """Return ``(findings per checked session, reason per skipped session)``.
    Pass a dict as ``notes`` to also collect session_notes per checked session."""
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
        elif data.get("prompt_version") not in PROMPT_VERSIONS:
            skipped[name] = f"prompt_version={data.get('prompt_version')!r}, regels gelden niet"
        else:
            findings[name] = lint_session(data)
            if notes is not None:
                notes[name] = session_notes(data)
    return findings, skipped


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):   # Windows consoles default to cp1252
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="Toets sessies aan prompt tolkcheck-sessies-v2/v3/v4.")
    parser.add_argument("--sessions-dir", type=Path, default=DEFAULT_DIR,
                        help="map met sessies (standaard: evaluation/data/sessions)")
    args = parser.parse_args(argv)

    if not args.sessions_dir.is_dir():
        print(f"map niet gevonden: {args.sessions_dir}", file=sys.stderr)
        return 2
    notes: dict[str, list[str]] = {}
    findings, skipped = lint_directory(args.sessions_dir, notes)
    for name, problems in findings.items():
        print(f"{name}: {'OK' if not problems else f'{len(problems)} afwijking(en)'}")
        for problem in problems:
            print(f"  - {problem}")
        for note in notes.get(name, []):
            print(f"  · {note}")
    for name, reason in skipped.items():
        print(f"{name}: overgeslagen ({reason})")
    total = sum(len(p) for p in findings.values())
    print(f"\n{len(findings)} sessie(s) getoetst, {total} afwijking(en), {len(skipped)} overgeslagen.")
    return 1 if total else 0


if __name__ == "__main__":
    raise SystemExit(main())
