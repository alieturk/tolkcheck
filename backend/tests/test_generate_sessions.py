"""Unit tests for evaluation/generate_sessions.py — no API calls."""
from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

EVAL_DIR = Path(__file__).resolve().parent.parent / "evaluation"
sys.path.insert(0, str(EVAL_DIR))

import generate_sessions as gs  # noqa: E402

PV = "tolkcheck-sessies-v3"

from tests.test_session_lint import v3_session as valid_session  # noqa: E402


def fenced(data: dict, before: str = "| controletabel |\n|---|\n", tag: str = "json") -> str:
    return f"{before}\n```{tag}\n{json.dumps(data, ensure_ascii=False, indent=1)}\n```\n"


class FakeCaller:
    """Returns the given answers in turn and records every request."""

    def __init__(self, answers: list[str], model: str = "claude-test-1", stop_reason: str = "end_turn"):
        self.answers = list(answers)
        self.model = model
        self.stop_reason = stop_reason
        self.calls: list[list[dict]] = []

    def __call__(self, system: str, messages: list[dict]) -> gs.Reply:
        self.calls.append(copy.deepcopy(messages))
        text = self.answers.pop(0)
        return gs.Reply(text, [{"type": "text", "text": text}], self.model,
                        {"input_tokens": 100, "output_tokens": 50}, self.stop_reason)


class TestAssignment(unittest.TestCase):
    def test_split(self):
        for n in (20, 29, 50, 59):
            self.assertEqual(gs.split_for(n), "dev", n)
        for n in (30, 49, 60, 69, 70, 89):
            self.assertEqual(gs.split_for(n), "test", n)
        for n in (19, 90, 0):
            with self.assertRaises(ValueError):
                gs.split_for(n)

    def test_topic_cycles_from_20(self):
        self.assertEqual(gs.topic_for(20), "aanhouding en detentie")
        self.assertEqual(gs.topic_for(26), "documenten en identiteit")
        self.assertEqual(gs.topic_for(27), "aanhouding en detentie")
        self.assertEqual(gs.topic_for(25), "werk en politieke activiteiten")
        self.assertEqual(gs.topic_for(89), gs.TOPICS[(89 - 20) % 7])

    def test_voices_match_existing_sessions(self):
        # S20–S24 were made by hand with this rotation.
        existing = {
            20: ("vb_officer_a", "vb_applicant_b"),
            21: ("vb_officer_b", "vb_applicant_c"),
            22: ("vb_officer_c", "vb_applicant_a"),
            23: ("vb_officer_a", "vb_applicant_b"),
            24: ("vb_officer_b", "vb_applicant_c"),
        }
        for n, (officer, applicant) in existing.items():
            v = gs.voices_for(n)
            self.assertEqual((v["officer"], v["applicant"]), (officer, applicant), n)
            self.assertEqual(v["interpreter"], "vb_interp_a")

    def test_voices_depend_only_on_mod_3(self):
        for n in range(20, 87):
            self.assertEqual(gs.voices_for(n), gs.voices_for(n + 3))

    def test_user_message_carries_the_assignment(self):
        msg = gs.user_message(gs.assignment(25))
        spec = gs.extract_json(msg.replace('"voices"', '"pairs": [], "voices"'))
        self.assertEqual(spec["session_id"], "S25")
        self.assertEqual(spec["split"], "dev")
        self.assertEqual(spec["topic"], "werk en politieke activiteiten")


class TestExtractJson(unittest.TestCase):
    def test_takes_the_json_block_after_the_table(self):
        data = valid_session(25)
        self.assertEqual(gs.extract_json(fenced(data)), data)

    def test_untagged_block_works(self):
        data = valid_session(25)
        self.assertEqual(gs.extract_json(fenced(data, tag="")), data)

    def test_ignores_other_blocks(self):
        data = valid_session(25)
        text = "```python\nprint('x')\n```\n" + "```json\n{\"note\": 1}\n```\n" + fenced(data)
        self.assertEqual(gs.extract_json(text), data)

    def test_no_block(self):
        with self.assertRaisesRegex(gs.ExtractError, "geen codeblok"):
            gs.extract_json('{"pairs": []}')

    def test_invalid_json(self):
        with self.assertRaisesRegex(gs.ExtractError, "geen geldige JSON"):
            gs.extract_json("```json\n{\"pairs\": [,]}\n```")

    def test_two_sessions_is_an_error(self):
        data = valid_session(25)
        with self.assertRaisesRegex(gs.ExtractError, "2 codeblokken"):
            gs.extract_json(fenced(data) + fenced(data))


