"""入力解析とコドン翻訳の回帰テスト。データの索引は要らない。

    python -m unittest discover -s tests
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from funcvep_report.variant import (  # noqa: E402
    CodingInput,
    ParseError,
    ProteinInput,
    apply_cds_substitution,
    parse,
    translate_codon,
)


class TestProteinParsing(unittest.TestCase):
    def test_three_letter(self):
        v = parse("BRCA1 p.Arg1699Trp")
        self.assertIsInstance(v, ProteinInput)
        self.assertEqual((v.gene, v.aa_ref, v.position, v.aa_alt),
                         ("BRCA1", "R", 1699, "W"))

    def test_one_letter(self):
        self.assertEqual(parse("BRCA1 R1699W").protein_variant, "R1699W")

    def test_colon_separator(self):
        self.assertEqual(parse("TP53:p.R175H").protein_variant, "R175H")

    def test_gene_is_uppercased(self):
        self.assertEqual(parse("brca1 Arg1699Trp").gene, "BRCA1")

    def test_no_p_prefix(self):
        self.assertEqual(parse("SMAD4 Arg361His").protein_variant, "R361H")

    def test_gene_with_digits_and_dash(self):
        self.assertEqual(parse("HLA-B p.Asn97Ser").gene, "HLA-B")


class TestCodingParsing(unittest.TestCase):
    def test_refseq(self):
        v = parse("NM_007294.4:c.5095C>T")
        self.assertIsInstance(v, CodingInput)
        self.assertEqual(v.transcript, "NM_007294.4")
        self.assertEqual(v.transcript_base, "NM_007294")
        self.assertEqual((v.cds_position, v.ref_base, v.alt_base), (5095, "C", "T"))

    def test_refseq_with_gene(self):
        v = parse("NM_007294.4(BRCA1):c.5095C>T")
        self.assertEqual(v.gene, "BRCA1")

    def test_ensembl(self):
        self.assertEqual(parse("ENST00000357654:c.5095C>T").transcript_base,
                         "ENST00000357654")

    def test_spaces_around_arrow(self):
        self.assertEqual(parse("NM_000546.6:c.524G > A").alt_base, "A")


class TestRejections(unittest.TestCase):
    def _rejects(self, text: str, fragment: str):
        with self.assertRaises(ParseError) as ctx:
            parse(text)
        self.assertIn(fragment, str(ctx.exception))

    def test_empty(self):
        self._rejects("", "空")

    def test_synonymous(self):
        self._rejects("BRCA1 p.Arg1699=", "同義置換")

    def test_nonsense_ter(self):
        self._rejects("TP53 p.Arg213Ter", "ナンセンス")

    def test_nonsense_star(self):
        self._rejects("TP53 p.Arg213*", "ナンセンス")

    def test_same_amino_acid(self):
        self._rejects("TP53 p.Arg175Arg", "同じ")

    def test_gibberish(self):
        self._rejects("なにか変な入力", "認識できません")

    def test_indel_not_supported(self):
        self._rejects("NM_007294.4:c.5095_5096del", "対象外")


class TestFlexibleInputs(unittest.TestCase):
    """検査報告書にある多様な書き方。"""

    def test_gene_plus_cds(self):
        v = parse("SDHB c.574T>C")
        self.assertIsInstance(v, CodingInput)
        self.assertEqual((v.gene, v.transcript, v.cds_position, v.ref_base, v.alt_base),
                         ("SDHB", None, 574, "T", "C"))
        self.assertIsNone(v.protein)

    def test_gene_cds_with_protein_in_parentheses(self):
        v = parse("SDHB c.574T>C (p.Cys192Arg)")
        self.assertIsInstance(v, CodingInput)
        self.assertEqual(v.protein, ("C", 192, "R"))

    def test_protein_first_then_cds(self):
        v = parse("SDHB p.Cys192Arg (c.574T>C)")
        self.assertIsInstance(v, CodingInput)
        self.assertEqual(v.cds_position, 574)
        self.assertEqual(v.protein, ("C", 192, "R"))

    def test_transcript_cds_protein(self):
        v = parse("NM_003000.3:c.574T>C (p.Cys192Arg)")
        self.assertEqual((v.transcript, v.gene, v.protein), ("NM_003000.3", None, ("C", 192, "R")))

    def test_gene_with_transcript_in_parentheses(self):
        v = parse("SDHB(NM_003000.3):c.574T>C")
        self.assertEqual((v.transcript, v.gene), ("NM_003000.3", "SDHB"))

    def test_separators_and_fullwidth(self):
        for text in ("SDHB:c.574T>C", "SDHB c.574 T>C", "ＳＤＨＢ　ｃ．５７４Ｔ＞Ｃ", "SDHB, c.574T>C", "SDHB／c.574T>C"):
            v = parse(text)
            self.assertIsInstance(v, CodingInput, text)
            self.assertEqual((v.gene, v.cds_position, v.ref_base, v.alt_base), ("SDHB", 574, "T", "C"), text)

    def test_protein_without_p_and_lowercase(self):
        self.assertEqual(parse("SDHB Cys192Arg").protein_variant, "C192R")
        self.assertEqual(parse("sdhb c192r").protein_variant, "C192R")
        self.assertEqual(parse("SDHB (p.Cys192Arg)").protein_variant, "C192R")

    def test_protein_with_transcript_noted(self):
        v = parse("SDHB p.Cys192Arg NM_003000.3")
        self.assertIsInstance(v, ProteinInput)
        self.assertEqual(v.transcript, "NM_003000.3")

    def test_gene_that_looks_like_a_substitution(self):
        # C1R は遺伝子名だが R100W にも見える。2 語あれば最初を遺伝子とする
        v = parse("C1R p.Arg100Trp")
        self.assertEqual((v.gene, v.protein_variant), ("C1R", "R100W"))
        v = parse("C1R R100W")
        self.assertEqual((v.gene, v.protein_variant), ("C1R", "R100W"))

    def test_helpful_errors(self):
        with self.assertRaises(ParseError) as ctx:
            parse("c.574T>C")
        self.assertIn("遺伝子記号か転写産物番号", str(ctx.exception))
        with self.assertRaises(ParseError) as ctx:
            parse("SDHB")
        self.assertIn("SDHB", str(ctx.exception))
        self.assertIn("変異の表記", str(ctx.exception))
        with self.assertRaises(ParseError) as ctx:
            parse("SDHB c.574_575del")
        self.assertIn("対象外", str(ctx.exception))


class TestCodon(unittest.TestCase):
    def test_translate(self):
        self.assertEqual(translate_codon("ATG"), "M")
        self.assertEqual(translate_codon("CGG"), "R")
        self.assertEqual(translate_codon("TGG"), "W")
        self.assertEqual(translate_codon("TGA"), "*")

    def _cds_with_codon(self, codon_no: int, codon: str, length: int = 6000) -> str:
        seq = list("ATG" + "AAA" * (length // 3))
        start = (codon_no - 1) * 3
        for i, b in enumerate(codon):
            seq[start + i] = b
        return "".join(seq)

    def test_substitution_first_base(self):
        cds = self._cds_with_codon(1699, "CGG")
        self.assertEqual(apply_cds_substitution(cds, 5095, "C", "T"),
                         ("R", 1699, "W"))

    def test_substitution_second_base(self):
        cds = self._cds_with_codon(175, "CGC")
        # c.524 は 175 番コドンの 2 塩基目
        self.assertEqual(apply_cds_substitution(cds, 524, "G", "A"),
                         ("R", 175, "H"))

    def test_reference_mismatch_is_caught(self):
        cds = self._cds_with_codon(1699, "CGG")
        with self.assertRaises(ParseError) as ctx:
            apply_cds_substitution(cds, 5095, "A", "T")
        self.assertIn("参照塩基が一致しません", str(ctx.exception))

    def test_position_out_of_range(self):
        cds = self._cds_with_codon(10, "CGG", length=90)
        with self.assertRaises(ParseError) as ctx:
            apply_cds_substitution(cds, 99999, "C", "T")
        self.assertIn("コード領域", str(ctx.exception))


if __name__ == "__main__":
    unittest.main(verbosity=2)
