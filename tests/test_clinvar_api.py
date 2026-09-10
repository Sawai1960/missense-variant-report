"""ClinVar API（VCV XML）の読み取り。ネットワークは使わない。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from funcvep_report.clinvar_api import is_generic_condition, moi_code, parse_vcv_xml  # noqa: E402

XML = """<ClinVarResult-Set>
<VariationArchive>
  <ClassifiedRecord>
    <RCVList>
      <RCVAccession Title="x AND Achondroplasia" Accession="RCV000017724" Version="96">
        <ClassifiedConditionList><ClassifiedCondition DB="MedGen" ID="C0001080">Achondroplasia</ClassifiedCondition></ClassifiedConditionList>
        <RCVClassifications><GermlineClassification>
          <ReviewStatus>criteria provided, multiple submitters, no conflicts</ReviewStatus>
          <Description DateLastEvaluated="2026-03-02" SubmissionCount="38">Pathogenic</Description>
        </GermlineClassification></RCVClassifications>
      </RCVAccession>
      <RCVAccession Title="x AND not provided" Accession="RCV000255750" Version="77">
        <ClassifiedConditionList><ClassifiedCondition DB="MedGen" ID="C3661900">not provided</ClassifiedCondition></ClassifiedConditionList>
        <RCVClassifications><GermlineClassification>
          <ReviewStatus>criteria provided, multiple submitters, no conflicts</ReviewStatus>
          <Description DateLastEvaluated="2026-01-01" SubmissionCount="14">Pathogenic</Description>
        </GermlineClassification></RCVClassifications>
      </RCVAccession>
      <RCVAccession Title="x AND Epidermal nevus" Accession="RCV000029207" Version="14">
        <ClassifiedConditionList><ClassifiedCondition DB="MedGen" ID="C0334082">Epidermal nevus</ClassifiedCondition></ClassifiedConditionList>
        <RCVClassifications><GermlineClassification>
          <ReviewStatus>no assertion criteria provided</ReviewStatus>
          <Description DateLastEvaluated="2011-04-15" SubmissionCount="1">Pathogenic</Description>
        </GermlineClassification></RCVClassifications>
      </RCVAccession>
    </RCVList>
    <ClinicalAssertionList>
      <ClinicalAssertion ID="1"><AttributeSet><Attribute Type="ModeOfInheritance">Autosomal dominant inheritance</Attribute></AttributeSet></ClinicalAssertion>
      <ClinicalAssertion ID="2"><AttributeSet><Attribute Type="ModeOfInheritance">Autosomal dominant inheritance</Attribute></AttributeSet></ClinicalAssertion>
      <ClinicalAssertion ID="3"><AttributeSet><Attribute Type="ModeOfInheritance">Unknown mechanism</Attribute></AttributeSet></ClinicalAssertion>
      <ClinicalAssertion ID="4"><AttributeSet><Attribute Type="AssertionMethod">ACMG</Attribute></AttributeSet></ClinicalAssertion>
      <ClinicalAssertion ID="5"/>
    </ClinicalAssertionList>
  </ClassifiedRecord>
</VariationArchive>
</ClinVarResult-Set>"""


class TestParseVCV(unittest.TestCase):
    def test_rows_sorted_by_submissions_and_generic_filtered(self):
        r = parse_vcv_xml(XML)
        self.assertEqual(r.status, "found")
        self.assertEqual([x.condition for x in r.rows], ["Achondroplasia", "not provided", "Epidermal nevus"])
        self.assertEqual([x.condition for x in r.specific], ["Achondroplasia", "Epidermal nevus"])
        self.assertEqual(r.top_condition, "Achondroplasia")
        self.assertEqual(r.rows[0].submissions, 38)
        self.assertEqual(r.rows[0].date, "2026-03-02")

    def test_mode_of_inheritance_counts(self):
        r = parse_vcv_xml(XML)
        self.assertEqual(r.n_scv, 5)
        self.assertEqual(r.moi, {"AD": 2, "unknown": 1})
        self.assertEqual(moi_code("X-linked recessive inheritance"), "XLR")
        self.assertEqual(moi_code("Something else"), "Something else")
        # 報告書の行: 略号と件数、記入率
        from funcvep_report.i18n import use_lang
        from funcvep_report.report import _moi_row
        with use_lang("ja"):
            rows = _moi_row(r)
        self.assertEqual(rows[0].value, "AD 2 件、不明 1 件（提出 5 件中 3 件が記入。参考）")
        with use_lang("ja"):
            self.assertEqual(_moi_row(parse_vcv_xml(XML.replace("ModeOfInheritance", "Other"))), [])

    def test_absent_when_no_rcv(self):
        self.assertEqual(parse_vcv_xml("<ClinVarResult-Set/>").status, "absent")

    def test_generic_rule(self):
        for name in ("not provided", "14 conditions", "See cases", "FGFR3-related disorder",
                     "Inborn genetic diseases", "alpha Thalassemia;Heinz body anemia", ""):
            self.assertTrue(is_generic_condition(name), name)
        for name in ("Achondroplasia", "Hb SS disease", "Charcot-Marie-Tooth disease type 2E"):
            self.assertFalse(is_generic_condition(name), name)


if __name__ == "__main__":
    unittest.main()
