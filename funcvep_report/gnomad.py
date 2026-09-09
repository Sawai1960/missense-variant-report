"""gnomAD の公開 API（GraphQL）からアレル頻度を取る。

送るのは変異のゲノム座標（染色体・位置・塩基）だけで、患者情報は含まない。
データのダウンロードは要らず、インターネット接続があれば動く。

結果は 3 通りに分かれ、報告書ではそれぞれ書き分ける。
  found   記録あり。頻度とホモ接合体数を表示し、BA1/BS1/BS2 の材料にする
  absent  記録なし。約 80 万人で観察されなかったという情報で、PM2_supporting
          の候補。ただし読み取り深度が低い位置では根拠にしない
  error   取得できなかった（オフライン、API の不調）。手入力を案内する

エクソームとゲノムの両方に記録がある変異は、アレル数を合算して頻度を出す。
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass, field

API_URL = "https://gnomad.broadinstitute.org/api"
DATASET = "gnomad_r4"
USER_AGENT = "funcvep-report/0.1"
# 20 リード以上で読めている割合がこれ未満なら「読み取り不十分」とみなす
WELL_COVERED_FRACTION = 0.9

_VARIANT_QUERY = """
query($id: String!, $ds: DatasetId!) {
  variant(variantId: $id, dataset: $ds) {
    variant_id
    rsids
    exome  { ac an af homozygote_count filters populations { id ac an homozygote_count } }
    genome { ac an af homozygote_count filters populations { id ac an homozygote_count } }
    coverage { exome { mean over_20 } genome { mean over_20 } }
  }
}"""

_COVERAGE_QUERY = """
query($chrom: String!, $pos: Int!, $ds: DatasetId!) {
  region(chrom: $chrom, start: $pos, stop: $pos, reference_genome: GRCh38) {
    coverage(dataset: $ds) {
      exome  { pos mean over_20 }
      genome { pos mean over_20 }
    }
  }
}"""


@dataclass
class GnomadResult:
    status: str                      # found / absent / error
    af: float | None = None
    ac: int | None = None
    an: int | None = None
    hom: int | None = None
    filters: list[str] = field(default_factory=list)
    depth_mean: float | None = None  # その位置の平均読み取り深度（exome/genome の良い方）
    over_20: float | None = None     # 20 リード以上で読めている割合（同上）
    eas_ac: int | None = None        # 東アジア集団（exome と genome の合算）
    eas_an: int | None = None
    eas_hom: int | None = None
    rsids: list[str] = field(default_factory=list)
    reason: str = ""                 # error のときの理由

    @property
    def well_covered(self) -> bool | None:
        """読み取りが十分か。深度情報が無ければ None。"""
        if self.over_20 is None:
            return None
        return self.over_20 >= WELL_COVERED_FRACTION

    @property
    def eas_af(self) -> float | None:
        if not self.eas_an:
            return None
        return (self.eas_ac or 0) / self.eas_an


def _sum_populations(exome: dict | None, genome: dict | None) -> tuple[int, int, int, list[str]]:
    ac = an = hom = 0
    filters: list[str] = []
    for part in (exome, genome):
        if not part:
            continue
        ac += int(part.get("ac") or 0)
        an += int(part.get("an") or 0)
        hom += int(part.get("homozygote_count") or 0)
        for f in part.get("filters") or []:
            if f not in filters:
                filters.append(f)
    return ac, an, hom, filters


def _sum_subpopulation(exome: dict | None, genome: dict | None, pop_id: str) -> tuple[int, int, int] | None:
    """指定した集団（eas など）のアレル数を exome と genome で合算する。無ければ None。"""
    ac = an = hom = 0
    seen = False
    for part in (exome, genome):
        for p in (part or {}).get("populations") or []:
            if p.get("id") == pop_id:
                seen = True
                ac += int(p.get("ac") or 0)
                an += int(p.get("an") or 0)
                hom += int(p.get("homozygote_count") or 0)
    return (ac, an, hom) if seen else None


def _best_coverage(cov: dict | None) -> tuple[float | None, float | None]:
    """exome と genome のうち、読めている割合が高い方を採る。"""
    best: tuple[float | None, float | None] = (None, None)
    if not isinstance(cov, dict):
        return best
    for part in cov.values():
        if not part:
            continue
        mean, over = part.get("mean"), part.get("over_20")
        if over is None:
            continue
        if best[1] is None or over > best[1]:
            best = (mean, over)
    return best


def parse_variant_payload(payload: dict) -> GnomadResult:
    """variant クエリの応答（JSON を dict にしたもの）を結果に変換する。

    記録が無い変異は errors に "Variant not found" が入り data.variant が null になる。
    """
    errors = payload.get("errors") or []
    variant = (payload.get("data") or {}).get("variant")
    if variant is None:
        if any("not found" in (e.get("message") or "").lower() for e in errors):
            return GnomadResult(status="absent")
        msg = "; ".join(e.get("message", "") for e in errors) or "empty response"
        return GnomadResult(status="error", reason=msg)

    ac, an, hom, filters = _sum_populations(variant.get("exome"), variant.get("genome"))
    depth, over = _best_coverage(variant.get("coverage"))
    if an == 0 or ac == 0:
        # 行はあるがアレルが数えられていない。品質フィルタ（AC0 など）で落ちた
        # 観察は「観察されず」と同じ扱いにする。gnomAD のサイトも同じ見せ方をする
        return GnomadResult(status="absent", filters=filters, depth_mean=depth, over_20=over)
    result = GnomadResult(status="found", af=ac / an, ac=ac, an=an, hom=hom,
                          filters=filters, depth_mean=depth, over_20=over)
    eas = _sum_subpopulation(variant.get("exome"), variant.get("genome"), "eas")
    if eas:
        result.eas_ac, result.eas_an, result.eas_hom = eas
    result.rsids = list(variant.get("rsids") or [])
    return result


def parse_coverage_payload(payload: dict, pos: int) -> tuple[float | None, float | None]:
    """region クエリの応答から、指定位置の深度を取り出す。"""
    region = (payload.get("data") or {}).get("region") or {}
    cov = region.get("coverage") or {}
    picked: dict[str, dict] = {}
    for key in ("exome", "genome"):
        for entry in cov.get(key) or []:
            if entry.get("pos") == pos:
                picked[key] = entry
    return _best_coverage(picked)


def _post(query: str, variables: dict, timeout: float) -> dict:
    body = json.dumps({"query": query, "variables": variables}).encode()
    req = urllib.request.Request(
        API_URL, data=body,
        headers={"Content-Type": "application/json", "User-Agent": USER_AGENT},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _post_with_retry(query: str, variables: dict, timeout: float) -> dict:
    """最初の応答が遅いことがある（API 側の起動待ち）ので、時間切れは一度だけやり直す。"""
    try:
        return _post(query, variables, timeout)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        if isinstance(exc, urllib.error.HTTPError):
            raise
        return _post(query, variables, timeout * 2)


def lookup(chrom: str, pos: int, ref: str, alt: str, timeout: float = 15.0) -> GnomadResult:
    """1 変異を照会する。ネットワークの失敗は例外にせず status="error" で返す。"""
    variant_id = f"{chrom}-{pos}-{ref}-{alt}"
    try:
        result = parse_variant_payload(
            _post_with_retry(_VARIANT_QUERY, {"id": variant_id, "ds": DATASET}, timeout)
        )
        if result.status == "absent" and result.over_20 is None:
            # 記録が無いときは、その位置がそもそも読めているかを別に聞く
            try:
                depth, over = parse_coverage_payload(
                    _post(_COVERAGE_QUERY, {"chrom": chrom, "pos": pos, "ds": DATASET}, timeout),
                    pos,
                )
                result.depth_mean, result.over_20 = depth, over
            except (urllib.error.URLError, OSError, ValueError):
                pass  # 深度が取れなくても「記録なし」自体は伝える
        return result
    except urllib.error.HTTPError as exc:
        return GnomadResult(status="error", reason=f"HTTP {exc.code}")
    except (urllib.error.URLError, OSError, ValueError) as exc:
        return GnomadResult(status="error", reason=str(getattr(exc, "reason", exc)))
