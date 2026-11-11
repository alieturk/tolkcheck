"""Unit tests for evaluation/review_sheet.py — sample and Excel round trip."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

EVAL_DIR = Path(__file__).resolve().parent.parent / "evaluation"
sys.path.insert(0, str(EVAL_DIR))

import review_sheet as rs  # noqa: E402
from sessions import load_session  # noqa: E402

from tests.test_session_lint import valid_session  # noqa: E402


def write_sessions(directory: Path, numbers) -> list[Path]:
    paths = []
    for n in numbers:
        p = directory / f"S{n}.json"
        p.write_text(json.dumps(valid_session(n), indent=1), encoding="utf-8")
        paths.append(p)
    return paths


class TestSample(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.paths = write_sessions(self.dir, range(20, 30))
        self.sessions = [load_session(p) for p in self.paths]

    def tearDown(self):
        self.tmp.cleanup()

    def test_fixed_seed_gives_same_sample(self):
        for s in self.sessions:
            self.assertEqual(rs.sample_controls(s, 7), rs.sample_controls(s, 7))

    def test_other_seed_changes_some_sample(self):
        a = [rs.sample_controls(s, 1) for s in self.sessions]
        b = [rs.sample_controls(s, 2) for s in self.sessions]
        self.assertNotEqual(a, b)

    def test_at_least_one_and_about_thirty_percent(self):
        total_controls = total_sampled = 0
        for s in self.sessions:
            controls = [p for p in s.pairs if p.is_control]
            picked = rs.sample_controls(s, rs.DEFAULT_SEED)
            self.assertGreaterEqual(len(picked), 1)
            self.assertEqual(len(picked), max(1, round(0.3 * len(controls))))
            self.assertTrue(set(picked) <= {p.pair_id for p in controls})
            total_controls += len(controls)
            total_sampled += len(picked)
        self.assertLess(abs(total_sampled / total_controls - 0.3), 0.1)

    def test_all_deviations_are_rows(self):
        for s in self.sessions:
            ids = {p.pair_id for p in rs.rows_for(s, rs.DEFAULT_SEED)}
            self.assertTrue({p.pair_id for p in s.pairs if not p.is_control} <= ids)

    def test_sample_does_not_depend_on_the_batch(self):
        s = self.sessions[5]
        self.assertEqual(rs.sample_controls(s, 3), rs.sample_controls(load_session(self.paths[5]), 3))


class TestRoundTrip(unittest.TestCase):
    def setUp(self):
        from openpyxl import load_workbook
        self.load_workbook = load_workbook
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.paths = write_sessions(self.dir, (25, 26))
        self.sheet = self.dir / "review.xlsx"
        self.summary = rs.make_sheet(self.paths, self.sheet, seed=11)

    def tearDown(self):
        self.tmp.cleanup()

    def fill(self, answers: dict[str, tuple[str, str]], default: str = "ja") -> None:
        wb = self.load_workbook(self.sheet)
        ws = wb[rs.REVIEW_SHEET]
        header = [c.value for c in ws[1]]
        pid_col = header.index("pair_id") + 1
        agree_col = header.index(rs.AGREE) + 1
        remark_col = header.index(rs.REMARK) + 1
        for r in range(2, ws.max_row + 1):
            pid = ws.cell(r, pid_col).value
            ans, remark = answers.get(pid, (default, ""))
            ws.cell(r, agree_col).value = ans
            ws.cell(r, remark_col).value = remark
        wb.save(self.sheet)

    def test_sheet_has_columns_rows_and_seed(self):
        wb = self.load_workbook(self.sheet)
        ws = wb[rs.REVIEW_SHEET]
        self.assertEqual(tuple(c.value for c in ws[1]), rs.COLUMNS)
        expected = sum(len(i["deviations"]) + len(i["controls_sampled"]) for i in self.summary.values())
        self.assertEqual(ws.max_row - 1, expected)
        meta = wb[rs.META_SHEET]
        self.assertEqual(meta["A1"].value, "seed")
        self.assertEqual(meta["B1"].value, 11)

    def test_woordverschillen_column(self):
        ws = self.load_workbook(self.sheet)[rs.REVIEW_SHEET]
        header = [c.value for c in ws[1]]
        col = header.index("woordverschillen")
        label_col = header.index("label")
        for row in ws.iter_rows(min_row=2, values_only=True):
            if str(row[label_col]).startswith("controle"):
                self.assertIn(row[col], (None, ""))
            else:
                self.assertEqual(row[col], "1")   # the fixture changes one word

    def test_all_ja_marks_sessions_reviewed(self):
        self.fill({})
        report = rs.apply_sheet(self.sheet, self.dir, "Ayşe")
        self.assertEqual(sorted(report.approved), ["S25", "S26"])
        for p in self.paths:
            data = json.loads(p.read_text(encoding="utf-8"))
            self.assertIs(data["reviewed"], True)
            self.assertEqual(data["reviewed_by"], "Ayşe")

    def test_nee_is_reported_and_session_left_alone(self):
        self.fill({"S25-P01": ("nee", "vertaling klopt niet")})
        before = self.paths[0].read_text(encoding="utf-8")
        report = rs.apply_sheet(self.sheet, self.dir, "Ayşe")
        self.assertEqual(report.approved, ["S26"])
        self.assertIn("S25", report.not_updated)
        self.assertEqual(report.rejected_pairs, [("S25", "S25-P01", "vertaling klopt niet")])
        self.assertEqual(self.paths[0].read_text(encoding="utf-8"), before)

    def test_empty_answer_blocks_the_session(self):
        self.fill({"S26-P01": ("", "")})
        report = rs.apply_sheet(self.sheet, self.dir, "Ayşe")
        self.assertEqual(report.approved, ["S25"])
        self.assertIn("zonder", report.not_updated["S26"])

    def test_changed_file_is_not_updated(self):
        self.fill({})
        data = json.loads(self.paths[1].read_text(encoding="utf-8"))
        data["topic"] = "gewijzigd"
        self.paths[1].write_text(json.dumps(data), encoding="utf-8")
        report = rs.apply_sheet(self.sheet, self.dir, "Ayşe")
        self.assertEqual(report.approved, ["S25"])
        self.assertIn("gewijzigd", report.not_updated["S26"])

    def test_dry_run_writes_nothing(self):
        self.fill({})
        before = [p.read_text(encoding="utf-8") for p in self.paths]
        report = rs.apply_sheet(self.sheet, self.dir, "Ayşe", write=False)
        self.assertEqual(sorted(report.approved), ["S25", "S26"])
        self.assertEqual([p.read_text(encoding="utf-8") for p in self.paths], before)



class TestRemarkColumn(TestRoundTrip):
    def test_column_is_named_opmerking_reviewer(self):
        ws = self.load_workbook(self.sheet)[rs.REVIEW_SHEET]
        self.assertIn("opmerking reviewer", [c.value for c in ws[1]])

    def test_old_header_is_still_read_back(self):
        self.fill({"S25-P01": ("nee", "klopt niet")})
        wb = self.load_workbook(self.sheet)
        ws = wb[rs.REVIEW_SHEET]
        for cell in ws[1]:
            if cell.value == rs.REMARK:
                cell.value = rs.OLD_REMARK
        wb.save(self.sheet)
        report = rs.apply_sheet(self.sheet, self.dir, "Ayşe", write=False)
        self.assertEqual(report.rejected_pairs, [("S25", "S25-P01", "klopt niet")])


if __name__ == "__main__":
    unittest.main()
