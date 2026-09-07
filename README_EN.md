# Missense Variant Report — a local FuncVEP/ClinVEP lookup tool

*English overview for the FuncVEP authors. The tool itself (UI, PDF reports,
design documents) is in Japanese, as it is used by clinicians at
Hyogo Medical University, Japan. This page summarises what the tool does and
how your released resources are used. The Japanese design document is
[docs/設計書.md](docs/設計書.md); [README.md](README.md) is the Japanese
user guide.*

## What it does

Given a newly observed missense variant (gene + amino-acid substitution, or a
transcript HGVS string), the tool produces a one-page report combining:

- **FuncVEP-CTI / CTE / SP** scores from your released ~73M-variant prediction
  table (Zenodo), with ClinVEP scores shown as a contrast
- **PP3/BP4 evidence tiers** using the Supplementary Table 13 calibration you
  kindly provided (tiers read as 1 = Supporting, 2 = Moderate,
  3 = Intermediate, 4 = Strong, per your 2026-09-07 message and
  doi:10.1016/j.gim.2025.101402)
- AlphaMissense, REVEL, ClinVar (with review status), and gnomAD gene
  constraint
- A concordance summary and interpretation caveats

Reports can be saved as PDF for clinical records and genetic counselling.
A Streamlit UI (`app.py`) is the front end.

## Design principles

1. **No recomputation.** FuncVEP is never re-run; the tool only looks up your
   precomputed scores. The released TSV is converted once into a local
   DuckDB/Parquet index (~30 GB) for fast per-variant retrieval.
2. **Functional impact ≠ clinical pathogenicity.** The report states this
   prominently, and the user guide walks through HBB p.Glu7Val and
   CFTR p.Arg117His as worked examples of the distinction — following the
   argument in your paper.
3. **Absent scores carry no information.** Variants that are blank (trained on
   a subset of models) or absent from the merged table (trained on all six, or
   lost in dataset assembly, per your 2026-09-05 and 2026-09-07 messages) are
   reported as "no FuncVEP/ClinVEP evidence", never as a red flag. The
   training-set membership (from your GitHub `models/` directories) is shown
   so clinicians see *why* a score is unavailable.
4. **ACMG framing.** Scores enter classification only as PP3/BP4
   (computational evidence), never PS3/BS3.
5. **Privacy.** Nothing is sent off-site. Population frequencies are typed in
   manually from the lab report rather than fetched, so patient variants never
   leave the institution.

## License compliance

The FuncVEP prediction table and the converted index remain inside our
institution and are not redistributed, in accordance with the PolyForm Strict
license. **This repository contains only our own code and documentation** —
no FuncVEP data, no derived index. Anyone cloning it must obtain the released
predictions from Zenodo themselves (`scripts/01_download.py`).

## Repository layout

| Path | Contents |
|---|---|
| `app.py` | Streamlit UI |
| `funcvep_report/` | Library: variant parsing, index lookup, ACMG tiers, report assembly, PDF output |
| `scripts/01–06` | Download references, build the index, optional local calibration (kept for comparison only), self-test, fetch training sets, audit absent scores |
| `data/acmg_thresholds_published.json` | Supplementary Table 13 values as provided by the authors |
| `docs/設計書.md` | Design document (Japanese): architecture, coordinate handling, calibration comparison, verification log |
| `docs/funcvep_discrepancies.tsv` | The discrepancy table shared with the authors (2026-09-06) |

## Reading the sample PDFs (section guide)

The PDF sections are, in order: **遺伝子** gene & gnomAD constraint /
**集団頻度** population frequency (manual entry) / **変異** variant &
coordinates / **FuncVEP（機能的影響の予測）** FuncVEP scores with
damaging–neutral calls at your per-model binary cutoffs and PP3/BP4 tiers /
**他の予測ツール** ClinVEP, AlphaMissense, REVEL / **ClinVar** /
**指標同士の一致** concordance / **PP3/BP4 の閾値について** threshold
provenance / **解釈上の注意** interpretation caveats.

## Acknowledgements

FuncVEP/ClinVEP predictions, calibration values, and patient explanations of
edge cases in the released table: Kayaalp et al., *Nature Genetics* (2026),
doi:10.1038/s41588-026-02727-3, and personal communications (2026-09-05,
2026-09-07). We are grateful to the authors for their generosity.
