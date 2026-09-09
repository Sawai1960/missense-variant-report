"""同じ残基の ClinVar 判定を PS1 / PM5 に振り分ける処理。索引は要らない。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from funcvep_report.i18n import use_lang  # noqa: E402
from funcvep_report.lookup import GenomicVariant  # noqa: E402
from funcvep_report.report import residue_rows  # noqa: E402


def _row(pos, ref, alt, name, sig, review="criteria provided, multiple submitters, no conflicts"):
    import re
    m = re.search(r"p\.([A-Z][a-z]{2})(\d+)([A-Z][a-z]{2}|=|Ter)", name)
    return {"chrom": "4", "pos": pos, "ref": ref, "alt": alt, "name": name,
            "significance": sig, "review_status": review,
            "aa_ref3": m.group(1), "aa_pos": m.group(2), "aa_alt3": m.group(3)}


class TestResidueRows(unittest.TestCase):
    def setUp(self):
        self.this = GenomicVariant("4", 1804392, "G", "C")   # FGFR3 p.Gly380Arg (G>C)

    def test_same_change_other_nucleotide_is_ps1(self):
        rows = [
            _row(1804392, "G", "C", "NM_000142.5(FGFR3):c.1138G>C (p.Gly380Arg)", "Pathogenic"),
            _row(1804392, "G", "A", "NM_000142.5(FGFR3):c.1138G>A (p.Gly380Arg)", "Pathogenic"),
        ]
        with use_lang("ja"):
            out = residue_rows(rows, self.this, "R")
        self.assertIn("c.1138G>A", out[0].value)
        self.assertNotIn("c.1138G>C", out[0].value)      # 自分自身は除く
        self.assertIn("PS1", out[0].note)
        self.assertEqual(out[1].value, "なし")
        self.assertEqual(out[1].note, "")

    def test_other_pathogenic_change_is_pm5_and_benign_is_noted(self):
        rows = [
            _row(1804392, "G", "T", "NM_000142.5(FGFR3):c.1138G>T (p.Gly380Trp)", "Likely pathogenic"),
            _row(1804393, "G", "A", "NM_000142.5(FGFR3):c.1139G>A (p.Gly380Glu)", "Likely benign"),
            _row(1804393, "G", "C", "NM_000142.5(FGFR3):c.1139G>C (p.Gly380Ala)", "Uncertain significance"),
        ]
        with use_lang("ja"):
            out = residue_rows(rows, self.this, "R")
        self.assertEqual(out[0].value, "なし")
        self.assertTrue(out[1].value.startswith("c.1138G>T"))   # 病的が先頭
        self.assertIn("PM5", out[1].note)
        self.assertIn("良性", out[1].note)

    def test_synonymous_nonsense_unclassified_are_skipped(self):
        rows = [
            _row(1804394, "C", "T", "NM_000142.5(FGFR3):c.1140C>T (p.Gly380=)", "Likely benign"),
            _row(1804392, "G", "T", "NM_000142.5(FGFR3):c.1138G>T (p.Gly380Ter)", "Pathogenic"),
            _row(1804393, "G", "T", "NM_000142.5(FGFR3):c.1139G>T (p.Gly380Val)", "-", "-"),
        ]
        with use_lang("ja"):
            out = residue_rows(rows, self.this, "R")
        self.assertEqual(out[0].value, "なし")
        self.assertEqual(out[1].value, "なし")

    def test_conflicting_is_listed_but_not_evidence(self):
        rows = [_row(1804393, "G", "T", "NM_000142.5(FGFR3):c.1139G>T (p.Gly380Val)",
                     "Conflicting classifications of pathogenicity",
                     "criteria provided, conflicting classifications")]
        with use_lang("en"):
            out = residue_rows(rows, self.this, "R")
        self.assertIn("Conflicting", out[1].value)
        self.assertIn("(1-star)", out[1].value)
        self.assertEqual(out[1].note, "")


if __name__ == "__main__":
    unittest.main()
