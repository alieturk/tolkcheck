"""Unit tests for evaluation/session_lint.py (standard library only)."""
from __future__ import annotations

import contextlib
import copy
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

EVAL_DIR = Path(__file__).resolve().parent.parent / "evaluation"
sys.path.insert(0, str(EVAL_DIR))

import session_lint  # noqa: E402
from session_lint import BY_LAST_DIGIT, EXCEPTION_BY_MOD3, PROMPT_VERSION, lint_session  # noqa: E402


def words(n: int) -> str:
    return " ".join(["woord"] * n)


def valid_session(number: int = 20) -> dict:
    """A session that satisfies every rule, for any number with four deviations
    or fewer; each test then breaks one thing."""
    deviations = list(BY_LAST_DIGIT[number % 10])
    labels = deviations + ["controle_letterlijk", "controle_parafrase"]
    labels += ["controle_letterlijk"] * (7 - len(labels))
    labels.insert(5, EXCEPTION_BY_MOD3[number % 3])  # P06, an answer: taalvariant must be tr->nl
    # P01 (question) and P02 (answer) are always deviations, so both directions have one.
    answer_lengths = {1: 10, 3: 25, 5: 45, 7: 12}
    pairs = []
    for i, label in enumerate(labels):
        is_question = i % 2 == 0
        source_lang, target_lang = ("nl", "tr") if is_question else ("tr", "nl")
        pair = {
            "pair_id": f"S{number}-P{i + 1:02d}",
            "order": i + 1,
            "round": i // 2 + 1,
            "direction": "nl->tr" if is_question else "tr->nl",
            "source": {"lang": source_lang, "text": words(answer_lengths.get(i, 8))},
            "rendering": {"lang": target_lang, "text": words(8)},
            "label": label,
            "subtype": None,
            "severity": "major" if label in session_lint.DEVIATIONS else "none",
            "expected_flag": label in session_lint.DEVIATIONS,
        }
        if label in session_lint.DEVIATIONS:
            pair["reference_rendering"] = words(7) + " juist"
        pairs.append(pair)
    return {"session_id": f"S{number}", "split": "dev", "prompt_version": PROMPT_VERSION, "pairs": pairs}


def v3_session(number: int = 20) -> dict:
    """valid_session as prompt v3 writes it: subtypes from the rotation."""
    data = valid_session(number)
    data["prompt_version"] = "tolkcheck-sessies-v3"
    wanted = session_lint.expected_subtypes(number)
    for pair in data["pairs"]:
        if pair["label"] in wanted:
            pair["subtype"] = wanted[pair["label"]]
    return data


class Base(unittest.TestCase):
    def assertFinding(self, data: dict, fragment: str) -> None:
        problems = lint_session(data)
        self.assertTrue(any(fragment in p for p in problems), f"{fragment!r} not in {problems}")


class TestValidSessions(Base):
    def test_every_last_digit_and_remainder_can_be_clean(self):
        for number in range(20, 50):
            with self.subTest(number=number):
                self.assertEqual(lint_session(valid_session(number)), [])


class TestStructure(Base):
    def test_wrong_number_of_pairs(self):
        data = valid_session()
        data["pairs"].pop()
        self.assertFinding(data, "7 paren")

    def test_directions_must_alternate(self):
        data = valid_session()
        data["pairs"][1]["direction"] = "nl->tr"
        self.assertFinding(data, "S20-P02: richting")

    def test_first_pair_must_be_a_question(self):
        data = valid_session()
        for pair in data["pairs"]:
            pair["direction"] = "tr->nl" if pair["direction"] == "nl->tr" else "nl->tr"
        self.assertFinding(data, "S20-P01: richting")

    def test_rounds_must_not_decrease(self):
        data = valid_session()
        data["pairs"][2]["round"], data["pairs"][4]["round"] = 3, 2
        self.assertFinding(data, "round loopt niet op")

    def test_all_four_rounds_must_occur(self):
        data = valid_session()
        for pair in data["pairs"][6:]:
            pair["round"] = 3
        self.assertFinding(data, "verwacht 1 t/m 4")

    def test_missing_round(self):
        data = valid_session()
        del data["pairs"][0]["round"]
        self.assertFinding(data, "round ontbreekt")

    def test_pairs_missing(self):
        self.assertEqual(lint_session({"session_id": "S20"}), ["pairs ontbreekt of is geen lijst van objecten"])


