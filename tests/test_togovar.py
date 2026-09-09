"""TogoVar API の応答の読み取り。ネットワークは使わない。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from funcvep_report.togovar import parse_search_payload  # noqa: E402


def _payload(*variants):
    return {"data": list(variants)}


class TestParseSearch(unittest.TestCase):
    def test_picks_exact_variant_and_japanese_sources(self):
        # ALDH2 rs671 の実際の応答を縮めたもの
        v = {"chromosome": "12", "position": 111803962, "reference": "G", "alternate": "A",
             "frequencies": [
                 {"ac": 52, "an": 250, "filter": ["PASS"], "source": "jga_wes"},
                 {"aac": 11778, "ac": 90026, "an": 365930, "filter": ["PASS"], "source": "jga_snp"},
                 {"ac": 20904, "an": 108604, "filter": ["PASS"], "source": "tommo"},
                 {"ac": 10123, "an": 1456236, "filter": ["PASS"], "source": "gnomad_exomes"},
                 {"aac": 644, "ac": 4892, "an": 23528, "filter": ["PASS"], "source": "ncbn"},
             ]}
        r = parse_search_payload(_payload(v), "12", 111803962, "G", "A")
        self.assertEqual(r.status, "found")
        self.assertEqual([s.source for s in r.sources], ["tommo", "ncbn", "jga_wes", "jga_snp"])
        self.assertEqual(r.primary.label, "ToMMo 54KJPN")
        self.assertAlmostEqual(r.primary.af, 20904 / 108604)
        self.assertIsNone(r.primary.hom)
        self.assertEqual(r.sources[1].hom, 644)

    def test_other_variant_at_same_position_is_ignored(self):
        v = {"chromosome": "11", "position": 5227002, "reference": "T", "alternate": "G",
             "frequencies": [{"ac": 5, "an": 100, "source": "tommo"}]}
        r = parse_search_payload(_payload(v), "11", 5227002, "T", "A")
        self.assertEqual(r.status, "absent")

    def test_only_gnomad_sources_means_absent_in_japan(self):
        v = {"chromosome": "17", "position": 43063931, "reference": "G", "alternate": "A",
             "frequencies": [{"ac": 12, "an": 1461760, "source": "gnomad_exomes"}]}
        r = parse_search_payload(_payload(v), "17", 43063931, "G", "A")
        self.assertEqual(r.status, "absent")

    def test_zero_count_is_not_a_record(self):
        v = {"chromosome": "8", "position": 24956493, "reference": "G", "alternate": "A",
             "frequencies": [{"ac": 0, "an": 108604, "source": "tommo"}]}
        r = parse_search_payload(_payload(v), "8", 24956493, "G", "A")
        self.assertEqual(r.status, "absent")

    def test_empty(self):
        self.assertEqual(parse_search_payload({"data": []}, "1", 1, "A", "G").status, "absent")


if __name__ == "__main__":
    unittest.main()
