"""Unit tests for _align_blocks — the block-level client/interpreter pairing logic.

_align_blocks is a pure function: no DB, no ML models, no network calls.
Each test documents one specific behaviour or edge case.
"""
from __future__ import annotations

import pytest

from app.pipeline import _align_blocks
from tests.conftest import make_seg

CLIENT = "SPEAKER_00"
INTERP = "SPEAKER_01"
OFFICER = "SPEAKER_02"


# ── Helpers ───────────────────────────────────────────────────────────────────

def align(segments: list[dict]) -> tuple[list[str], list[str]]:
    """Shorthand: run _align_blocks and return (interp_texts, client_texts)."""
    return _align_blocks(segments, interpreter_speaker=INTERP, client_speaker=CLIENT)


# ── Happy-path cases ──────────────────────────────────────────────────────────

class TestHappyPath:
    def test_single_pair(self):
        """One client block followed by one interpreter block → one pair."""
        segs = [
            make_seg(CLIENT, "Ik kom uit Kabul.", 0, 5),
            make_seg(INTERP,  "Ik kom uit Kabul.", 6, 10),
        ]
        interp, client = align(segs)
        assert len(interp) == 1
        assert len(client) == 1
        assert client[0] == "Ik kom uit Kabul."
        assert interp[0] == "Ik kom uit Kabul."

    def test_three_clean_pairs(self):
        """Three client blocks each followed by an interpreter block → three pairs."""
        segs = [
            make_seg(CLIENT, "Block A.", 0, 5),
            make_seg(INTERP,  "Block A NL.", 6, 10),
            make_seg(CLIENT, "Block B.", 11, 15),
            make_seg(INTERP,  "Block B NL.", 16, 20),
            make_seg(CLIENT, "Block C.", 21, 25),
            make_seg(INTERP,  "Block C NL.", 26, 30),
        ]
        interp, client = align(segs)
        assert client == ["Block A.", "Block B.", "Block C."]
        assert interp == ["Block A NL.", "Block B NL.", "Block C NL."]

    def test_officer_between_client_and_interpreter(self):
        """Officer turn between client and interpreter does not break pairing."""
        segs = [
            make_seg(CLIENT,  "Ik ben leraar.", 0, 5),
            make_seg(OFFICER, "Wanneer precies?", 6, 8),
            make_seg(INTERP,  "Ik ben leraar NL.", 9, 14),
        ]
        interp, client = align(segs)
        assert len(client) == 1
        assert client[0] == "Ik ben leraar."
        assert interp[0] == "Ik ben leraar NL."

    def test_multiple_interpreter_segments_per_block(self):
        """Several consecutive interpreter segments are concatenated into one block text."""
        segs = [
            make_seg(CLIENT, "Lang verhaal.", 0, 30),
            make_seg(INTERP,  "Deel 1.", 31, 40),
            make_seg(INTERP,  "Deel 2.", 41, 50),
            make_seg(INTERP,  "Deel 3.", 51, 60),
        ]
        interp, client = align(segs)
        assert len(client) == 1
        assert interp[0] == "Deel 1. Deel 2. Deel 3."

    def test_officer_interrupts_interpreter_block(self):
        """Officer interjecting mid-interpretation still lets interpreter continue same block."""
        segs = [
            make_seg(CLIENT,  "Client A.", 0, 10),
            make_seg(INTERP,  "Interp A1.", 11, 20),
            make_seg(OFFICER, "Kunt u dat verduidelijken?", 21, 24),
            make_seg(INTERP,  "Interp A2.", 25, 35),
            make_seg(CLIENT,  "Client B.", 36, 45),
            make_seg(INTERP,  "Interp B.", 46, 55),
        ]
        interp, client = align(segs)
        # Client A should map to both interpreter segments for block A
        assert len(client) == 2
        assert client[0] == "Client A."
        assert interp[0] == "Interp A1. Interp A2."
        assert client[1] == "Client B."
        assert interp[1] == "Interp B."

    def test_multiple_client_segments_merged_into_block(self):
        """Consecutive client segments are merged into one block before pairing."""
        segs = [
            make_seg(CLIENT, "Zin 1.", 0, 5),
            make_seg(CLIENT, "Zin 2.", 6, 10),   # consecutive → same block
            make_seg(INTERP, "Zin 1 en 2 NL.", 11, 20),
        ]
        interp, client = align(segs)
        assert len(client) == 1
        assert client[0] == "Zin 1. Zin 2."
        assert interp[0] == "Zin 1 en 2 NL."

    def test_realistic_ind_session(self):
        """Full 5-turn IND session: each client block → interpreter block."""
        segs = [
            make_seg(OFFICER, "Goede morgen.", 0, 3),
            make_seg(CLIENT,  "Naam: Ahmad.", 4, 9, language="fa"),
            make_seg(INTERP,  "Naam: Ahmad NL.", 10, 15),
            make_seg(OFFICER, "Waarom gevlucht?", 16, 19),
            make_seg(CLIENT,  "Taliban bedreigd.", 20, 30, language="fa"),
            make_seg(INTERP,  "Taliban bedreigd NL.", 31, 40),
            make_seg(OFFICER, "Wanneer?", 41, 43),
            make_seg(CLIENT,  "Augustus 2022.", 44, 50, language="fa"),
            make_seg(INTERP,  "Augustus 2022 NL.", 51, 58),
        ]
        interp, client = align(segs)
        assert len(client) == 3
        assert client == ["Naam: Ahmad.", "Taliban bedreigd.", "Augustus 2022."]
        assert interp == ["Naam: Ahmad NL.", "Taliban bedreigd NL.", "Augustus 2022 NL."]