class TestCategoriesAndExceptions(Base):
    def test_missing_category(self):
        data = valid_session(20)
        data["pairs"][3]["label"] = "omissie"  # entiteitsfout replaced by a second omissie
        problems = lint_session(data)
        finding = next(p for p in problems if "laatste cijfer 0" in p)
        self.assertIn("entiteitsfout", finding)
        self.assertIn("omissie", finding)

    def test_digit_table_matches_the_prompt(self):
        self.assertEqual(BY_LAST_DIGIT[4],
                         ("register_en_nadruk", "omissie", "toevoeging", "betekenisverschuiving"))
        self.assertEqual(BY_LAST_DIGIT[9],
                         ("betekenisverschuiving", "entiteitsfout", "register_en_nadruk"))

    def test_wrong_exception_for_the_number(self):
        data = valid_session(20)  # 20 % 3 == 2: controle_taalvariant
        data["pairs"][5]["label"] = "controle_verzoek_herhaling"
        self.assertFinding(data, "verwacht precies één controle_taalvariant")

    def test_two_exceptions(self):
        data = valid_session(21)  # three deviations, so P07/P08 are spare controls
        data["pairs"][7]["label"] = EXCEPTION_BY_MOD3[0]
        data["pairs"][7]["expected_flag"] = False
        self.assertFinding(data, "verwacht precies één")

    def test_exception_is_required(self):
        data = valid_session(20)
        data["pairs"][5]["label"] = "controle_letterlijk"
        self.assertFinding(data, "uitzondering: gevonden –")

    def test_literal_and_paraphrase_required(self):
        data = valid_session(20)
        for index in (4, 7):  # the fixture has two literal controls
            data["pairs"][index]["label"] = "controle_parafrase"
        self.assertFinding(data, "geen controle_letterlijk")
        data = valid_session(20)
        data["pairs"][6]["label"] = "controle_letterlijk"
        self.assertFinding(data, "geen controle_parafrase")

    def test_unknown_label(self):
        data = valid_session()
        data["pairs"][7]["label"] = "controle_onzin"
        self.assertFinding(data, "onbekend label")

    def test_session_id_without_number(self):
        data = valid_session()
        data["session_id"] = "X"
        self.assertFinding(data, "S<nummer>")


class TestDirectionSpread(Base):
    def _swap(self, data: dict, deviation_index: int, control_index: int) -> None:
        a, b = data["pairs"][deviation_index], data["pairs"][control_index]
        for key in ("label", "severity", "expected_flag", "reference_rendering"):
            a_value, b_value = a.pop(key, None), b.pop(key, None)
            if b_value is not None:
                a[key] = b_value
            if a_value is not None:
                b[key] = a_value

    def test_no_deviation_in_a_question(self):
        data = valid_session(21)  # deviations at P01, P02, P03: move both questions to answers
        self._swap(data, 0, 3)
        self._swap(data, 2, 5)
        self.assertFinding(data, "geen afwijking in een vraag")

    def test_no_deviation_in_an_answer(self):
        data = valid_session(21)
        self._swap(data, 1, 4)
        self.assertFinding(data, "geen afwijking in een antwoord")


class TestLengths(Base):
    def test_source_over_60_words(self):
        data = valid_session()
        data["pairs"][0]["source"]["text"] = words(61)
        self.assertFinding(data, "S20-P01: bronuiting van 61 woorden")

    def test_source_of_exactly_60_words_is_allowed(self):
        data = valid_session()
        data["pairs"][0]["source"]["text"] = words(60)
        self.assertEqual(lint_session(data), [])

    def test_questions_do_not_count_for_the_bands(self):
        data = valid_session()
        data["pairs"][5]["source"]["text"] = words(20)   # no long answer left
        data["pairs"][0]["source"]["text"] = words(50)   # a long question does not help
        self.assertFinding(data, "lengteklasse lang")

    def test_each_band_is_required(self):
        # The fixture's answers (P02, P04, P06, P08) are 10, 25, 45 and 12 words.
        for band, new_lengths in (("kort", {1: 25, 7: 25}), ("middellang", {3: 10}), ("lang", {5: 10})):
            data = valid_session()
            for index, n in new_lengths.items():
                data["pairs"][index]["source"]["text"] = words(n)
            with self.subTest(band=band):
                self.assertFinding(data, f"lengteklasse {band}")

    def test_band_edges_are_inclusive(self):
        data = valid_session()
        data["pairs"][1]["source"]["text"] = words(15)  # short and medium
        data["pairs"][3]["source"]["text"] = words(35)  # medium and long
        data["pairs"][5]["source"]["text"] = words(60)
        data["pairs"][7]["source"]["text"] = words(60)
        self.assertEqual(lint_session(data), [])


