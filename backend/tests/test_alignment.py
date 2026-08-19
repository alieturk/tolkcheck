"""Unit tests for services/alignment.py — speaker-block pairing for bidirectional
consecutive interpretation.

The three public functions form a chain, and each is tested at its own level:

  build_blocks        segments  → speaker blocks (merge + role assignment)
  classify_directions blocks    → blocks with direction on interpreter blocks
  extract_pairs       blocks    → (c2o_pairs, o2c_pairs)

All three are pure: no DB, no ML models, no network calls.
"""
from __future__ import annotations

from app.services import alignment
from tests.conftest import make_seg

CLIENT = "SPEAKER_00"
INTERP = "SPEAKER_01"
OFFICER = "SPEAKER_02"


# ── Helpers ───────────────────────────────────────────────────────────────────

def build(segments: list[dict], **kwargs) -> list[dict]:
    """Shorthand: build_blocks with this module's speaker labels."""
    return alignment.build_blocks(
        segments, interpreter_speaker=INTERP, client_speaker=CLIENT, **kwargs
    )


def classified(segments: list[dict], client_lang: str = "tr") -> list[dict]:
    """build_blocks + classify_directions. client_lang defaults to "tr" — this
    file's fixtures consistently use "tr" as the client's source language."""
    return alignment.classify_directions(build(segments), client_lang)


def pairs(segments: list[dict]) -> tuple[list[dict], list[dict]]:
    """Full chain: segments → (c2o_pairs, o2c_pairs)."""
    return alignment.extract_pairs(classified(segments))


def texts(pair_list: list[dict]) -> list[tuple[str, str]]:
    """Reduce pairs to (source_text, interpreter_text) tuples for readable asserts."""
    return [(p["source_block"]["text"], p["interp_block"]["text"]) for p in pair_list]


# A full two-round IND exchange, following the protocol in the module docstring:
#   OFFICER → INTERP (relay to client) → CLIENT → INTERP (to officer) → OFFICER → …
FULL_EXCHANGE = [
    make_seg(OFFICER, "Waar komt u vandaan?",       0,  3),
    make_seg(INTERP,  "Nereden geliyorsunuz?",      4,  7,  language="tr"),
    make_seg(CLIENT,  "Kabil'den geliyorum.",       8,  14, language="tr"),
    make_seg(INTERP,  "Ik kom uit Kabul.",          15, 19),
    make_seg(OFFICER, "Wanneer bent u vertrokken?", 20, 23),
    make_seg(INTERP,  "Ne zaman ayrildiniz?",       24, 27, language="tr"),
    make_seg(CLIENT,  "Agustos 2022'de.",           28, 34, language="tr"),
    make_seg(INTERP,  "In augustus 2022.",          35, 39),
]


# ── build_blocks ──────────────────────────────────────────────────────────────

