"""外部データ源（SpliceAI・ClinGen・MaveDB・LitVar）の応答の読み取り。ネットワークは使わない。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from funcvep_report import clingen, litvar, mavedb, spliceai  # noqa: E402


class TestSpliceAI(unittest.TestCase):
    payload = [{"transcript_consequences": [
        {"transcript_id": "ENST00000000001", "gene_symbol": "BRCA1",
         "spliceai": {"DS_AG": 0.01, "DS_AL": 0.14, "DS_DG": 0, "DS_DL": 0, "DP_AG": -22, "DP_AL": 20, "DP_DG": 20, "DP_DL": -41, "SYMBOL": "BRCA1"}},
        {"transcript_id": "ENST00000357654", "gene_symbol": "BRCA1",
         "spliceai": {"DS_AG": 0.02, "DS_AL": 0.61, "DS_DG": 0, "DS_DL": 0.1, "DP_AG": -22, "DP_AL": 20, "DP_DG": 20, "DP_DL": -41, "SYMBOL": "BRCA1"}},
        {"transcript_id": "ENST00000999999", "gene_symbol": "OTHER"},
    ]}]

    def test_prefers_mane_transcript(self):
        r = spliceai.parse_vep_payload(self.payload, "ENST00000357654.9", "BRCA1")
        self.assertEqual(r.status, "scored")
        self.assertEqual(r.transcript, "ENST00000357654")
        self.assertEqual(r.max_type, "AL")
        self.assertAlmostEqual(r.max_ds, 0.61)
        self.assertEqual(r.level, "high")

    def test_falls_back_to_max_in_gene(self):
        r = spliceai.parse_vep_payload(self.payload, "ENST00000000002", "BRCA1")
        self.assertEqual(r.transcript, "ENST00000357654")

    def test_low_level_and_no_score(self):
        r = spliceai.parse_vep_payload(self.payload, "ENST00000000001", "BRCA1")
        self.assertEqual(r.level, "low")
        self.assertEqual(spliceai.parse_vep_payload([{"transcript_consequences": []}], None, None).status, "no_score")


class TestClinGen(unittest.TestCase):
    csv_text = (
        '"CLINGEN GENE DISEASE VALIDITY CURATIONS","","","","","","","","",""\n'
        '"FILE CREATED: 2026-09-09","","","","","","","","",""\n'
        '"GENE SYMBOL","GENE ID (HGNC)","DISEASE LABEL","DISEASE ID (MONDO)","MOI","SOP","CLASSIFICATION","ONLINE REPORT","CLASSIFICATION DATE","GCEP"\n'
        '"+++++++++++","++++++++++++++","+++++++++++++","++++++++++++++++++","+++++++++","+++++++++","++++++++++++++","+++++++++++++","+++++++++++++++++++","+++++++++++++++++++"\n'
        '"NEFL","HGNC:7739","Charcot-Marie-Tooth disease type 2","MONDO:0018993","AR","SOP9","Definitive","https://x/1","2023-01-10T17:00:00.000Z","GCEP A"\n'
        '"NEFL","HGNC:7739","Charcot-Marie-Tooth disease","MONDO:0015626","AD","SOP9","Definitive","https://x/2","2024-01-10T17:00:00.000Z","GCEP A"\n'
    )

    def test_parse(self):
        gv = clingen.parse_csv(self.csv_text)
        self.assertEqual(list(gv), ["NEFL"])
        self.assertEqual([g.moi for g in gv["NEFL"]], ["AD", "AR"])   # 新しい順
        self.assertEqual(gv["NEFL"][0].date, "2024-01-10")
        self.assertEqual(clingen.moi_label("AR", "ja"), "潜性遺伝（劣性遺伝）")
        self.assertEqual(clingen.moi_label("XL", "en"), "X-linked")


class TestMaveDB(unittest.TestCase):
    detail = {
        "urn": "urn:mavedb:00000097-0-2", "title": "BRCA1 SGE Normalized Scores",
        "shortDescription": "BRCA1 SGE", "publishedDate": "2025-05-12T00:00:00", "numVariants": 3893,
        "targetGenes": [{"name": "BRCA1", "targetAccession": {"accession": "NM_007294.3"}}],
        "primaryPublicationIdentifiers": [{"identifier": "30209399", "dbName": "PubMed",
                                           "authors": [{"name": "Findlay, Gregory M"}],
                                           "publicationYear": 2018, "publicationJournal": "Nature"}],
        "scoreCalibrations": [{"title": "Investigator-provided functional classes", "functionalClassifications": [
            {"label": "Functional", "functionalClassification": "normal", "range": [-0.748, None], "inclusiveLowerBound": True, "inclusiveUpperBound": False},
            {"label": "Intermediate", "functionalClassification": "not_specified", "range": [-1.328, -0.748], "inclusiveLowerBound": False, "inclusiveUpperBound": False},
            {"label": "Non-functional", "functionalClassification": "abnormal", "range": [None, -1.328], "inclusiveLowerBound": False, "inclusiveUpperBound": True},
        ]}],
    }

    def test_parse_and_classify(self):
        ss = mavedb.parse_score_set(self.detail)
        self.assertTrue(ss.full_length_numbering)
        self.assertEqual(ss.citation, "Findlay (2018) Nature")
        self.assertEqual(ss.classify(0.1).classification, "normal")
        self.assertEqual(ss.classify(-1.0).label, "Intermediate")
        self.assertEqual(ss.classify(-2.0).classification, "abnormal")
        self.assertEqual(ss.classify(-1.328).classification, "abnormal")   # 上端を含む

    def test_single_gene_filter_and_scores(self):
        payload = {"scoreSets": [
            {"urn": "a", "targetGenes": [{"name": "BRCA1"}]},
            {"urn": "b", "targetGenes": [{"name": "BRCA1"}, {"name": "TP53"}]},
        ]}
        self.assertEqual([s["urn"] for s in mavedb.single_gene_sets(payload, "BRCA1")], ["a"])
        csv_text = "accession,hgvs_nt,hgvs_pro,score\nx#1,NA,p.Thr167Cys,0\nx#2,NA,p.Arg1699Trp,-1.9\n"
        self.assertEqual(mavedb.find_in_scores(csv_text, "p.Arg1699Trp"), -1.9)
        self.assertIsNone(mavedb.find_in_scores(csv_text, "p.Arg1699Gln"))

    def test_match_via_cdna_when_hgvs_pro_missing(self):
        # SGE の表は hgvs_pro が NA で c. 表記だけ。手元の CDS で翻訳して照合する
        cds = "ATGTGTGGC"          # Met Cys Gly
        csv_text = ("accession,hgvs_nt,hgvs_splice,hgvs_pro,score\n"
                    "x#1,NM_1.1:c.4T>G,NA,NA,-2.5\n"       # Cys2Gly
                    "x#2,NM_1.1:c.6T>C,NA,NA,0.1\n")       # 同義
        self.assertEqual(mavedb.find_in_scores(csv_text, "p.Cys2Gly", cds), -2.5)
        self.assertIsNone(mavedb.find_in_scores(csv_text, "p.Cys2Gly"))          # cds 無しでは照合しない
        self.assertIsNone(mavedb.find_in_scores(csv_text, "p.Cys2Ser", cds))


class TestLitVar(unittest.TestCase):
    items = [
        {"_id": "litvar@rs1##", "rsid": "rs1", "gene": ["OTHER"], "name": "p.R1699W"},
        {"_id": "litvar@rs55770810##", "rsid": "rs55770810", "gene": ["BRCA1"], "name": "p.R1699W"},
    ]

    def test_pick_by_rsid_or_name(self):
        self.assertEqual(litvar.pick_variant(self.items, "BRCA1", "R1699W", ["rs55770810"])["rsid"], "rs55770810")
        self.assertEqual(litvar.pick_variant(self.items, "BRCA1", "R1699W", [])["rsid"], "rs55770810")
        self.assertIsNone(litvar.pick_variant(self.items, "BRCA1", "R1699Q", []))


if __name__ == "__main__":
    unittest.main()
