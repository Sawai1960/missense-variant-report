# Missense Variant Evaluation Report — a local FuncVEP/ClinVEP lookup tool

*English overview for the FuncVEP authors. The interface and the PDF reports
can be shown in either Japanese or English (sidebar switch, or `?lang=en`);
the design document and user guide are in Japanese, as the tool is used by
clinicians at Hyogo Medical University, Japan. The Japanese design document is
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
- gnomAD v4 allele frequency and homozygote count, fetched per variant from
  the public gnomAD GraphQL API, with the maximum population frequency; a
  variant absent from gnomAD is reported as such (a PM2_supporting candidate
  only when coverage at that position is adequate), and BA1 is shown as a
  candidate above 0.05
- PP3/BP4 assigned from one pre-fixed model (FuncVEP-CTI by default; CTE and
  SP shown for reference), withheld for BP4 when SpliceAI suggests a splicing
  effect
- A concordance summary, interpretation caveats, and a closing section that
  records data versions, the code version and the transcript resolution path

Reports can be saved as PDF for clinical records and genetic counselling.
A Streamlit UI (`app.py`) is the front end.

## Design principles

1. **No recomputation.** FuncVEP is never re-run; the tool only looks up your
   precomputed scores. The released TSV is converted once into a local
   DuckDB/Parquet index (about 4 GB; the downloaded sources take another
   7 GB) for fast per-variant retrieval.
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
5. **Privacy.** The only off-site request is the gnomAD allele-frequency
   lookup, which sends the genomic coordinates of the variant (chromosome,
   position, reference and alternate base) and nothing else; no patient
   information is transmitted. The lookup can be switched off in the sidebar
   (or with `gnomad_af_mode: manual` in `config.yaml`), in which case
   frequencies are typed in from the lab report and the tool runs fully
   offline.

## License compliance

The FuncVEP prediction table and the converted index remain inside our
institution and are not redistributed, in accordance with the PolyForm Strict
license. **This repository contains only our own code and documentation** —
no FuncVEP data, no derived index. Anyone cloning it must obtain the released
predictions from Zenodo themselves (`scripts/01_download.py`).

Our own code and documentation are released under the MIT License (see
`LICENSE`). The data sources listed in the Japanese README keep their own
licenses and are not part of this repository.

## Running it

Requirements: Python 3.11 or later (verified on 3.14), about 12 GB of disk
space, and network access for the downloads. Before the first run, open
`config.yaml` and set `data_root` to the directory that will hold the
downloaded sources and the index (default `D:/FuncVEP`). On macOS or Linux
also point `pdf_font` / `pdf_font_bold` (Japanese) and `pdf_font_en` /
`pdf_font_en_bold` (English) to TrueType fonts present on your system; the
defaults are Windows font paths. Then:

```bash
python -m pip install -r requirements.txt
python scripts/01_download.py        # references, ~5.5 GB
python scripts/02_build_index.py     # builds the local index, ~1 h
python scripts/05_fetch_training_sets.py   # optional: training-set membership
python scripts/07_write_versions.py        # record reference-data versions
streamlit run app.py                 # opens http://localhost:8501
```

The index build downloads the released FuncVEP/ClinVEP table from Zenodo
(about 4 GB) together with MANE, ClinVar, AlphaMissense, REVEL and the gnomAD
constraint table; all of these are public downloads. Switch the interface to
English with the language selector in the sidebar (or open
`http://localhost:8501/?lang=en`).

On Windows, double-clicking `start_report_tool.bat` does the last step and opens
a browser tab (`レポートツールを起動.bat` is the same launcher with a Japanese
name for in-house users).

`config.yaml` sets the data directory (`data_root`) and the PDF font.
`scripts/04_selftest.py` runs a set of known variants end to end.

### Server mode (restricted access for invited users)

On the machine that holds the index, `scripts/start_server.bat` runs the app
headless on 127.0.0.1:8501 and restarts it if it exits; a Startup-folder
shortcut launches it at logon through `scripts/start_server_hidden.vbs`.
Invited users reach that instance at https://missense.human-genetics.uk
through a Cloudflare Tunnel, behind Cloudflare Access: only registered e-mail
addresses can log in (one-time code by e-mail), and the application and index
never leave our machine. This is how department members and the FuncVEP
authors can try the tool without installing anything. Setup notes (Japanese)
are kept in an internal guide (docs/限定公開_Cloudflare手順.md in the in-house working copy; not part of the public repository).

## Repository layout

| Path | Contents |
|---|---|
| `app.py` | Streamlit UI (Japanese / English) |
| `funcvep_report/` | Library: variant parsing, index lookup, ACMG tiers, report assembly, PDF output, string catalogue (`i18n.py`) |
| `scripts/01–07` | Download references, build the index, optional local calibration (kept for comparison only), self-test, fetch training sets, audit absent scores, record reference-data versions |
| `data/acmg_thresholds_published.json` | Supplementary Table 13 values as provided by the authors |
| `docs/設計書.md` | Design document (Japanese): architecture, coordinate handling, calibration comparison, verification log |
| `docs/funcvep_discrepancies.tsv` | The discrepancy table shared with the authors (2026-09-06) |

## Acknowledgements

FuncVEP/ClinVEP predictions, calibration values, and patient explanations of
edge cases in the released table: Kayaalp et al., *Nature Genetics* (2026),
doi:10.1038/s41588-026-02727-3, and personal communications (2026-09-05,
2026-09-07). We are grateful to the authors for their generosity.