class TestBuildBlocks:
    def test_empty_segments(self):
        assert build([]) == []

    def test_roles_assigned_from_speaker_labels(self):
        segs = [
            make_seg(CLIENT,  "C.", 0,  5),
            make_seg(INTERP,  "I.", 6,  10),
            make_seg(OFFICER, "O.", 11, 15),
        ]
        assert [b["role"] for b in build(segs)] == ["client", "interpreter", "officer"]

    def test_unrecognised_speaker_falls_back_to_officer(self):
        """Any label that is neither the interpreter nor the client is treated as officer."""
        segs = [make_seg("UNKNOWN", "?", 0, 2)]
        assert build(segs)[0]["role"] == "officer"

    def test_consecutive_same_speaker_merged(self):
        """Two client segments within the gap threshold become one block."""
        segs = [
            make_seg(CLIENT, "Zin 1.", 0, 5),
            make_seg(CLIENT, "Zin 2.", 6, 10),
        ]
        blocks = build(segs)
        assert len(blocks) == 1
        assert blocks[0]["text"] == "Zin 1. Zin 2."
        assert blocks[0]["start"] == 0
        assert blocks[0]["end"] == 10
        assert len(blocks[0]["segments"]) == 2

    def test_many_consecutive_segments_merged_into_one_block(self):
        segs = [make_seg(INTERP, f"Deel {i}.", i * 5, i * 5 + 4) for i in range(10)]
        blocks = build(segs)
        assert len(blocks) == 1
        assert blocks[0]["text"] == " ".join(f"Deel {i}." for i in range(10))

    def test_gap_above_threshold_splits_same_speaker(self):
        """A silence longer than gap_s starts a new block even for the same speaker."""
        segs = [
            make_seg(CLIENT, "Voor de pauze.", 0,   5),
            make_seg(CLIENT, "Na de pauze.",   8.5, 12),  # gap 3.5s > 3.0s
        ]
        blocks = build(segs)
        assert len(blocks) == 2
        assert [b["text"] for b in blocks] == ["Voor de pauze.", "Na de pauze."]

    def test_gap_exactly_at_threshold_still_merges(self):
        """The threshold is inclusive: gap == gap_s merges."""
        segs = [
            make_seg(CLIENT, "Eerste.", 0, 5),
            make_seg(CLIENT, "Tweede.", 8, 10),  # gap exactly 3.0s
        ]
        assert len(build(segs)) == 1

    def test_gap_s_is_configurable(self):
        segs = [
            make_seg(CLIENT, "Eerste.", 0,  5),
            make_seg(CLIENT, "Tweede.", 15, 20),
        ]
        assert len(build(segs)) == 2                  # default gap_s=3.0 → split
        assert len(build(segs, gap_s=10.0)) == 1      # wider window → merged

    def test_speaker_change_always_starts_new_block(self):
        """Even with no gap at all, a different speaker means a different block."""
        segs = [
            make_seg(CLIENT, "C.", 0, 5),
            make_seg(INTERP, "I.", 5, 8),
            make_seg(CLIENT, "C.", 8, 10),
        ]
        assert len(build(segs)) == 3

    def test_segments_are_sorted_by_start_time(self):
        segs = [
            make_seg(CLIENT,  "Derde.",  20, 25),
            make_seg(OFFICER, "Eerste.", 0,  5),
            make_seg(INTERP,  "Tweede.", 10, 15),
        ]
        assert [b["text"] for b in build(segs)] == ["Eerste.", "Tweede.", "Derde."]

    def test_language_comes_from_first_segment_of_block(self):
        """Only reachable when consecutive same-speaker segments agree on
        language — see test_language_change_starts_new_block below for what
        happens when they don't (they no longer merge at all)."""
        segs = [
            make_seg(CLIENT, "Turks.", 0, 5,  language="tr"),
            make_seg(CLIENT, "Ook.",   6, 10, language="tr"),
        ]
        assert build(segs)[0]["language"] == "tr"

    def test_language_change_starts_new_block_even_within_gap(self):
        """A language change ends a block, same as a speaker change. Two turns
        from the same speaker within the gap threshold that disagree on
        detected language must NOT merge into one block — classify_directions
        reads a block's language as its primary signal, so a merged block
        could only carry one (stale, partially wrong) language tag for text
        that actually crossed a language boundary."""
        segs = [
            make_seg(INTERP, "Turks deel.",      0,   2, language="tr"),
            make_seg(INTERP, "Nederlands deel.", 2.4, 5, language="nl"),  # gap 0.4s — well within threshold
        ]
        blocks = build(segs)
        assert len(blocks) == 2
        assert [b["text"] for b in blocks] == ["Turks deel.", "Nederlands deel."]
        assert [b["language"] for b in blocks] == ["tr", "nl"]

    def test_direction_starts_as_none(self):
        """build_blocks leaves direction unset — classify_directions fills it in."""
        blocks = build(FULL_EXCHANGE)
        assert all(b["direction"] is None for b in blocks)


# ── classify_directions ───────────────────────────────────────────────────────

