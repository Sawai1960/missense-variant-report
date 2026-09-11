"""参照データの版を index/versions.json に書き出す。

レポートの「データの版と解決経路」の節はこのファイルを読む。後日同じ入力で
結果が変わったとき、どのデータの版が違うのかを追えるようにするためのもの
（レビュー対応 10）。

版の情報は、取得元 URL に含まれる版番号と、raw フォルダーのファイルの更新日時
（＝取得日）から組み立てる。ファイルが無い項目は書かない。

使い方:
    python scripts/07_write_versions.py
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from funcvep_report.config import load_config  # noqa: E402

# (キー, 表示名, 英語の表示名, raw のファイル名, 版の表記, 英語の版の表記, 取得元)
ENTRIES = [
    ("funcvep", "FuncVEP / ClinVEP スコア表", "FuncVEP / ClinVEP score table", "FuncVEP_and_ClinVEP_scores.zip",
     "Zenodo record 20595206", "Zenodo record 20595206", "https://zenodo.org/records/20595206"),
    ("training", "FuncVEP 学習データ（学習セットの照合用）", "FuncVEP training sets (for membership checks)",
     "funcvep_repo_data.zip", "GitHub OzcelikLab/FuncVEP", "GitHub OzcelikLab/FuncVEP", "https://github.com/OzcelikLab/FuncVEP"),
    ("mane", "MANE（転写産物の対応表と CDS 配列）", "MANE (transcript mapping and CDS sequences)", "MANE.summary.txt.gz",
     "GRCh38 v1.5", "GRCh38 v1.5", "https://ftp.ncbi.nlm.nih.gov/refseq/MANE/MANE_human/release_1.5/"),
    ("clinvar", "ClinVar variant_summary", "ClinVar variant_summary", "variant_summary.txt.gz",
     "取得日の月次版", "monthly release as of the download date", "https://ftp.ncbi.nlm.nih.gov/pub/clinvar/tab_delimited/"),
    ("alphamissense", "AlphaMissense", "AlphaMissense", "AlphaMissense_hg38.tsv.gz",
     "Zenodo record 10813168", "Zenodo record 10813168", "https://zenodo.org/records/10813168"),
    ("revel", "REVEL", "REVEL", "revel-v1.3_all_chromosomes.zip", "v1.3", "v1.3",
     "https://sites.google.com/site/revelgenomics/"),
    ("constraint", "gnomAD 遺伝子制約指標", "gnomAD gene constraint metrics", "gnomad_constraint_metrics.txt",
     "FuncVEP リポジトリ同梱（gnomAD v2.1.1 相当）", "bundled with the FuncVEP repository (gnomAD v2.1.1)",
     "https://github.com/OzcelikLab/FuncVEP/tree/main/resources/gene_level_features"),
]


def main() -> None:
    cfg = load_config()
    raw = cfg.paths.data_root / "raw"
    out: dict = {}
    for key, label, label_en, fname, version, version_en, source in ENTRIES:
        f = raw / fname
        if not f.exists():
            continue
        date = datetime.fromtimestamp(f.stat().st_mtime).strftime("%Y-%m-%d")
        out[key] = {"label": label, "label_en": label_en, "version": version, "version_en": version_en,
                    "date": date, "file": fname, "bytes": f.stat().st_size, "source": source}
    newest_index = max((p.stat().st_mtime for p in cfg.paths.index.glob("*.parquet")), default=None)
    out["_index"] = {
        "built": datetime.fromtimestamp(newest_index).strftime("%Y-%m-%d") if newest_index else "",
        "written": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "note": "date は raw フォルダーのファイルの更新日時（取得日）。built は索引ファイルの最新更新日",
    }
    path = cfg.paths.index / "versions.json"
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {path}")
    for k, v in out.items():
        if not k.startswith("_"):
            print(f"  {v['label']}: {v['version']} ({v['date']})")


if __name__ == "__main__":
    main()