class TestRetryLoop(unittest.TestCase):
    def setUp(self):
        self.a = gs.assignment(25)

    def test_valid_first_time_and_overrides(self):
        data = valid_session(25)
        data.update(split="test", topic="iets anders", generator="claude", reviewed=True,
                    reviewed_by="iemand", prompt_version="v1",
                    voices={"officer": "x", "applicant": "y", "interpreter": "z"})
        fake = FakeCaller([fenced(data)], model="claude-sonnet-4-6")
        out = gs.generate_one(fake, "systeem", self.a, PV)
        self.assertTrue(out.ok)
        self.assertEqual(len(out.attempts), 1)
        d = out.data
        self.assertEqual(d["split"], "dev")
        self.assertEqual(d["topic"], "werk en politieke activiteiten")
        self.assertEqual(d["voices"], gs.voices_for(25))
        self.assertEqual(d["generator"], "claude-sonnet-4-6")
        self.assertEqual(d["prompt_version"], PV)
        self.assertIs(d["reviewed"], False)
        self.assertIsNone(d["reviewed_by"])

    def test_findings_are_fed_back_and_second_attempt_accepted(self):
        bad = valid_session(25)
        bad["pairs"].pop()
        fake = FakeCaller([fenced(bad), fenced(valid_session(25))])
        out = gs.generate_one(fake, "systeem", self.a, PV)
        self.assertTrue(out.ok)
        self.assertEqual(len(out.attempts), 2)
        self.assertEqual(out.usage["input_tokens"], 200)
        second = fake.calls[1]
        self.assertEqual([m["role"] for m in second], ["user", "assistant", "user"])
        self.assertIn("7 paren", second[2]["content"])
        self.assertEqual(second[1]["content"][0]["text"], fenced(bad))

    def test_rejected_after_max_retries(self):
        fake = FakeCaller(["geen json"] * 10)
        out = gs.generate_one(fake, "systeem", self.a, PV, max_retries=3)
        self.assertFalse(out.ok)
        self.assertEqual(len(fake.calls), 4)
        self.assertIn("geen codeblok", out.problems[0])

    def test_wrong_session_id_is_a_finding(self):
        fake = FakeCaller([fenced(valid_session(25)).replace('"S25"', '"S99"')] * 4)
        out = gs.generate_one(fake, "systeem", self.a, PV)
        self.assertFalse(out.ok)
        self.assertTrue(any("session_id" in p for p in out.problems))

    def test_truncated_answer_is_retried(self):
        fake = FakeCaller([fenced(valid_session(25))] * 4, stop_reason="max_tokens")
        out = gs.generate_one(fake, "systeem", self.a, PV, max_retries=1)
        self.assertFalse(out.ok)
        self.assertEqual(len(fake.calls), 2)
        self.assertIn("max_tokens", out.problems[0])

    def test_write_outcome_ok_and_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            bad = gs.generate_one(FakeCaller(["geen json"] * 4), "s", self.a, PV)
            gs.write_outcome(bad, out_dir)
            self.assertTrue((out_dir / "rejected" / "S25.errors.md").exists())
            self.assertFalse((out_dir / "S25.json").exists())

            good = gs.generate_one(FakeCaller([fenced(valid_session(25))]), "s", self.a, PV)
            gs.write_outcome(good, out_dir)
            self.assertTrue((out_dir / "S25.json").exists())
            self.assertFalse((out_dir / "rejected" / "S25.errors.md").exists())
            raw = (out_dir / "raw" / "S25.md").read_text(encoding="utf-8")
            self.assertIn("controletabel", raw)
            self.assertEqual(gs.log_record(good)["attempts"], 1)


class TestSubtypesAndWarnings(unittest.TestCase):
    def test_user_message_names_the_rotation_subtypes(self):
        a = gs.assignment(26)
        self.assertEqual(a.subtypes, {"toevoeging": "eigen_vraag_tolk",
                                      "betekenisverschuiving": "sterker_of_zwakker_gemaakt",
                                      "entiteitsfout": "tijdsduur",
                                      "register_en_nadruk": "voorzichtigheidswoord_weg"})
        msg = gs.user_message(a)
        for subtype in a.subtypes.values():
            self.assertIn(f'"{subtype}"', msg)

    def test_allowed_second_difference_is_not_sent_back(self):
        data = valid_session(25)
        pair = next(p for p in data["pairs"] if p["label"] == "omissie")
        pair["rendering"]["text"] = "Ja, ik kende hem."
        pair["reference_rendering"] = "Nee, ik kende hem niet."
        fake = FakeCaller([fenced(data)])
        out = gs.generate_one(fake, "s", gs.assignment(25), PV)
        self.assertTrue(out.ok)
        self.assertEqual(len(fake.calls), 1)

    def test_deviation_with_expected_flag_false_is_an_error(self):
        data = valid_session(25)
        pair = next(p for p in data["pairs"] if p["label"] == "omissie")
        pair["expected_flag"] = False
        problems = gs.validate(gs.apply_overrides(data, gs.assignment(25), "m", PV), gs.assignment(25))
        self.assertTrue(any("expected_flag false" in p for p in problems), problems)
        self.assertFalse(any("loader:" in p and "counted as a control" in p for p in problems))

    def test_wrong_subtype_is_sent_back(self):
        bad = valid_session(26)
        next(p for p in bad["pairs"] if p["label"] == "entiteitsfout")["subtype"] = "aantal"
        fake = FakeCaller([fenced(bad), fenced(valid_session(26))])
        out = gs.generate_one(fake, "s", gs.assignment(26), PV)
        self.assertTrue(out.ok)
        self.assertIn("verwacht 'tijdsduur'", fake.calls[1][2]["content"])


class TestPromptVersion(unittest.TestCase):
    def test_follows_the_file_name(self):
        self.assertEqual(gs.prompt_version_of(Path("x/tolkcheck-sessies-v3.md")), "tolkcheck-sessies-v3")
        self.assertEqual(gs.DEFAULT_PROMPT.name, "tolkcheck-sessies-v4.md")
        self.assertEqual(gs.DEFAULT_MODEL, "claude-haiku-5-5")

    def test_log_and_raw_carry_the_version(self):
        out = gs.generate_one(FakeCaller([fenced(valid_session(25))]), "s", gs.assignment(25), "promptX")
        self.assertEqual(out.data["prompt_version"], "promptX")
        self.assertEqual(gs.log_record(out)["prompt_version"], "promptX")
        self.assertIn("prompt: promptX", gs.raw_markdown(out))


class TestCost(unittest.TestCase):
    def test_known_and_unknown_model(self):
        usage = {"input_tokens": 1_000_000, "output_tokens": 1_000_000}
        self.assertAlmostEqual(gs.cost_usd("claude-sonnet-4-6", usage), 18.0)
        self.assertIsNone(gs.cost_usd("onbekend", usage))


if __name__ == "__main__":
    unittest.main()