class TestPairFields(Base):
    def test_deviation_needs_reference(self):
        data = valid_session()
        del data["pairs"][0]["reference_rendering"]
        self.assertFinding(data, "S20-P01: afwijking zonder reference_rendering")

    def test_null_reference_counts_as_missing(self):
        data = valid_session()
        data["pairs"][0]["reference_rendering"] = None
        self.assertFinding(data, "afwijking zonder reference_rendering")

    def test_control_must_not_have_reference(self):
        data = valid_session()
        data["pairs"][7]["reference_rendering"] = words(8)
        self.assertFinding(data, "S20-P08: controle met reference_rendering")

    def test_own_question_severity(self):
        data = valid_session()
        data["pairs"][1].update(subtype="eigen_vraag_tolk", severity="minor")
        self.assertFinding(data, "eigen_vraag_tolk met severity 'minor'")

    def test_own_question_critical_is_fine(self):
        data = valid_session()
        data["pairs"][1].update(subtype="eigen_vraag_tolk", severity="critical")
        self.assertEqual(lint_session(data), [])


class TestDirectory(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)

    def _write(self, name: str, data) -> None:
        text = data if isinstance(data, str) else json.dumps(data)
        (self.dir / name).write_text(text, encoding="utf-8")

    def test_skips_old_prompt_and_test_sessions(self):
        old = valid_session(12)
        del old["prompt_version"]
        held_out = copy.deepcopy(valid_session(30))
        held_out["split"] = "test"
        held_out["pairs"] = []  # would produce findings if it were looked at
        self._write("S12.json", old)
        self._write("S30.json", held_out)
        self._write("S20.json", valid_session(20))
        findings, skipped = session_lint.lint_directory(self.dir)
        self.assertEqual(findings, {"S20": []})
        self.assertEqual(set(skipped), {"S12", "S30"})

    def test_invalid_json_is_a_finding_not_a_crash(self):
        self._write("S20.json", "{")
        findings, _ = session_lint.lint_directory(self.dir)
        self.assertIn("geen geldige JSON", findings["S20"][0])

    def _run_main(self) -> int:
        with contextlib.redirect_stdout(io.StringIO()):
            return session_lint.main(["--sessions-dir", str(self.dir)])

    def test_exit_code_zero_when_clean(self):
        self._write("S20.json", valid_session(20))
        self.assertEqual(self._run_main(), 0)

    def test_exit_code_one_with_findings(self):
        data = valid_session(20)
        data["pairs"].pop()
        self._write("S20.json", data)
        self.assertEqual(self._run_main(), 1)



class TestPromptVersions(unittest.TestCase):
    def test_v3_is_checked_and_v1_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            for n, version in ((20, "tolkcheck-sessies-v3"), (21, "tolkcheck-sessies-v1")):
                data = v3_session(n)
                data["prompt_version"] = version
                Path(tmp, f"S{n}.json").write_text(json.dumps(data), encoding="utf-8")
            findings, skipped = session_lint.lint_directory(Path(tmp))
        self.assertEqual(findings, {"S20": []})
        self.assertEqual(set(skipped), {"S21"})


