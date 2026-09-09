"""gnomAD API の応答の読み取り。ネットワークは使わない。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from funcvep_report.gnomad import (  # noqa: E402
    parse_coverage_payload,
    parse_variant_payload,
)


class TestParseVariant(unittest.TestCase):
    def test_found_sums_exome_and_genome(self):
        payload = {"data": {"variant": {
            "variant_id": "11-5227002-T-A",
            "exome": {"ac": 2335, "an": 1458356, "af": 0.0016, "homozygote_count": 31, "filters": []},
            "genome": {"ac": 1937, "an": 152294, "af": 0.0127, "homozygote_count": 9, "filters": []},
            "coverage": {"exome": {"mean": 71.4, "over_20": 0.92},
                         "genome": {"mean": 31.4, "over_20": 0.955}},
        }}}
        r = parse_variant_payload(payload)
        self.assertEqual(r.status, "found")
        self.assertEqual((r.ac, r.an, r.hom), (4272, 1610650, 40))
        self.assertAlmostEqual(r.af, 4272 / 1610650)
        self.assertEqual(r.over_20, 0.955)
        self.assertTrue(r.well_covered)

    def test_found_exome_only(self):
        payload = {"data": {"variant": {
            "exome": {"ac": 1, "an": 1460854, "homozygote_count": 0, "filters": []},
            "genome": None,
            "coverage": {"exome": {"mean": 43.5, "over_20": 0.99}, "genome": None},
        }}}
        r = parse_variant_payload(payload)
        self.assertEqual(r.status, "found")
        self.assertEqual(r.an, 1460854)
        self.assertEqual(r.hom, 0)

    def test_absent(self):
        payload = {"errors": [{"message": "Variant not found"}], "data": {"variant": None}}
        r = parse_variant_payload(payload)
        self.assertEqual(r.status, "absent")
        self.assertIsNone(r.well_covered)

    def test_other_error(self):
        payload = {"errors": [{"message": "Internal server error"}], "data": {"variant": None}}
        r = parse_variant_payload(payload)
        self.assertEqual(r.status, "error")
        self.assertIn("Internal", r.reason)

    def test_zero_count_after_filtering_is_absent(self):
        # NEFL p.Pro8Leu の実例: 行はあるが AC0 フィルタで数えられていない
        payload = {"data": {"variant": {
            "exome": {"ac": 0, "an": 1447836, "homozygote_count": 0, "filters": ["AC0"]},
            "genome": None,
            "coverage": {"exome": {"mean": 40.0, "over_20": 0.97}, "genome": None},
        }}}
        r = parse_variant_payload(payload)
        self.assertEqual(r.status, "absent")
        self.assertEqual(r.filters, ["AC0"])
        self.assertTrue(r.well_covered)   # 深度は variant 応答から引き継ぐ

    def test_filters_are_collected(self):
        payload = {"data": {"variant": {
            "exome": {"ac": 3, "an": 100, "homozygote_count": 0, "filters": ["AC0"]},
            "genome": {"ac": 0, "an": 50, "homozygote_count": 0, "filters": ["AS_VQSR"]},
            "coverage": {},
        }}}
        r = parse_variant_payload(payload)
        self.assertEqual(r.filters, ["AC0", "AS_VQSR"])


class TestParseCoverage(unittest.TestCase):
    def test_picks_position(self):
        payload = {"data": {"region": {"coverage": {
            "exome": [{"pos": 9, "mean": 1.0, "over_20": 0.1}, {"pos": 10, "mean": 42.0, "over_20": 0.96}],
            "genome": [{"pos": 10, "mean": 30.0, "over_20": 0.95}],
        }}}}
        self.assertEqual(parse_coverage_payload(payload, 10), (42.0, 0.96))

    def test_missing_position(self):
        payload = {"data": {"region": {"coverage": {"exome": [], "genome": []}}}}
        self.assertEqual(parse_coverage_payload(payload, 10), (None, None))


if __name__ == "__main__":
    unittest.main()