# ── Edge cases ────────────────────────────────────────────────────────────────

class TestEdgeCases:
    def test_empty_segments(self):
        """Empty transcript → empty result."""
        interp, client = align([])
        assert interp == []
        assert client == []

    def test_no_client_turns(self):
        """Only officer + interpreter, no client → no pairs."""
        segs = [
            make_seg(OFFICER, "Vraag.", 0, 3),
            make_seg(INTERP,  "Antwoord.", 4, 8),
        ]
        interp, client = align(segs)
        assert interp == []
        assert client == []

    def test_no_interpreter_turns(self):
        """Client speaks but interpreter never responds → no pairs."""
        segs = [
            make_seg(CLIENT, "Ik spreek.", 0, 5),
            make_seg(OFFICER, "Dank u.", 6, 8),
        ]
        interp, client = align(segs)
        assert interp == []
        assert client == []

    def test_interpreter_before_client(self):
        """Interpreter speaks before any client turn — should produce no pair."""
        segs = [
            make_seg(INTERP,  "Vooraf.", 0, 3),
            make_seg(CLIENT,  "Client.", 4, 9),
            make_seg(INTERP,  "Client NL.", 10, 15),
        ]
        interp, client = align(segs)
        # Only the second interpreter turn (after the client) should form a pair
        assert len(client) == 1
        assert client[0] == "Client."
        assert interp[0] == "Client NL."

    def test_client_without_following_interpreter(self):
        """Last client block has no interpreter response → not included in pairs."""
        segs = [
            make_seg(CLIENT, "Block A.", 0, 5),
            make_seg(INTERP,  "Block A NL.", 6, 10),
            make_seg(CLIENT, "Block B — unanswered.", 11, 20),
        ]
        interp, client = align(segs)
        assert len(client) == 1
        assert client[0] == "Block A."

    def test_only_officer_turns(self):
        """No client or interpreter turns → empty."""
        segs = [make_seg(OFFICER, f"Vraag {i}.", i * 5, i * 5 + 3) for i in range(5)]
        interp, client = align(segs)
        assert interp == []
        assert client == []

    def test_single_segment_client_only(self):
        """Single client segment with no interpreter → no pair."""
        segs = [make_seg(CLIENT, "Ik kom uit Kabul.", 0, 5)]
        interp, client = align(segs)
        assert interp == []
        assert client == []

    def test_whitespace_preserved_in_concatenation(self):
        """Consecutive segments are joined with a space, not run together."""
        segs = [
            make_seg(CLIENT, "Eerste.",  0, 3),
            make_seg(CLIENT, "Tweede.", 4, 7),
            make_seg(INTERP, "Vertaling.", 8, 12),
        ]
        interp, client = align(segs)
        assert client[0] == "Eerste. Tweede."

    def test_unknown_speaker_ignored(self):
        """An UNKNOWN speaker label does not create pairs or break existing ones."""
        segs = [
            make_seg(CLIENT,    "Client.", 0, 5),
            make_seg("UNKNOWN", "?", 6, 7),
            make_seg(INTERP,    "Client NL.", 8, 13),
        ]
        interp, client = align(segs)
        assert len(client) == 1
        assert client[0] == "Client."
        assert interp[0] == "Client NL."

    def test_return_order_is_interp_then_client(self):
        """Return value is (interp_texts, client_texts) — order matters for callers."""
        segs = [
            make_seg(CLIENT, "Bron.", 0, 5),
            make_seg(INTERP,  "Doel.", 6, 10),
        ]
        interp, client = _align_blocks(segs, INTERP, CLIENT)
        assert interp == ["Doel."]
        assert client == ["Bron."]

    def test_very_long_interpreter_block(self):
        """Ten interpreter segments all belong to one client block."""
        segs = [make_seg(CLIENT, "Lang verhaal.", 0, 60)]
        for i in range(10):
            segs.append(make_seg(INTERP, f"Segment {i}.", 61 + i * 5, 65 + i * 5))
        interp, client = align(segs)
        assert len(client) == 1
        expected = " ".join(f"Segment {i}." for i in range(10))
        assert interp[0] == expected