class TestReferenceDiff(Base):
    def _deviation(self, data: dict) -> dict:
        return next(p for p in data["pairs"] if p["label"] in session_lint.DEVIATIONS)

    def _set(self, rendering: str, reference: str) -> tuple[dict, dict]:
        data = valid_session()
        pair = self._deviation(data)
        pair["rendering"]["text"] = rendering
        pair["reference_rendering"] = reference
        return data, pair

    def test_one_run_is_clean_without_note(self):
        data, _ = self._set("Polisler size ne söylediler?",
                            "Polisler sizi götürmeden önce size ne söylediler?")
        self.assertEqual(lint_session(data), [])
        self.assertEqual(session_lint.session_notes(data), [])

    def test_two_runs_close_together_are_allowed_and_noted(self):
        data, pair = self._set("Ja, ik kende hem.", "Nee, ik kende hem niet.")
        self.assertEqual(lint_session(data), [])
        notes = session_lint.session_notes(data)
        self.assertEqual(len(notes), 1)
        self.assertIn(f"{pair['pair_id']}: 2 woordverschillen, 2 woord(en) ertussen", notes[0])

    def test_gap_of_six_is_allowed_seven_is_not(self):
        six = "a b c d e f"
        data, _ = self._set(f"X {six} Y", f"P {six} Q")
        self.assertEqual(lint_session(data), [])
        data, pair = self._set(f"X {six} g Y", f"P {six} g Q")
        self.assertFinding(data, f"{pair['pair_id']}: rendering en reference_rendering verschillen op "
                                 "2 plaatsen die 7 woorden uit elkaar liggen")

    def test_three_runs_is_a_finding(self):
        data, pair = self._set("a X b Y c Z d", "a P b Q c R d")
        self.assertFinding(data, f"{pair['pair_id']}: rendering en reference_rendering verschillen op "
                                 "3 plaatsen, hooguit 2")

    def test_adjacent_changes_count_as_one_run(self):
        self.assertEqual(session_lint.diff_runs("a b c d", "a x y z d"), [("b c", "x y z")])
        self.assertEqual(len(session_lint.diff_runs("a b c", "a c")), 1)   # deletion only
        self.assertEqual(len(session_lint.diff_runs("a c", "a b c")), 1)   # insertion only

    def test_gaps_and_description(self):
        self.assertEqual(session_lint.word_diff("a X b c Y", "a P b c Q")[1], [2])
        self.assertEqual(session_lint.describe_diff("a X b c Y", "a P b c Q"), "2 (2 ertussen)")
        self.assertEqual(session_lint.describe_diff("a X b", "a P b"), "1")

    def test_identical_reference_is_a_note_not_a_finding(self):
        data, pair = self._set("a b c", "a b c")
        self.assertEqual(lint_session(data), [])
        self.assertIn("gelijk aan de rendering", session_lint.session_notes(data)[0])

    def test_controls_are_ignored(self):
        data = valid_session()
        control = next(p for p in data["pairs"] if p["label"] == "controle_letterlijk")
        control["rendering"]["text"] = "a b c d e"
        self.assertEqual(lint_session(data), [])


class TestSubtypeRotation(Base):
    def _v3(self, number: int) -> dict:
        return v3_session(number)

    def test_every_category_of_the_session_gets_a_valid_subtype(self):
        for number in range(20, 90):
            wanted = session_lint.expected_subtypes(number)
            self.assertEqual(set(wanted), set(BY_LAST_DIGIT[number % 10]))
            for category, subtype in wanted.items():
                self.assertIn(subtype, session_lint.SUBTYPES[category])

    def test_each_subtype_equally_often_give_or_take_one(self):
        counts = {c: {s: 0 for s in subs} for c, subs in session_lint.SUBTYPES.items()}
        for number in range(20, 90):
            for category, subtype in session_lint.expected_subtypes(number).items():
                counts[category][subtype] += 1
        for category, per in counts.items():
            self.assertLessEqual(max(per.values()) - min(per.values()), 1, category)

    def test_rotation_follows_occurrences_of_the_category(self):
        # omissie occurs in S20, S21, S22, S24: kernfeit, detail, bijzin, voorwaarde
        got = [session_lint.expected_subtypes(n)["omissie"] for n in (20, 21, 22, 24, 25)]
        self.assertEqual(got, ["kernfeit", "detail", "bijzin", "voorwaarde", "kernfeit"])

    def test_v3_session_with_the_rotation_is_clean(self):
        for number in range(20, 90):
            with self.subTest(number=number):
                self.assertEqual(lint_session(self._v3(number)), [])

    def test_wrong_subtype_is_a_finding_for_v3(self):
        data = self._v3(26)
        pair = next(p for p in data["pairs"] if p["label"] == "entiteitsfout")
        pair["subtype"] = "aantal"
        self.assertFinding(data, f"{pair['pair_id']}: subtype 'aantal' bij entiteitsfout, verwacht 'tijdsduur'")

    def test_v2_sessions_keep_their_own_subtypes(self):
        data = valid_session(26)
        for pair in data["pairs"]:
            if pair["label"] == "entiteitsfout":
                pair["subtype"] = "aantal"
        self.assertEqual(lint_session(data), [])


