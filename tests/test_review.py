"""設計レビュー（2026-09-10）への対応の確認。索引は要らない。

対象:
  3  BA1 は「候補」に留め、集団別の最大頻度の行を出す
  5  SpliceAI の Δ が 0.5 以上なら BP4 を保留し、未取得なら「未評価」と明記する
  7  同じ位置の変異の判定が 1 星以下だけなら「弱い候補」と添える
  9  読み取り深度が取れない「収録なし」を PM2 の候補として扱わない
  10 データの版と解決経路の節
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from funcvep_report.gnomad import GnomadResult  # noqa: E402
from funcvep_report.i18n import use_lang  # noqa: E402
from funcvep_report.lookup import GenomicVariant, Resolution  # noqa: E402
from funcvep_report.report import _gnomad_rows, _qualify_bp4, provenance_rows, residue_rows  # noqa: E402
from funcvep_report.spliceai import SpliceResult  # noqa: E402


def _splice(ds: float) -> SpliceResult:
    return SpliceResult(status="scored", transcript="ENST1", ds={"AG": 0.0, "AL": ds, "DG": 0.0, "DL": 0.0},
                        dp={"AG": 0, "AL": 0, "DG": 0, "DL": 0})


class TestPopulationFrequency(unittest.TestCase):
    def test_ba1_is_a_candidate_and_uses_grpmax(self):
        g = GnomadResult(status="found", af=0.02, ac=20000, an=1_000_000, hom=5,
                         grpmax_id="eas", grpmax_ac=6000, grpmax_an=100_000)
        with use_lang("ja"):
            rows = _gnomad_rows(g, "2026-09-10")
        labels = [r.label for r in rows]
        self.assertIn("集団別の最大頻度（東アジア）", labels)
        grp = rows[labels.index("集団別の最大頻度（東アジア）")]
        self.assertIn("BA1 の候補", grp.value)          # 0.06 > 0.05 だが「候補」に留める
        self.assertNotIn("BA1", rows[0].value)           # 合算頻度 0.02 には付けない
        self.assertNotIn("該当", grp.value)
        self.assertIn("例外", rows[0].note)              # 疾患別の例外の確認が必要
        self.assertIn("浸透率", rows[-1].note)           # BS2 の注記

    def test_absent_without_coverage_is_not_pm2(self):
        g = GnomadResult(status="absent")
        with use_lang("ja"):
            rows = _gnomad_rows(g, "2026-09-10")
        self.assertIn("判断できません", rows[0].note)
        self.assertNotIn("候補となります", rows[0].note)
        g = GnomadResult(status="absent", depth_mean=40.0, over_20=0.99)
        with use_lang("ja"):
            rows = _gnomad_rows(g, "2026-09-10")
        self.assertIn("PM2_supporting", rows[0].note)
        self.assertIn("候補", rows[0].note)


class TestBP4AndSplicing(unittest.TestCase):
    def test_bp4_withheld_when_spliceai_high(self):
        with use_lang("ja"):
            self.assertIn("BP4 保留", _qualify_bp4("BP4_Supporting", _splice(0.61), True))
            self.assertIn("要確認", _qualify_bp4("BP4_Supporting", _splice(0.3), True))
            self.assertEqual(_qualify_bp4("BP4_Supporting", _splice(0.05), True), "BP4_Supporting")
            self.assertIn("未評価", _qualify_bp4("BP4_Supporting", None, True))
            self.assertIn("未評価", _qualify_bp4("BP4_Supporting", _splice(0.05), False))
            self.assertIn("未評価", _qualify_bp4("BP4_Supporting", SpliceResult(status="no_score"), True))


class TestWeakResidueEvidence(unittest.TestCase):
    def _row(self, pos, ref, alt, name, sig, review):
        import re
        m = re.search(r"p\.([A-Z][a-z]{2})(\d+)([A-Z][a-z]{2}|=|Ter)", name)
        return {"chrom": "4", "pos": pos, "ref": ref, "alt": alt, "name": name,
                "significance": sig, "review_status": review, "last_evaluated": "2020-01-01",
                "phenotypes": "Achondroplasia", "aa_ref3": m.group(1), "aa_pos": m.group(2), "aa_alt3": m.group(3)}

    def test_single_submitter_only_is_flagged_weak(self):
        this = GenomicVariant("4", 1804392, "G", "C")
        rows = [self._row(1804393, "G", "T", "NM_000142.5(FGFR3):c.1139G>T (p.Gly380Val)",
                          "Likely pathogenic", "criteria provided, single submitter")]
        with use_lang("ja"):
            out = residue_rows(rows, this, "R")
        self.assertIn("PM5", out[1].note)
        self.assertIn("弱い候補", out[1].note)
        self.assertIn("Achondroplasia", out[1].value)
        self.assertIn("2020-01-01", out[1].value)
        rows[0]["review_status"] = "reviewed by expert panel"
        with use_lang("ja"):
            out = residue_rows(rows, this, "R")
        self.assertNotIn("弱い候補", out[1].note)


class TestProvenance(unittest.TestCase):
    def test_rows_list_versions_path_and_model(self):
        res = Resolution(query="x", resolution_path=["入力の転写産物番号 NM_000142.5 を使用（NM_000142.5）"])
        versions = {"mane": {"label": "MANE", "version": "GRCh38 v1.5", "date": "2026-08-27"},
                    "_index": {"built": "2026-09-05"}}
        thresholds = {"meta": {"source": "published"}, "models": {}}
        with use_lang("ja"):
            rows = provenance_rows(res, versions, "abc1234 2026-09-10", thresholds, "2026-09-10 10:00",
                                   ["FuncVEP_CTE", None], "FuncVEP_CTI")
        text = "\n".join(f"{r.label}|{r.value}|{r.note}" for r in rows)
        self.assertIn("MANE: GRCh38 v1.5（2026-08-27）", text)
        self.assertIn("索引の作成日: 2026-09-05", text)
        self.assertIn("Supplementary Table 13", text)
        self.assertIn("abc1234", text)
        self.assertIn("NM_000142.5", text)
        self.assertIn("FuncVEP-CTI（実際に用いたモデル: FuncVEP-CTE）", text)


class TestBuildWithSplicing(unittest.TestCase):
    """報告書の組み立て（build）で、SpliceAI と BP4・まとめの箱・PM2 が正しく連動するか。"""

    def _res(self, funcvep: dict):
        from funcvep_report.lookup import Evidence, ResolvedVariant
        gv = GenomicVariant("17", 100, "A", "G")
        ev = Evidence(funcvep=funcvep, am_score=0.1, am_class="likely_benign", revel=0.1,
                      in_funcvep_table=True, same_residue=[], train_models=[])
        rv = ResolvedVariant(gene="X", ensg="ENSG1", enst="ENST1", refseq_nuc="NM_1.1",
                             aa_ref="A", position=1, aa_alt="V", genomic=gv, evidence=ev)
        return Resolution(query="X p.Ala1Val", variants=[rv], gene="X", ensg="ENSG1"), gv

    def _thresholds(self):
        import json
        return json.loads((Path(__file__).resolve().parent.parent / "data" / "acmg_thresholds_published.json")
                          .read_text(encoding="utf-8"))

    def test_neutral_with_high_spliceai_withholds_bp4_and_turns_box_amber(self):
        from funcvep_report.report import build
        low = {"FuncVEP_CTI": 0.01, "FuncVEP_CTE": 0.01, "FuncVEP_SP": 0.01}
        res, gv = self._res(low)
        with use_lang("ja"):
            rep = build(res, self._thresholds(), gnomad_online=True,
                        splice_results={gv.funcvep_id: _splice(0.61)},
                        gnomad_results={gv.funcvep_id: GnomadResult(status="error", reason="timeout")})
        vr = rep.variants[0]
        self.assertEqual(vr.adopted_model, "FuncVEP_CTI")
        self.assertTrue(vr.predictions[0].note.startswith("BP4 保留"))
        self.assertIn("（参考）", vr.predictions[1].note)
        self.assertEqual(vr.concordance_kind, "mixed")           # 予測は揃って neutral でも箱は橙
        self.assertTrue(any(r.label == "スプライシング" for r in vr.concordance_rows))
        # 通信失敗は PM2 の候補にしない
        self.assertFalse(any("PM2" in r.note for r in vr.population_rows))
        # 低い Δ なら通常どおり
        with use_lang("ja"):
            rep = build(res, self._thresholds(), gnomad_online=True,
                        splice_results={gv.funcvep_id: _splice(0.05)})
        vr = rep.variants[0]
        self.assertEqual(vr.concordance_kind, "neutral")
        self.assertTrue(vr.predictions[0].note.startswith("BP4_Strong（採用）"))
        # オフラインなら「未評価」と添え、PM2 も出さない
        with use_lang("ja"):
            rep = build(res, self._thresholds(), gnomad_online=False)
        vr = rep.variants[0]
        self.assertIn("未評価", vr.predictions[0].note)
        self.assertFalse(any("PM2" in r.note for r in vr.population_rows))

    def test_fallback_model_when_primary_missing(self):
        from funcvep_report.report import build
        res, gv = self._res({"FuncVEP_CTE": 0.95, "FuncVEP_SP": 0.9})
        with use_lang("ja"):
            rep = build(res, self._thresholds(), gnomad_online=False)
        vr = rep.variants[0]
        self.assertEqual(vr.adopted_model, "FuncVEP_CTE")
        self.assertIn("代替として FuncVEP-CTE", vr.adoption_note)
        self.assertIn("（採用）", vr.predictions[1].note)
        res, gv = self._res({})
        with use_lang("ja"):
            rep = build(res, self._thresholds(), gnomad_online=False)
        self.assertIsNone(rep.variants[0].adopted_model)
        self.assertIn("判定できません", rep.variants[0].adoption_note)


class TestThresholdBoundaries(unittest.TestCase):
    def test_published_cti_boundaries(self):
        import json
        from funcvep_report.acmg import assign
        thr = json.loads((Path(__file__).resolve().parent.parent / "data" / "acmg_thresholds_published.json")
                         .read_text(encoding="utf-8"))
        m = "FuncVEP_CTI"
        cases = [
            (0.6902, None, None), (0.6903, "PP3", "supporting"), (0.8022, "PP3", "supporting"),
            (0.8023, "PP3", "moderate"), (0.8583, "PP3", "intermediate"), (0.9108, "PP3", "intermediate"),
            (0.9109, "PP3", "strong"), (1.0, "PP3", "strong"),
            (0.1353, None, None), (0.1352, "BP4", "supporting"), (0.0643, "BP4", "moderate"),
            (0.0262, "BP4", "intermediate"), (0.0175, "BP4", "intermediate"), (0.0174, "BP4", "strong"),
            (0.0, "BP4", "strong"), (0.4, None, None),
        ]
        for score, crit, strength in cases:
            a = assign(score, m, thr)
            self.assertEqual((a.criterion, a.strength), (crit, strength), score)
        self.assertIsNone(assign(None, m, thr))
        self.assertIsNone(assign(0.9, m, None))


if __name__ == "__main__":
    unittest.main()
