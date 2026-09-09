"""SpliceAI のスコアを Ensembl VEP の REST API から取る。

ミスセンスに見える塩基置換の一部は、アミノ酸を変えるだけでなくスプライシングを
壊す。FuncVEP はタンパク質の置換を前提に予測するので、その場合は予測の前提が
崩れる。SpliceAI（Jaganathan ら 2019, Cell）は塩基置換がスプライス部位を
新設・消失させる確率（Δ スコア、0〜1）を 4 種類出す。

  DS_AG アクセプター獲得   DS_AL アクセプター喪失
  DS_DG ドナー獲得         DS_DL ドナー喪失
  DP_*  それぞれの位置（変異からの塩基数）

判定の目安（SpliceAI 論文）: 0.2 以上で感度重視、0.5 以上が推奨、0.8 以上で精度重視。

VEP の SpliceAI プラグインは事前計算済みのスコアを返す。送るのは座標と塩基だけ。
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass

API_URL = "https://rest.ensembl.org/vep/human/region/{chrom}:{pos}-{pos}:1/{alt}?SpliceAI=1"
USER_AGENT = "funcvep-report/0.1"

TYPES = ("AG", "AL", "DG", "DL")
LOW, RECOMMENDED = 0.2, 0.5


@dataclass
class SpliceResult:
    status: str                      # scored / no_score / error
    transcript: str | None = None
    ds: dict[str, float] | None = None   # {"AG": 0.01, ...}
    dp: dict[str, int] | None = None
    reason: str = ""

    @property
    def max_type(self) -> str | None:
        if not self.ds:
            return None
        return max(self.ds, key=lambda k: self.ds[k])

    @property
    def max_ds(self) -> float | None:
        if not self.ds:
            return None
        return self.ds[self.max_type]

    @property
    def level(self) -> str | None:
        """low / moderate / high。スコアが無ければ None。"""
        m = self.max_ds
        if m is None:
            return None
        if m >= RECOMMENDED:
            return "high"
        if m >= LOW:
            return "moderate"
        return "low"


def _pick(tcs: list[dict], enst: str | None, gene: str | None) -> dict | None:
    """MANE の転写産物を優先し、無ければ同じ遺伝子で最大スコアのものを採る。"""
    want = (enst or "").split(".")[0]
    with_scores = [tc for tc in tcs if tc.get("spliceai")]
    for tc in with_scores:
        if want and (tc.get("transcript_id") or "").split(".")[0] == want:
            return tc
    same_gene = [tc for tc in with_scores
                 if gene and (tc.get("gene_symbol") == gene or tc["spliceai"].get("SYMBOL") == gene)]
    pool = same_gene or with_scores
    if not pool:
        return None
    return max(pool, key=lambda tc: max(float(tc["spliceai"].get(f"DS_{k}") or 0) for k in TYPES))


def parse_vep_payload(payload, enst: str | None, gene: str | None) -> SpliceResult:
    if not payload or not isinstance(payload, list):
        return SpliceResult(status="no_score")
    tcs = payload[0].get("transcript_consequences") or []
    tc = _pick(tcs, enst, gene)
    if tc is None:
        return SpliceResult(status="no_score")
    sp = tc["spliceai"]
    ds = {k: float(sp.get(f"DS_{k}") or 0) for k in TYPES}
    dp = {k: int(sp.get(f"DP_{k}") or 0) for k in TYPES}
    return SpliceResult(status="scored", transcript=tc.get("transcript_id"), ds=ds, dp=dp)


def _get(url: str, timeout: float):
    req = urllib.request.Request(
        url, headers={"Accept": "application/json", "User-Agent": USER_AGENT}
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def lookup(chrom: str, pos: int, ref: str, alt: str, enst: str | None = None,
           gene: str | None = None, timeout: float = 30.0) -> SpliceResult:
    """1 変異を照会する。ネットワークの失敗は例外にせず status="error" で返す。"""
    url = API_URL.format(chrom=chrom, pos=pos, alt=alt)
    try:
        try:
            payload = _get(url, timeout)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            if isinstance(exc, urllib.error.HTTPError):
                raise
            payload = _get(url, timeout * 2)
        return parse_vep_payload(payload, enst, gene)
    except urllib.error.HTTPError as exc:
        return SpliceResult(status="error", reason=f"HTTP {exc.code}")
    except (urllib.error.URLError, OSError, ValueError) as exc:
        return SpliceResult(status="error", reason=str(getattr(exc, "reason", exc)))
