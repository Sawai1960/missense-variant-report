"""FuncVEP 統合レポートツール。

Kayaalp ら, Nature Genetics (2026) の FuncVEP による予測を軸に、
AlphaMissense・REVEL・ClinVar・gnomAD の情報を 1 枚のレポートにまとめる。

FuncVEP 自体を再計算するものではない。著者らが公開した全ミスセンス変異の
予測済みスコアを引くだけなので、GPU も大規模な特徴量計算も要らない。
"""

from .config import load_config
from .lookup import Store, resolve
from .report import build as build_report
from .variant import ParseError, parse

__all__ = [
    "load_config",
    "Store",
    "resolve",
    "build_report",
    "parse",
    "ParseError",
]

__version__ = "0.1.0"
