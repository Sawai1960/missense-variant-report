"""ClinVar の API から、この変異の疾患ごとの登録内容を取る。

手元の ClinVar 索引にある「表現型」欄は、各提出者が付けた疾患名を縦棒でつないだ
だけで、どの疾患名が何件の提出に支えられているかが分からない。NCBI の E-utilities
（efetch, rettype=vcv）で VariationID を照会すると、疾患（RCV）ごとに判定・提出件数・
レビュー段階が返るので、それを疾患ごとの表にする。

疾患名は各提出者が登録したもので、ClinVar が正しさを検証したものではない。検査の
依頼理由（遺伝子パネルの対象疾患）がそのまま登録されることもある。件数の少ない
疾患名はその可能性が高い。報告書ではこの注意を添える。

送るのは ClinVar の VariationID だけで、患者情報は含まない。
"""

from __future__ import annotations

import re
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

EFETCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?db=clinvar&rettype=vcv&from_esearch=true&id={vid}"
USER_AGENT = "funcvep-report/0.1"

# 疾患名ではない登録（総称）。表示と照合から除く
_GENERIC = {"not provided", "not specified", "see cases", "inborn genetic diseases", "-", ""}


def is_generic_condition(name: str | None) -> bool:
    low = (name or "").strip().lower()
    return (low in _GENERIC or "-related" in low or ";" in low
            or re.fullmatch(r"\d+ conditions", low) is not None)


@dataclass
class ConditionRow:
    condition: str
    classification: str
    submissions: int
    review_status: str
    date: str = ""

    @property
    def generic(self) -> bool:
        return is_generic_condition(self.condition)


@dataclass
class ConditionResult:
    status: str                             # found / absent / error
    rows: list[ConditionRow] = field(default_factory=list)
    reason: str = ""

    @property
    def specific(self) -> list[ConditionRow]:
        """疾患名のある行だけ、提出件数の多い順。"""
        return sorted((r for r in self.rows if not r.generic), key=lambda r: -r.submissions)

    @property
    def top_condition(self) -> str | None:
        rows = self.specific
        return rows[0].condition if rows else None


def parse_vcv_xml(xml_text: str) -> ConditionResult:
    """VCV の XML から疾患ごとの行を取り出す。RCV が無ければ absent。"""
    root = ET.fromstring(xml_text)
    rows: list[ConditionRow] = []
    for rcv in root.iter("RCVAccession"):
        conds = [(c.text or "").strip() for c in rcv.iter("ClassifiedCondition")]
        g = rcv.find("./RCVClassifications/GermlineClassification")
        if g is None:
            continue
        d = g.find("Description")
        if d is None:
            continue
        rows.append(ConditionRow(
            condition="; ".join(c for c in conds if c),
            classification=(d.text or "").strip(),
            submissions=int(d.get("SubmissionCount") or 0),
            review_status=(g.findtext("ReviewStatus") or "").strip(),
            date=d.get("DateLastEvaluated") or "",
        ))
    if not rows:
        return ConditionResult(status="absent")
    rows.sort(key=lambda r: -r.submissions)
    return ConditionResult(status="found", rows=rows)


def _get(url: str, timeout: float) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8")


def lookup(variation_id: str | int, timeout: float = 30.0) -> ConditionResult:
    """VariationID で照会する。ネットワークの失敗は例外にせず status="error" で返す。"""
    vid = str(variation_id).strip()
    if not vid.isdigit():
        return ConditionResult(status="absent")
    url = EFETCH_URL.format(vid=urllib.parse.quote(vid))
    try:
        try:
            text = _get(url, timeout)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            if isinstance(exc, urllib.error.HTTPError):
                raise
            text = _get(url, timeout * 2)
        return parse_vcv_xml(text)
    except urllib.error.HTTPError as exc:
        return ConditionResult(status="error", reason=f"HTTP {exc.code}")
    except (urllib.error.URLError, OSError, ValueError, ET.ParseError) as exc:
        return ConditionResult(status="error", reason=str(getattr(exc, "reason", exc)))