class TestDialectDirection(Base):
    def test_taalvariant_in_a_question_is_a_finding(self):
        data = valid_session(20)
        exc = next(p for p in data["pairs"] if p["label"] == "controle_taalvariant")
        self.assertEqual(exc["direction"], "tr->nl")
        self.assertEqual(lint_session(data), [])
        # swap it with the literal control on P05, a question
        data["pairs"][4]["label"], exc["label"] = "controle_taalvariant", "controle_letterlijk"
        self.assertFinding(data, f"{data['pairs'][4]['pair_id']}: controle_taalvariant in een nl->tr-paar")

    def test_other_exceptions_may_be_in_a_question(self):
        data = valid_session(22)  # 22 % 3 == 1: verzoek_herhaling
        exc = next(p for p in data["pairs"] if p["label"] == "controle_verzoek_herhaling")
        q = next(p for p in data["pairs"] if p["direction"] == "nl->tr" and p["label"] == "controle_letterlijk")
        exc["label"], q["label"] = q["label"], exc["label"]
        self.assertEqual(lint_session(data), [])



def v4_session(number: int = 20) -> dict:
    """v3_session as prompt v4 writes it: zelfcorrectie instead of taalvariant."""
    data = v3_session(number)
    data["prompt_version"] = session_lint.V4
    for pair in data["pairs"]:
        if pair["label"] == "controle_taalvariant":
            pair["label"] = session_lint.SELF_CORRECTION
            pair["normbron"] = "Wbtv regel 18"
            pair["rendering"]["text"] = "Ik woonde in Izmir. De tolk corrigeert zich: in Ankara."
    return data


class TestPromptV4(Base):
    def test_v4_sessions_are_checked_and_clean(self):
        for number in range(20, 90):
            with self.subTest(number=number):
                data = v4_session(number)
                self.assertEqual(lint_session(data), [])
                self.assertEqual(session_lint.session_notes(data), [])

    def test_v4_needs_zelfcorrectie_for_mod_3_is_2(self):
        data = v3_session(20)              # still has controle_taalvariant
        data["prompt_version"] = session_lint.V4
        self.assertFinding(data, "verwacht precies één controle_zelfcorrectie")

    def test_v3_still_needs_taalvariant(self):
        data = v4_session(20)
        data["prompt_version"] = session_lint.V3
        self.assertFinding(data, "verwacht precies één controle_taalvariant")

    def test_other_remainders_unchanged_in_v4(self):
        self.assertEqual(session_lint.exceptions_for(session_lint.V4)[0], "controle_gemelde_omschrijving")
        self.assertEqual(session_lint.exceptions_for(session_lint.V4)[1], "controle_verzoek_herhaling")

    def test_zelfcorrectie_needs_normbron_18(self):
        data = v4_session(20)
        pair = next(p for p in data["pairs"] if p["label"] == session_lint.SELF_CORRECTION)
        pair["normbron"] = "Wbtv regel 17"
        self.assertFinding(data, f"{pair['pair_id']}: controle_zelfcorrectie met normbron 'Wbtv regel 17'")

    def test_missing_announcement_is_a_warning_not_a_finding(self):
        data = v4_session(20)
        pair = next(p for p in data["pairs"] if p["label"] == session_lint.SELF_CORRECTION)
        pair["rendering"]["text"] = "Ik woonde in Ankara."
        self.assertEqual(lint_session(data), [])
        notes = session_lint.session_notes(data)
        self.assertEqual(len(notes), 1)
        self.assertIn(f"{pair['pair_id']}: waarschuwing: controle_zelfcorrectie zonder melding", notes[0])

    def test_turkish_announcement_counts(self):
        data = v4_session(20)
        pair = next(p for p in data["pairs"] if p["label"] == session_lint.SELF_CORRECTION)
        pair["rendering"]["text"] = "İzmir'de, tercüman düzeltiyor: Ankara'da yaşıyordum."
        self.assertEqual(session_lint.session_notes(data), [])

    def test_v4_directory_is_not_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "S20.json").write_text(json.dumps(v4_session(20)), encoding="utf-8")
            findings, skipped = session_lint.lint_directory(Path(tmp))
        self.assertEqual((findings, skipped), ({"S20": []}, {}))


if __name__ == "__main__":
    unittest.main()
