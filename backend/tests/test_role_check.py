"""Tests for services/role_check.py.

Roles are assigned by hand over anonymous diarization labels, and nothing
verifies either the choice or the clustering behind it. Detected languages are
independent evidence: in an IND hearing the officer speaks Dutch, the client
speaks the source language, and only the interpreter does both.
"""
from __future__ import annotations

from app.services.role_check import check_roles
from tests.conftest import make_seg

INTERP, CLIENT, OFFICER = "SPEAKER_00", "SPEAKER_02", "SPEAKER_01"


def run(segs, client_lang="tr"):
    return check_roles(segs, INTERP, CLIENT, client_lang)


def codes(result):
    return {w["code"] for w in result["warnings"]}


def healthy():
    """A clean hearing: officer Dutch, client Turkish, interpreter alternating."""
    segs = []
    for i in range(6):
        segs.append(make_seg(OFFICER, f"Vraag {i}", i * 10, i * 10 + 2, language="nl"))
        segs.append(make_seg(INTERP, f"Soru {i}", i * 10 + 2, i * 10 + 4, language="tr"))
        segs.append(make_seg(CLIENT, f"Cevap {i}", i * 10 + 4, i * 10 + 6, language="tr"))
        segs.append(make_seg(INTERP, f"Antwoord {i}", i * 10 + 6, i * 10 + 8, language="nl"))
    return segs


class TestCleanHearing:
    def test_no_warnings(self):
        result = run(healthy())
        assert result["ok"] is True
        assert result["warnings"] == []

    def test_distribution_is_reported_either_way(self):
        result = run(healthy())
        assert result["distribution"][INTERP]["role"] == "interpreter"
        assert result["distribution"][INTERP]["langs"] == {"tr": 6, "nl": 6}
        assert result["distribution"][OFFICER]["langs"] == {"nl": 6}

    def test_a_single_stray_segment_does_not_trip_it(self):
        """A Turkish place name inside a Dutch question is normal."""
        segs = healthy() + [make_seg(OFFICER, "Diyarbakir", 200, 201, language="tr")]
        assert run(segs)["ok"] is True

    def test_dutch_speaking_client_skips_the_language_checks(self):
        """With client_lang == nl the languages carry no role information."""
        segs = [make_seg(OFFICER, "Vraag", 0, 2, language="nl"),
                make_seg(CLIENT, "Antwoord", 2, 4, language="nl"),
                make_seg(INTERP, "Herhaling", 4, 6, language="nl")]
        assert run(segs, client_lang="nl")["ok"] is True


class TestDiarizationLeak:
    def test_officer_carrying_client_speech(self):
        """Session f1fae5ce: 'Yerimi dokuz yasindayim' landed in the officer's cluster."""
        segs = healthy()
        for i in range(3):
            segs.append(make_seg(OFFICER, f"Turkse zin {i}", 300 + i, 301 + i, language="tr"))
        result = run(segs)
        assert "officer_speaks_client_lang" in codes(result)
        assert result["ok"] is False

    def test_client_carrying_officer_speech(self):
        segs = healthy()
        for i in range(3):
            segs.append(make_seg(CLIENT, f"Nederlandse vraag {i}", 300 + i, 301 + i, language="nl"))
        assert "client_speaks_dutch" in codes(run(segs))

    def test_warning_names_the_speaker_and_the_share(self):
        segs = healthy()
        for i in range(3):
            segs.append(make_seg(CLIENT, f"NL {i}", 300 + i, 301 + i, language="nl"))
        w = next(w for w in run(segs)["warnings"] if w["code"] == "client_speaks_dutch")
        assert w["speaker"] == CLIENT
        assert "33%" in w["message"] or "%" in w["message"]
        assert w["severity"] == "medium"


class TestWrongRolePick:
    def test_monolingual_interpreter_is_flagged(self):
        """Picking a non-interpreter as the interpreter: they never switch language."""
        segs = [make_seg(INTERP, f"Alleen Nederlands {i}", i, i + 1, language="nl")
                for i in range(10)]
        segs += [make_seg(CLIENT, f"Turkce {i}", 100 + i, 101 + i, language="tr")
                 for i in range(5)]
        segs += [make_seg(OFFICER, f"NL {i}", 200 + i, 201 + i, language="nl") for i in range(5)]
        result = run(segs)
        assert "interpreter_not_bilingual" in codes(result)
        assert any(w["severity"] == "high" for w in result["warnings"])

    def test_suggests_the_more_bilingual_speaker(self):
        """When the pick looks wrong, name the speaker the evidence points at."""
        segs = [make_seg(INTERP, f"NL {i}", i, i + 1, language="nl") for i in range(10)]
        # OFFICER is the one actually alternating — the real interpreter.
        segs += [make_seg(OFFICER, f"tr {i}", 100 + i, 101 + i, language="tr") for i in range(5)]
        segs += [make_seg(OFFICER, f"nl {i}", 150 + i, 151 + i, language="nl") for i in range(5)]
        segs += [make_seg(CLIENT, f"tr {i}", 200 + i, 201 + i, language="tr") for i in range(5)]
        result = run(segs)
        assert "interpreter_candidate" in codes(result)
        assert next(w for w in result["warnings"]
                    if w["code"] == "interpreter_candidate")["speaker"] == OFFICER

    def test_no_candidate_suggested_when_the_pick_looks_fine(self):
        segs = healthy()
        segs += [make_seg(OFFICER, f"tr {i}", 300 + i, 301 + i, language="tr") for i in range(3)]
        assert "interpreter_candidate" not in codes(run(segs))


class TestClientLanguageMismatch:
    def test_client_mostly_not_speaking_expected_language(self):
        """NEW: Client should speak mostly in the expected language.

        This catches Phase B retranscription failures where forced language
        did not take hold, or language detection was wrong.
        """
        # Client has mostly Dutch segments (wrong for Turkish client)
        segs = [make_seg(OFFICER, "Vraag", 0, 2, language="nl")]
        segs += [make_seg(CLIENT, f"Nederlands {i}", 10 + i, 11 + i, language="nl") for i in range(10)]
        segs += [make_seg(INTERP, "Soru", 30, 32, language="tr")]
        segs += [make_seg(INTERP, "Vraag", 32, 34, language="nl")]

        result = run(segs)  # client_lang="tr"
        assert "client_language_mismatch" in codes(result)
        assert result["ok"] is False
        w = next(w for w in result["warnings"] if w["code"] == "client_language_mismatch")
        assert w["severity"] == "high"
        assert w["speaker"] == CLIENT

    def test_client_speaking_expected_language_is_ok(self):
        """Client speaking ≥50% in expected language is acceptable."""
        segs = healthy()
        # Add some Dutch to the client (diarization leak or code-switching)
        segs += [make_seg(CLIENT, f"Nederlands {i}", 300 + i, 301 + i, language="nl") for i in range(3)]

        result = run(segs)
        # Should not trigger client_language_mismatch (client still mostly Turkish)
        assert "client_language_mismatch" not in codes(result)


class TestEdgeCases:
    def test_empty_transcript(self):
        result = run([])
        assert result["distribution"] == {}
        assert "interpreter_not_bilingual" in codes(result)

    def test_result_is_json_serialisable(self):
        import json
        json.dumps(run(healthy()))
