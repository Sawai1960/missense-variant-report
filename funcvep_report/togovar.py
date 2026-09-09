"""TogoVar（NBDC/DBCLS）の公開 API から日本人集団のアレル頻度を取る。

TogoVar は東北メディカル・メガバンク機構の 54KJPN（約 54,000 人の全ゲノム）、
NCBN（ナショナルセンター・バイオバンクネットワーク）、GEM-J WGA、JGA の
各データセットの頻度を変異ごとに集約して公開している。ここではその REST API
（GET /api/search/variant?term=chrom:pos-pos）を叩き、座標と塩基が一致する
1 件を取り出して、日本人集団のデータセットだけを抜き出す。

送るのは変異のゲノム座標だけで、患者情報は含まない。

  found   日本人集団のいずれかに記録がある
  absent  TogoVar に変異が無い、または日本人集団のデータセットに記録が無い
  error   取得できなかった
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field

API_URL = "https://grch38.togovar.org/api/search/variant"
USER_AGENT = "funcvep-report/0.1"

# 日本人集団のデータセット。表示順もこの順（規模の大きいものから）
JAPANESE_SOURCES = ("tommo", "ncbn", "gem_j_wga", "jga_wgs", "jga_wes", "jga_snp")
# 一般集団の参照として使うのは ToMMo 54KJPN（健常者中心の住民コホート）だけ。
# NCBN は国立高度専門医療研究センターの患者由来バイオバンク、JGA は研究データ、
# GEM-J WGA は複数コホートの寄せ集めで、いずれも疾患群の偏りがありうる
REFERENCE_SOURCES = ("tommo",)
SOURCE_LABELS = {
    "tommo": "ToMMo 54KJPN",
    "ncbn": "NCBN",
    "gem_j_wga": "GEM-J WGA",
    "jga_wgs": "JGA-WGS",
    "jga_wes": "JGA-WES",
    "jga_snp": "JGA-SNP",
}


@dataclass
class SourceFreq:
    source: str
    ac: int
    an: int
    hom: int | None = None      # ホモ接合体数。データセットによっては無い
    filters: list[str] = field(default_factory=list)

    @property
    def af(self) -> float:
        return self.ac / self.an if self.an else 0.0

    @property
    def label(self) -> str:
        return SOURCE_LABELS.get(self.source, self.source)

    @property
    def is_reference(self) -> bool:
        return self.source in REFERENCE_SOURCES


@dataclass
class JapanResult:
    status: str                         # found / absent / error
    sources: list[SourceFreq] = field(default_factory=list)
    reason: str = ""

    @property
    def primary(self) -> SourceFreq | None:
        """規模の大きい順で最初に見つかったデータセット。"""
        return self.sources[0] if self.sources else None

    @property
    def max_af(self) -> float | None:
        return max((s.af for s in self.sources), default=None)

    @property
    def reference(self) -> list[SourceFreq]:
        return [s for s in self.sources if s.is_reference]

    @property
    def supplementary(self) -> list[SourceFreq]:
        return [s for s in self.sources if not s.is_reference]


def parse_search_payload(payload: dict, chrom: str, pos: int, ref: str, alt: str) -> JapanResult:
    """検索応答から、座標と塩基が一致する 1 件を選び、日本人集団の頻度を取り出す。"""
    data = payload.get("data") or []
    hit = None
    for v in data:
        if (str(v.get("chromosome")) == str(chrom) and v.get("position") == pos
                and v.get("reference") == ref and v.get("alternate") == alt):
            hit = v
            break
    if hit is None:
        return JapanResult(status="absent")
    by_source: dict[str, SourceFreq] = {}
    for f in hit.get("frequencies") or []:
        src = f.get("source")
        if src not in JAPANESE_SOURCES:
            continue
        ac, an = int(f.get("ac") or 0), int(f.get("an") or 0)
        if an == 0 or ac == 0:
            continue
        hom = f.get("aac")      # 変異アレルのホモ接合の遺伝型数
        by_source[src] = SourceFreq(source=src, ac=ac, an=an,
                                    hom=int(hom) if hom is not None else None,
                                    filters=list(f.get("filter") or []))
    ordered = [by_source[s] for s in JAPANESE_SOURCES if s in by_source]
    if not ordered:
        return JapanResult(status="absent")
    return JapanResult(status="found", sources=ordered)


def _get(url: str, timeout: float) -> dict:
    req = urllib.request.Request(
        url, headers={"Accept": "application/json", "User-Agent": USER_AGENT}
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def lookup(chrom: str, pos: int, ref: str, alt: str, timeout: float = 20.0) -> JapanResult:
    """1 変異を照会する。ネットワークの失敗は例外にせず status="error" で返す。"""
    url = f"{API_URL}?{urllib.parse.urlencode({'term': f'{chrom}:{pos}-{pos}'})}"
    try:
        try:
            payload = _get(url, timeout)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            if isinstance(exc, urllib.error.HTTPError):
                raise
            payload = _get(url, timeout * 2)    # 時間切れは一度だけやり直す
        return parse_search_payload(payload, chrom, pos, ref, alt)
    except urllib.error.HTTPError as exc:
        return JapanResult(status="error", reason=f"HTTP {exc.code}")
    except (urllib.error.URLError, OSError, ValueError) as exc:
        return JapanResult(status="error", reason=str(getattr(exc, "reason", exc)))
