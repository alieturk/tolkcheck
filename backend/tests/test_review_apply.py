"""review_sheet.py apply with corrections and left-out pairs, and how the measurement
scripts treat left-out pairs afterwards."""
from __future__ import annotations

import asyncio
import json
import sys
import tempfile
import unittest
from pathlib import Path

EVAL_DIR = Path(__file__).resolve().parent.parent / "evaluation"
sys.path.insert(0, str(EVAL_DIR))

import detection_check as dc  # noqa: E402
import review_sheet as rs  # noqa: E402
import test_sealed as ts  # noqa: E402
from sessions import load_session  # noqa: E402

from tests.test_session_lint import v4_session  # noqa: E402

FIX = {"label": rs.FIX_LABEL, "subtype": rs.FIX_SUBTYPE, "severity": rs.FIX_SEVERITY,
       "omit": rs.OMIT, "agree": rs.AGREE, "remark": rs.REMARK}


class Base(unittest.TestCase):
    numbers = (25, 26)

    def setUp(self):
        from openpyxl import load_workbook
        self.load_workbook = load_workbook
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.paths = []
        for n in self.numbers:
            p = self.dir / f"S{n}.json"
            p.write_text(json.dumps(v4_session(n), indent=1), encoding="utf-8")
            self.paths.append(p)
        self.sheet = self.dir / "review.xlsx"
        self.summary = rs.make_sheet(self.paths, self.sheet, seed=11)
        self.before = {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in self.paths}

    def tearDown(self):
        self.tmp.cleanup()

    def fill(self, rows: dict[str, dict], default: str = "ja") -> None:
        """rows: pair_id → {agree/label/subtype/severity/omit/remark: value}; others get ``default``."""
        wb = self.load_workbook(self.sheet)
        ws = wb[rs.REVIEW_SHEET]
        header = [c.value for c in ws[1]]
        col = {k: header.index(v) + 1 for k, v in FIX.items()}
        pid_col = header.index("pair_id") + 1
        for r in range(2, ws.max_row + 1):
            values = rows.get(ws.cell(r, pid_col).value, {"agree": default})
            for key, value in values.items():
                ws.cell(r, col[key]).value = value
        wb.save(self.sheet)

    def data(self, sid: str) -> dict:
        return json.loads((self.dir / f"{sid}.json").read_text(encoding="utf-8"))

    def pair(self, pid: str) -> dict:
        return next(p for p in self.data(pid.split("-")[0])["pairs"] if p["pair_id"] == pid)

    def deviation(self, sid: str) -> dict:
        return next(p for p in self.before[sid]["pairs"] if p["expected_flag"])

    def sampled_control(self, sid: str) -> str:
        return self.summary[sid]["controls_sampled"][0]


class TestColumns(Base):
    def test_new_columns_exist_and_old_ones_stay(self):
        ws = self.load_workbook(self.sheet)[rs.REVIEW_SHEET]
        header = [c.value for c in ws[1]]
        for name in ("sessie", "pair_id", "bron", "vertolking", "label", "subtype", "severity",
                     rs.AGREE, rs.REMARK, "woordverschillen", "gecorrigeerd label",
                     "gecorrigeerd subtype", "gecorrigeerde severity", "weglaten (ja/leeg)"):
            self.assertIn(name, header)


