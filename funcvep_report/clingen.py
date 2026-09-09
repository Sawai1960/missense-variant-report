"""ClinGen の遺伝子と疾患の関係（Gene-Disease Validity）を引く。

ClinGen の専門家パネルが「この遺伝子はこの疾患の原因として確立しているか」を
Definitive / Strong / Moderate / Limited / Disputed / Refuted / No Known Disease
Relationship で評価している。遺伝形式（MOI）も付く。pLI の読み方、BS2（ホモ接合体の
有無）、PM2 の重みづけに必要な文脈になる。

一覧は 1 つの CSV（約 1 MB、約 3,700 行）として公開されているので、丸ごと取得して
ローカルに置き、古くなったら取り直す。変異ごとの通信は無い。
"""

from __future__ import annotations

import csv
import io
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

DOWNLOAD_URL = "https://search.clinicalgenome.org/kb/gene-validity/download"
USER_AGENT = "funcvep-report/0.1"
MAX_AGE_DAYS = 30

# 遺伝形式の略号（ClinGen の MOI 欄）
MOI_LABELS = {
    "AD": ("顕性遺伝（優性遺伝）", "autosomal dominant"),
    "AR": ("潜性遺伝（劣性遺伝）", "autosomal recessive"),
    "XL": ("X 連鎖", "X-linked"),
    "SD": ("半顕性（セミドミナント）", "semidominant"),
    "MT": ("ミトコンドリア", "mitochondrial"),
    "AD/AR": ("顕性および潜性", "autosomal dominant and recessive"),
    "Undetermined": ("未確定", "undetermined"),
}


@dataclass
class GeneDisease:
    gene: str
    disease: str
    mondo: str
    moi: str
    classification: str
    date: str          # YYYY-MM-DD
    url: str


def parse_csv(text: str) -> dict[str, list[GeneDisease]]:
    """ClinGen の CSV（先頭に説明行、次に見出し、区切り行、データ）を遺伝子別に分ける。"""
    rows = list(csv.reader(io.StringIO(text)))
    try:
        hdr = next(i for i, r in enumerate(rows) if r and r[0].strip() == "GENE SYMBOL")
    except StopIteration:
        return {}
    out: dict[str, list[GeneDisease]] = {}
    for r in rows[hdr + 1:]:
        if len(r) < 9 or not r[0] or r[0].startswith("+"):
            continue
        gd = GeneDisease(gene=r[0].strip(), disease=r[2].strip(), mondo=r[3].strip(),
                         moi=r[4].strip(), classification=r[6].strip(),
                         date=r[8].strip()[:10], url=r[7].strip())
        out.setdefault(gd.gene, []).append(gd)
    for lst in out.values():
        lst.sort(key=lambda g: g.date, reverse=True)
    return out


def _download(timeout: float = 60.0) -> str:
    req = urllib.request.Request(DOWNLOAD_URL, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8")


def load(cache_path: Path, online: bool = True,
         max_age_days: int = MAX_AGE_DAYS) -> dict[str, list[GeneDisease]] | None:
    """一覧を返す。キャッシュが無く取得もできなければ None。"""
    fresh = cache_path.exists() and (time.time() - cache_path.stat().st_mtime) < max_age_days * 86400
    if online and not fresh:
        try:
            text = _download()
            if "GENE SYMBOL" in text:
                cache_path.parent.mkdir(parents=True, exist_ok=True)
                cache_path.write_text(text, encoding="utf-8")
        except (urllib.error.URLError, OSError):
            pass    # 古いキャッシュがあればそれを使う
    if not cache_path.exists():
        return None
    return parse_csv(cache_path.read_text(encoding="utf-8"))


def moi_label(moi: str, lang: str) -> str:
    ja, en = MOI_LABELS.get(moi, (moi, moi))
    return ja if lang == "ja" else en