class TestClassifyDirections:
    def test_interpreter_before_client_is_to_client(self):
        """Interpreter followed by the client → relay of the officer's question.

        Interpreter's language ("tr") matches client_lang, so this is also
        the language-primary result, not just the next-role fallback.
        """
        segs = [
            make_seg(OFFICER, "Vraag.",    0, 3),
            make_seg(INTERP,  "Soru.",     4, 8, language="tr"),
            make_seg(CLIENT,  "Antwoord.", 9, 15, language="tr"),
        ]
        assert classified(segs)[1]["direction"] == "to_client"

    def test_interpreter_before_officer_is_to_officer(self):
        """Interpreter followed by the officer → the legally decisive translation.

        Interpreter's language ("nl", the make_seg default) matches "nl", so
        this is also the language-primary result, not just the next-role
        fallback.
        """
        segs = [
            make_seg(CLIENT,  "Antwoord.",  0,  6, language="tr"),
            make_seg(INTERP,  "Vertaling.", 7,  11),
            make_seg(OFFICER, "Dank u.",    12, 15),
        ]
        assert classified(segs)[1]["direction"] == "to_officer"

    def test_trailing_interpreter_defaults_to_officer(self):
        """Nothing follows the interpreter → assumed to be addressed to the officer.

        language="und" deliberately matches neither client_lang nor "nl", so
        this exercises the next-role fallback path specifically rather than
        the language-primary path (see test_interpreter_before_officer_is_to_officer
        for that one).
        """
        segs = [
            make_seg(CLIENT, "Antwoord.",  0, 6, language="tr"),
            make_seg(INTERP, "Vertaling.", 7, 11, language="und"),
        ]
        assert classified(segs)[-1]["direction"] == "to_officer"

    def test_non_interpreter_blocks_are_left_alone(self):
        blocks = classified(FULL_EXCHANGE)
        assert all(b["direction"] is None for b in blocks if b["role"] != "interpreter")

    def test_lookahead_skips_over_other_interpreter_blocks(self):
        """A pause splits the interpreter into two blocks; both look past each other
        to the next real speaker, so both get the same direction.

        language="tr" on both so this tests the lookahead-skipping structure
        itself (via the fallback path would also work, but tagging them "tr"
        keeps this test aligned with what real Whisper output for a relay-to-
        client turn would actually look like, same as test_lookahead's siblings).
        """
        segs = [
            make_seg(OFFICER, "Vraag.",    0,  3),
            make_seg(INTERP,  "Deel 1.",   4,  8,  language="tr"),
            make_seg(INTERP,  "Deel 2.",   20, 25, language="tr"),  # gap 12s → separate block
            make_seg(CLIENT,  "Antwoord.", 26, 32, language="tr"),
        ]
        blocks = classified(segs)
        assert [b["direction"] for b in blocks[1:3]] == ["to_client", "to_client"]

    def test_mutates_and_returns_the_same_list(self):
        blocks = build(FULL_EXCHANGE)
        assert alignment.classify_directions(blocks, "tr") is blocks

    def test_language_overrides_next_role_heuristic(self):
        """Regression test for the bug this change fixes: when the interpreter's
        detected language contradicts what the next-role heuristic would have
        guessed, the language wins.

        Client answers (tr), interpreter translates into Dutch for the officer
        (nl — a genuine to_officer translation) — but the client then speaks
        again instead of the officer responding. The old next-role-only logic
        read "next role == client" and misclassified the interpreter block as
        to_client. Language says otherwise and is now what decides it.
        """
        segs = [
            make_seg(CLIENT, "Antwoord.",  0, 6,  language="tr"),
            make_seg(INTERP, "Vertaling.", 7, 11),                  # language="nl" (default)
            make_seg(CLIENT, "Meer.",      17, 22, language="tr"),  # gap 6s → new block, not officer
        ]
        assert classified(segs)[1]["direction"] == "to_officer"

    def test_ambiguous_language_falls_back_to_next_role(self):
        """When the interpreter block's language is neither client_lang nor "nl"
        (e.g. a bad Whisper detection on a short/unclear turn), classification
        falls back to the next-role heuristic instead of trusting a language
        tag that doesn't match either expected language."""
        segs = [
            make_seg(OFFICER, "Vraag.",    0, 3),
            make_seg(INTERP,  "Soru.",     4, 8, language="und"),  # neither "tr" nor "nl"
            make_seg(CLIENT,  "Antwoord.", 9, 15, language="tr"),
        ]
        assert classified(segs)[1]["direction"] == "to_client"  # next-role fallback

    def test_full_exchange_alternates_direction(self):
        directions = [
            b["direction"] for b in classified(FULL_EXCHANGE) if b["role"] == "interpreter"
        ]
        assert directions == ["to_client", "to_officer", "to_client", "to_officer"]


# ── extract_pairs ─────────────────────────────────────────────────────────────

