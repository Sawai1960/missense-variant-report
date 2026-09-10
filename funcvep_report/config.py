"""設定の読み込みとデータファイルの所在。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = PROJECT_ROOT / "config.yaml"


@dataclass(frozen=True)
class Paths:
    """索引済みデータの所在。すべて data_root からの相対で決まる。"""

    data_root: Path

    @property
    def raw(self) -> Path:
        return self.data_root / "raw"

    @property
    def index(self) -> Path:
        return self.data_root / "index"

    @property
    def tmp(self) -> Path:
        return self.data_root / "tmp"

    # --- 索引済み Parquet ---
    @property
    def funcvep(self) -> Path:
        return self.index / "funcvep"          # chrom= でパーティション

    @property
    def alphamissense(self) -> Path:
        return self.index / "alphamissense"    # chrom= でパーティション

    @property
    def revel(self) -> Path:
        return self.index / "revel"             # chrom= でパーティション

    @property
    def clinvar(self) -> Path:
        return self.index / "clinvar.parquet"

    @property
    def mane(self) -> Path:
        return self.index / "mane.parquet"

    @property
    def cds(self) -> Path:
        return self.index / "mane_cds.parquet"

    @property
    def gene_constraint(self) -> Path:
        return self.index / "gnomad_constraint.parquet"

    @property
    def transcript_map(self) -> Path:
        return self.index / "transcript_map.parquet"

    @property
    def training_sets(self) -> Path:
        # scripts/05_fetch_training_sets.py が作る。無くても動く。
        return self.index / "training_sets.parquet"


class Config:
    def __init__(self, raw: dict):
        self._raw = raw
        self.paths = Paths(Path(raw["data_root"]))
        self.assembly: str = raw.get("assembly", "GRCh38")
        self.primary_model: str = raw.get("primary_model", "FuncVEP_CTI")
        self.gnomad_af_mode: str = raw.get("gnomad_af_mode", "manual")
        self.pdf_font = Path(raw.get("pdf_font", ""))
        self._organization = raw.get("organization") or {}
        self._acmg = raw.get("acmg", {})

    def organization(self, lang: str = "ja") -> str:
        """発行元の名称。設定が無ければ空文字。"""
        if isinstance(self._organization, str):
            return self._organization
        return str(self._organization.get(lang) or self._organization.get("ja") or "")

    @property
    def prior_pathogenic(self) -> float:
        return float(self._acmg.get("prior_pathogenic", 0.0441))

    @property
    def min_review_stars(self) -> int:
        return int(self._acmg.get("min_review_stars", 2))

    @property
    def max_variants_per_gene(self) -> int:
        return int(self._acmg.get("max_variants_per_gene", 50))

    @property
    def published_thresholds_path(self) -> Path:
        """論文の公表値。リポジトリに同梱するのでプロジェクト相対。"""
        rel = self._acmg.get(
            "published_thresholds_file", "data/acmg_thresholds_published.json"
        )
        return PROJECT_ROOT / rel

    @property
    def thresholds_path(self) -> Path:
        """手元の ClinVar から算出した閾値。data_root 相対。"""
        rel = self._acmg.get("thresholds_file", "index/acmg_thresholds.json")
        return self.paths.data_root / rel

    def load_thresholds(self) -> dict | None:
        """PP3/BP4 の閾値。

        公表値（Supplementary Table 13）を優先する。設定で prefer_local を
        真にした場合と、公表値のファイルが無い場合だけ、手元の ClinVar から
        算出した値に落ちる。どちらも無ければ None を返し、呼び出し側は
        「未較正のため判定しない」と表示する。
        """
        order = [self.thresholds_path, self.published_thresholds_path]             if self._acmg.get("prefer_local", False)             else [self.published_thresholds_path, self.thresholds_path]
        for p in order:
            if p.exists():
                with p.open(encoding="utf-8") as fh:
                    data = json.load(fh)
                data.setdefault("meta", {}).setdefault(
                    "source", "published" if p == self.published_thresholds_path else "local"
                )
                return data
        return None


def load_config(path: Path | None = None) -> Config:
    with (path or CONFIG_PATH).open(encoding="utf-8") as fh:
        return Config(yaml.safe_load(fh))


MODELS = [
    "FuncVEP_CTI",
    "FuncVEP_CTE",
    "FuncVEP_SP",
    "ClinVEP_CTI",
    "ClinVEP_CTE",
    "ClinVEP_SP",
]

FUNCVEP_MODELS = ["FuncVEP_CTI", "FuncVEP_CTE", "FuncVEP_SP"]