class TestCorrections(Base):
    def test_all_ja_marks_reviewed_and_changes_no_label(self):
        self.fill({})
        report = rs.apply_sheet(self.sheet, self.dir, "Huseyin Altunbas")
        self.assertEqual(sorted(report.approved), ["S25", "S26"])
        self.assertEqual((report.corrected, report.excluded), ([], []))
        for sid in ("S25", "S26"):
            d = self.data(sid)
            self.assertIs(d["reviewed"], True)
            self.assertEqual(d["reviewed_by"], "Huseyin Altunbas")
            self.assertEqual([p["label"] for p in d["pairs"]], [p["label"] for p in self.before[sid]["pairs"]])

    def test_deviation_becomes_control(self):
        dev = self.deviation("S25")
        self.fill({dev["pair_id"]: {"agree": "nee", "label": "controle_parafrase", "remark": "is een parafrase"}})
        report = rs.apply_sheet(self.sheet, self.dir, "R")
        p = self.pair(dev["pair_id"])
        self.assertEqual((p["label"], p["subtype"], p["severity"], p["expected_flag"]),
                         ("controle_parafrase", None, "none", False))
        self.assertEqual((p["label_origineel"], p["subtype_origineel"], p["severity_origineel"]),
                         (dev["label"], dev["subtype"], dev["severity"]))
        self.assertNotIn("reference_rendering", p)
        self.assertEqual(p["reference_rendering_origineel"], dev["reference_rendering"])
        self.assertEqual(p["opmerking_reviewer"], "is een parafrase")
        self.assertEqual(len(report.corrected), 1)
        self.assertTrue(load_session(self.dir / "S25.json").pairs[int(dev["pair_id"][-2:]) - 1].is_control)

    def test_subtype_and_severity_corrections(self):
        dev = self.deviation("S25")
        other = next(s for s in rs.SUBTYPES[dev["label"]] if s != dev["subtype"])
        self.fill({dev["pair_id"]: {"agree": "nee", "subtype": other, "severity": "critical"}})
        rs.apply_sheet(self.sheet, self.dir, "R")
        p = self.pair(dev["pair_id"])
        self.assertEqual((p["label"], p["subtype"], p["severity"], p["expected_flag"]),
                         (dev["label"], other, "critical", True))
        self.assertEqual(p["label_origineel"], dev["label"])

    def test_control_becomes_deviation_needs_subtype_and_severity(self):
        pid = self.sampled_control("S25")
        self.fill({pid: {"agree": "nee", "label": "omissie"}})
        report = rs.apply_sheet(self.sheet, self.dir, "R")
        self.assertIn("S25", report.not_updated)
        self.assertEqual(self.data("S25"), self.before["S25"])
        self.fill({pid: {"agree": "nee", "label": "omissie", "subtype": "detail", "severity": "minor"}})
        rs.apply_sheet(self.sheet, self.dir, "R")
        p = self.pair(pid)
        self.assertEqual((p["label"], p["subtype"], p["severity"], p["expected_flag"]),
                         ("omissie", "detail", "minor", True))

    def test_controls_outside_the_sample_stay(self):
        self.fill({})
        rs.apply_sheet(self.sheet, self.dir, "R")
        sampled = set(self.summary["S25"]["controls_sampled"])
        for before, after in zip(self.before["S25"]["pairs"], self.data("S25")["pairs"]):
            if not before["expected_flag"] and before["pair_id"] not in sampled:
                self.assertEqual(before, after)


class TestNoValidJudgement(Base):
    def check_untouched(self, rows: dict, fragment: str):
        self.fill(rows)
        report = rs.apply_sheet(self.sheet, self.dir, "R")
        self.assertIn("S25", report.not_updated)
        self.assertTrue(any(fragment in p for p in report.problems["S25"]), report.problems)
        self.assertEqual(self.data("S25"), self.before["S25"])     # all or nothing
        self.assertEqual(report.approved, ["S26"])

    def test_unknown_label(self):
        self.check_untouched({self.deviation("S25")["pair_id"]: {"agree": "nee", "label": "fout"}},
                             "onbekend label")

    def test_ja_with_correction(self):
        self.check_untouched({self.deviation("S25")["pair_id"]: {"agree": "ja", "severity": "minor"}},
                             "akkoord = ja, maar er staat ook een correctie")

    def test_nee_without_correction(self):
        self.check_untouched({self.deviation("S25")["pair_id"]: {"agree": "nee", "remark": "klopt niet"}},
                             "zonder correctie")

    def test_correction_without_nee(self):
        self.check_untouched({self.deviation("S25")["pair_id"]: {"agree": None, "severity": "minor"}},
                             "correctie zonder akkoord = nee")

    def test_empty_row(self):
        self.check_untouched({self.deviation("S25")["pair_id"]: {"agree": None}}, "geen oordeel")

    def test_subtype_from_another_category(self):
        dev = self.deviation("S25")
        wrong = next(s for c, subs in rs.SUBTYPES.items() if c != dev["label"] for s in subs)
        self.check_untouched({dev["pair_id"]: {"agree": "nee", "subtype": wrong}}, "hoort niet bij")

    def test_control_with_severity(self):
        self.check_untouched({self.sampled_control("S25"): {"agree": "nee", "severity": "major"}},
                             "controle met severity")

    def test_omit_without_reason(self):
        self.check_untouched({self.deviation("S25")["pair_id"]: {"omit": "ja"}}, "weglaten zonder reden")

    def test_correction_equal_to_current(self):
        dev = self.deviation("S25")
        self.check_untouched({dev["pair_id"]: {"agree": "nee", "label": dev["label"]}}, "gelijk aan het huidige")