class TestExtractPairs:
    def test_empty_blocks(self):
        assert alignment.extract_pairs([]) == ([], [])

    def test_client_to_officer_pair(self):
        segs = [
            make_seg(CLIENT,  "Ik kom uit Kabul.", 0,  6, language="tr"),
            make_seg(INTERP,  "Ik kom uit Kabul.", 7,  11),
            make_seg(OFFICER, "Dank u.",           12, 15),
        ]
        c2o, o2c = pairs(segs)
        assert o2c == []
        assert texts(c2o) == [("Ik kom uit Kabul.", "Ik kom uit Kabul.")]

    def test_officer_to_client_pair(self):
        segs = [
            make_seg(OFFICER, "Waar komt u vandaan?",  0, 3),
            make_seg(INTERP,  "Nereden geliyorsunuz?", 4, 8, language="tr"),
            make_seg(CLIENT,  "Kabil'den.",            9, 15, language="tr"),
        ]
        c2o, o2c = pairs(segs)
        assert c2o == []
        assert texts(o2c) == [("Waar komt u vandaan?", "Nereden geliyorsunuz?")]

    def test_pair_shape(self):
        blocks = classified(FULL_EXCHANGE)
        c2o, o2c = alignment.extract_pairs(blocks)
        pair = c2o[0]
        assert set(pair) == {"direction", "source_block", "interp_block", "pair_index"}
        assert pair["direction"] == "client_to_officer"
        assert o2c[0]["direction"] == "officer_to_client"
        # Pairs reference the block dicts themselves, not copies
        assert any(pair["source_block"] is b for b in blocks)
        assert any(pair["interp_block"] is b for b in blocks)

    def test_pair_index_is_per_list(self):
        c2o, o2c = pairs(FULL_EXCHANGE)
        assert [p["pair_index"] for p in c2o] == [0, 1]
        assert [p["pair_index"] for p in o2c] == [0, 1]

    def test_full_exchange_yields_both_directions(self):
        c2o, o2c = pairs(FULL_EXCHANGE)
        assert texts(c2o) == [
            ("Kabil'den geliyorum.", "Ik kom uit Kabul."),
            ("Agustos 2022'de.",     "In augustus 2022."),
        ]
        assert texts(o2c) == [
            ("Waar komt u vandaan?",       "Nereden geliyorsunuz?"),
            ("Wanneer bent u vertrokken?", "Ne zaman ayrildiniz?"),
        ]

    def test_nearest_preceding_client_wins(self):
        """With two client blocks before the interpreter, the closest one is paired."""
        segs = [
            make_seg(CLIENT,  "Oud antwoord.",  0,  5,  language="tr"),
            make_seg(OFFICER, "Nieuwe vraag.",  6,  9),
            make_seg(CLIENT,  "Vers antwoord.", 10, 15, language="tr"),
            make_seg(INTERP,  "Vers vertaald.", 16, 20),
            make_seg(OFFICER, "Dank u.",        21, 24),
        ]
        c2o, _ = pairs(segs)
        assert texts(c2o) == [("Vers antwoord.", "Vers vertaald.")]

    def test_officer_interruption_splits_the_interpretation(self):
        """An officer interjecting mid-interpretation ends the interpreter block, and
        the continuation after it is classified as a relay back to the client."""
        segs = [
            make_seg(CLIENT,  "Client A.",         0,  10, language="tr"),
            make_seg(INTERP,  "Interp A1.",        11, 20),
            make_seg(OFFICER, "Verduidelijk dat.", 21, 24),
            make_seg(INTERP,  "Interp A2.",        25, 35, language="tr"),  # relayed to client
            make_seg(CLIENT,  "Client B.",         36, 45, language="tr"),
            make_seg(INTERP,  "Interp B.",         46, 55),
            make_seg(OFFICER, "Dank u.",           56, 60),
        ]
        c2o, o2c = pairs(segs)
        assert texts(c2o) == [("Client A.", "Interp A1."), ("Client B.", "Interp B.")]
        assert texts(o2c) == [("Verduidelijk dat.", "Interp A2.")]

    def test_to_officer_without_preceding_client_is_dropped(self):
        segs = [
            make_seg(OFFICER, "Alleen de ambtenaar.", 0, 3),
            make_seg(INTERP,  "En de tolk.",          4, 8),
        ]
        assert pairs(segs) == ([], [])

    def test_to_client_without_preceding_officer_is_dropped(self):
        """Interpreter speaking before anyone else has no source block to pair with."""
        segs = [
            make_seg(INTERP, "Vooraf.", 0, 3, language="tr"),  # to_client (next role: client)
            make_seg(CLIENT, "Client.", 4, 9, language="tr"),
        ]
        assert pairs(segs) == ([], [])

    def test_no_interpreter_turns(self):
        segs = [
            make_seg(CLIENT,  "Ik spreek.", 0, 5, language="tr"),
            make_seg(OFFICER, "Dank u.",    6, 8),
        ]
        assert pairs(segs) == ([], [])

    def test_only_officer_turns(self):
        segs = [make_seg(OFFICER, f"Vraag {i}.", i * 5, i * 5 + 3) for i in range(5)]
        assert pairs(segs) == ([], [])

    def test_client_speaking_again_no_longer_breaks_the_pairing(self):
        """Formerly a known limit of the next-role-only heuristic: when the client
        speaks again straight after the interpreter (instead of the officer taking
        the floor), the old logic read "next role == client" and misclassified a
        genuine to_officer translation as a relay *to* the client — losing the pair
        entirely, since there was no preceding officer block to match it against.

        The interpreter's own language ("nl", the make_seg default — this really
        was a Dutch translation of the client's answer) now overrides that guess,
        so the pair survives. See also
        TestClassifyDirections.test_language_overrides_next_role_heuristic, which
        tests the same fix at the classify_directions level directly.
        """
        segs = [
            make_seg(CLIENT, "Antwoord deel 1.", 0,  10, language="tr"),
            make_seg(INTERP, "Vertaling.",       11, 20),                    # language="nl" (default)
            make_seg(CLIENT, "Antwoord deel 2.", 25, 35, language="tr"),  # gap 5s → new block
        ]
        c2o, o2c = pairs(segs)
        assert texts(c2o) == [("Antwoord deel 1.", "Vertaling.")]
        assert o2c == []
