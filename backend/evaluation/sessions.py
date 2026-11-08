"""Loader for labelled test sessions (evaluation/data/sessions/*.json).

One JSON file per synthetic session, in the format of S12.json: session
metadata, the TTS voices, and an ordered list of source/rendering pairs, each
labelled with a deviation category and whether the tool is expected to flag it.

This module only reads and checks that format. It deliberately imports nothing
from app/ and nothing outside the standard library, so the metrics and their
tests run without model weights.

Categories
----------
Labels map onto the five DV4 report categories below. Every ``controle_*``
label is a negative control: a rendering that is correct (or a permitted
exception such as a paraphrase announced by the interpreter) and must NOT be
flagged. Anything else is rejected rather than silently counted, so a typo in a
label cannot move a pair between categories.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

CATEGORIES: tuple[str, ...] = (
    "omissie",
    "toevoeging",
    "betekenisverschuiving",
    "entiteitsfout",
    "register_en_nadruk",
)
CONTROL_PREFIX = "controle"
SPLITS = ("dev", "test", "draft")
DIRECTIONS = {"nl->tr": ("nl", "tr"), "tr->nl": ("tr", "nl")}


class SessionFormatError(ValueError):
    """A session file does not match the expected format."""


@dataclass(frozen=True)
class Pair:
    pair_id: str
    session_id: str
    split: str
    reviewed: bool
    order: int
    direction: str            # "nl->tr" | "tr->nl"
    source_lang: str
    target_lang: str
    source_text: str
    rendering_text: str
    label: str                # raw label from the file
    category: str | None      # one of CATEGORIES, or None for a control
    subtype: str | None
    severity: str
    expected_flag: bool
    reference_text: str | None
    round: int | None = None  # interview round; absent in sessions before prompt v2

    @property
    def is_control(self) -> bool:
        return self.category is None

    @property
    def source_words(self) -> int:
        return len(self.source_text.split())


@dataclass
class Session:
    session_id: str
    split: str
    reviewed: bool
    language_pair: str
    path: Path
    pairs: list[Pair] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    reviewed_by: str | None = None
    prompt_version: str | None = None
    interpreter_voices: tuple[str, ...] = ()


def _interpreter_voices(value: object, where: str) -> tuple[str, ...]:
    """``voices.interpreter`` is one voice (string) or one voice per language (dict)."""
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    if isinstance(value, dict):
        return tuple(str(v) for v in value.values())
    raise SessionFormatError(
        f"{where}: voices.interpreter must be a string or an object, got {type(value).__name__}"
    )


def _round(value: object, where: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise SessionFormatError(f"{where}: round must be an integer, got {value!r}")
    return value


def _category(label: str, where: str) -> str | None:
    if label.startswith(CONTROL_PREFIX):
        return None
    if label in CATEGORIES:
        return label
    raise SessionFormatError(
        f"{where}: unknown label {label!r}; expected one of {', '.join(CATEGORIES)} "
        f"or a label starting with {CONTROL_PREFIX!r}"
    )


def load_session(path: Path) -> Session:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SessionFormatError(f"{path.name}: not valid JSON ({exc})") from exc

    for key in ("session_id", "split", "pairs"):
        if key not in data:
            raise SessionFormatError(f"{path.name}: missing key {key!r}")
    sid = str(data["session_id"])
    split = str(data["split"])
    if split not in SPLITS:
        raise SessionFormatError(f"{path.name}: split {split!r} not in {SPLITS}")
    reviewed = bool(data.get("reviewed", False))
    session = Session(
        sid, split, reviewed, str(data.get("language_pair", "")), Path(path),
        reviewed_by=data.get("reviewed_by"),
        prompt_version=data.get("prompt_version"),
    )

    # One interpreter, one voice: two voice profiles for the interpreter make the
    # diarizer hear four speakers where the pipeline expects three, which tests
    # the fixture rather than the tool. Only a warning here — this loader is used
    # for the text-level measurement, where voices do not matter — but layer 2
    # (audio) must not run on such a session.
    session.interpreter_voices = _interpreter_voices(
        (data.get("voices") or {}).get("interpreter"), path.name
    )
    distinct = sorted(set(session.interpreter_voices))
    if len(distinct) > 1:
        session.warnings.append(
            f"{sid}: interpreter has {len(distinct)} different voices "
            f"({', '.join(distinct)}); fine for text-level "
            "scoring, not for an audio run"
        )

    seen: set[str] = set()
    for i, raw in enumerate(data["pairs"]):
        where = f"{path.name} pair #{i + 1}"
        try:
            pid = str(raw["pair_id"])
            direction = str(raw["direction"])
            src = raw["source"]
            ren = raw["rendering"]
            label = str(raw["label"])
        except (KeyError, TypeError) as exc:
            raise SessionFormatError(f"{where}: missing field {exc}") from exc
        if pid in seen:
            raise SessionFormatError(f"{where}: duplicate pair_id {pid!r}")
        seen.add(pid)
        if direction not in DIRECTIONS:
            raise SessionFormatError(f"{where}: direction {direction!r} not in {list(DIRECTIONS)}")
        s_lang, t_lang = DIRECTIONS[direction]
        if src.get("lang") != s_lang or ren.get("lang") != t_lang:
            raise SessionFormatError(
                f"{where}: languages {src.get('lang')}->{ren.get('lang')} do not match "
                f"direction {direction}"
            )
        category = _category(label, where)
        expected = bool(raw.get("expected_flag", category is not None))
        if category is None and expected:
            raise SessionFormatError(f"{where}: control pair {pid} has expected_flag=true")
        if category is not None and not expected:
            session.warnings.append(
                f"{pid}: labelled {category} but expected_flag=false; counted as a control"
            )
            category = None
        session.pairs.append(Pair(
            pair_id=pid,
            session_id=sid,
            split=split,
            reviewed=reviewed,
            order=int(raw.get("order", i + 1)),
            direction=direction,
            source_lang=s_lang,
            target_lang=t_lang,
            source_text=str(src.get("text", "")),
            rendering_text=str(ren.get("text", "")),
            label=label,
            category=category,
            subtype=raw.get("subtype"),
            severity=str(raw.get("severity", "")),
            expected_flag=expected,
            reference_text=raw.get("reference_rendering"),
            round=_round(raw.get("round"), where),
        ))
    return session


def load_sessions(directory: Path) -> list[Session]:
    files = sorted(Path(directory).glob("*.json"))
    return [load_session(f) for f in files]