class TestOmit(Base):
    def test_left_out_pair_keeps_its_text(self):
        dev = self.deviation("S25")
        self.fill({dev["pair_id"]: {"omit": "ja", "remark": "vertolking onbruikbaar"}})
        before_hashes = {p.pair_id: ts.text_hash(p) for p in load_session(self.paths[0]).pairs}
        report = rs.apply_sheet(self.sheet, self.dir, "R")
        self.assertEqual(report.excluded, [("S25", dev["pair_id"], "vertolking onbruikbaar")])
        p = self.pair(dev["pair_id"])
        self.assertEqual((p["excluded"], p["excluded_reason"]), (True, "vertolking onbruikbaar"))
        self.assertEqual((p["source"], p["rendering"], p["label"]), (dev["source"], dev["rendering"], dev["label"]))
        after = load_session(self.dir / "S25.json")
        self.assertEqual({q.pair_id: ts.text_hash(q) for q in after.pairs}, before_hashes)
        self.assertTrue(next(q for q in after.pairs if q.pair_id == dev["pair_id"]).excluded)
        self.assertIs(self.data("S25")["reviewed"], True)


class TestMeasurementSkipsLeftOutPairs(Base):
    numbers = (20, 21, 30, 31)

    def setUp(self):
        super().setUp()
        for n, split in ((20, "dev"), (21, "dev"), (30, "test"), (31, "test")):
            p = self.dir / f"S{n}.json"
            d = json.loads(p.read_text(encoding="utf-8"))
            d.update(split=split, reviewed=True)
            p.write_text(json.dumps(d, indent=1), encoding="utf-8")
        self.left_test = next(p for p in json.loads((self.dir / "S30.json").read_text(encoding="utf-8"))["pairs"]
                              if p["expected_flag"])["pair_id"]
        self.left_dev = "S20-P01"
        for sid, pid in (("S30", self.left_test), ("S20", self.left_dev)):
            path = self.dir / f"{sid}.json"
            d = json.loads(path.read_text(encoding="utf-8"))
            for p in d["pairs"]:
                if p["pair_id"] == pid:
                    p.update(excluded=True, excluded_reason="onbruikbaar")
            path.write_text(json.dumps(d, indent=1), encoding="utf-8")
        self.sessions = {n: load_session(self.dir / f"S{n}.json") for n in self.numbers}

    def test_sealed_scoring_leaves_them_out_and_stays_valid(self):
        test = [self.sessions[30], self.sessions[31]]
        dev = [self.sessions[20], self.sessions[21]]
        preds = [{"pair_id": p.pair_id, "session_id": p.session_id, "direction": p.direction,
                  "text_hash": ts.text_hash(p), "labse": 0.5,
                  "issues_A": [{"type": "omission", "severity": "high"}], "issues_B": []}
                 for s in test for p in s.pairs]
        dev_scores = {p.pair_id: (0.5 if not p.is_control else 0.9) for s in dev for p in s.pairs}
        r = ts.compute_metrics(test, dev, preds, dev_scores, n_boot=20)
        self.assertEqual(r["excluded_pairs"], {})                       # nothing invalidates the run
        self.assertEqual(r["excluded_by_reviewer"], {"test": {self.left_test: "onbruikbaar"},
                                                     "dev": {self.left_dev: "onbruikbaar"}})
        self.assertEqual(r["n_test_pairs"], 15)
        a = r["variants"]["A"]["high_critical"]["numbers"]["all"]
        self.assertEqual(a["tp"] + a["fn"] + a["fp"] + a["tn"], 15)

    def test_detection_check_leaves_them_out_and_reports_them(self):
        async def fake_score(pairs, path):
            return [0.5 for _ in pairs]

        async def fake_ref(pairs):
            return {}

        old = dc._score, dc._reference_scores
        dc._score, dc._reference_scores = fake_score, fake_ref
        try:
            res = asyncio.run(dc.run(threshold=0.7, dry_run=True, sessions_dir=self.dir, n_boot=10))
        finally:
            dc._score, dc._reference_scores = old
        self.assertEqual(res.status, dc.RAN)
        self.assertEqual(res.numbers["excluded_by_reviewer"], {self.left_dev: "onbruikbaar"})
        self.assertEqual(res.numbers["n_dev"], 15)
        self.assertTrue(any("weggelaten door de reviewer" in n for n in res.numbers["notes"]))


if __name__ == "__main__":
    unittest.main()
