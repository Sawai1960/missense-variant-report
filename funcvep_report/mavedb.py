"""MaveDB の機能実験の実測値を引く。

MaveDB は大規模機能実験（MAVE: multiplexed assays of variant effect）のスコアを
公開している。FuncVEP は「予測」だが、こちらは「実験結果」で、ACMG の PS3/BS3
（機能実験による証拠）の材料になる。ただし実験のある遺伝子は限られる。

流れ:
  1. 遺伝子名で score set を検索（API、遺伝子ごとに 30 日キャッシュ）
  2. 各 score set の詳細（研究者が定めた正常／異常のスコア範囲）を取得
  3. スコア表（CSV）を取得して hgvs_pro が一致する行を探す

スコアの尺度はデータセットごとに違う。範囲情報があれば「正常」「異常」などの
区分に変換して示し、無ければ生の値だけを示す。

注意: 対象配列が全長でない（ドメイン断片など）データセットでは残基番号の付け方が
違うことがある。targetAccession が RefSeq の転写産物を指すものは全長基準とみなし、
それ以外は「番号の基準が未確認」と添える。
"""

from __future__ import annotations

import csv
import io
import json
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path


API_ROOT = "https://api.mavedb.org/api/v1"
USER_AGENT = "funcvep-report/0.1"
SEARCH_MAX_AGE_DAYS = 30


@dataclass
class FunctionalClass:
    label: str
    classification: str          # normal / abnormal / not_specified
    lo: float | None
    hi: float | None
    incl_lo: bool = True
    incl_hi: bool = False

    def contains(self, x: float) -> bool:
        if self.lo is not None and (x < self.lo or (x == self.lo and not self.incl_lo)):
            return False
        if self.hi is not None and (x > self.hi or (x == self.hi and not self.incl_hi)):
            return False
        return True


@dataclass
class ScoreSet:
    urn: str
    title: str
    short_description: str = ""
    published: str = ""
    num_variants: int | None = None
    target_accession: str | None = None
    pmid: str | None = None
    citation: str = ""               # 第一著者 (年) 誌名 の短い形
    classes: list[FunctionalClass] = field(default_factory=list)
    calibration_title: str = ""

    @property
    def url(self) -> str:
        return f"https://www.mavedb.org/score-sets/{self.urn}"

    @property
    def full_length_numbering(self) -> bool:
        acc = self.target_accession or ""
        return acc.startswith(("NM_", "NP_", "ENST", "ENSP"))

    def classify(self, score: float) -> FunctionalClass | None:
        for c in self.classes:
            if c.contains(score):
                return c
        return None


@dataclass
class MaveHit:
    score_set: ScoreSet
    hgvs_pro: str
    score: float
    functional_class: FunctionalClass | None
    match: str = "aa"                 # "nt"（塩基が一致）または "aa"（アミノ酸置換のみ一致）
    nt_accession: str | None = None   # 実験側の転写産物番号（塩基照合のとき）


@dataclass
class MaveResult:
    status: str                       # found / no_match / no_dataset / error
    n_score_sets: int = 0
    hits: list[MaveHit] = field(default_factory=list)
    reason: str = ""


# -------------------------------------------------------------- 応答の読み取り

def parse_score_set(d: dict) -> ScoreSet:
    tg = d.get("targetGenes") or []
    acc = None
    if tg:
        ta = tg[0].get("targetAccession") or {}
        acc = ta.get("accession")
    pub = (d.get("primaryPublicationIdentifiers") or [{}])[0]
    pmid = pub.get("identifier") if pub.get("dbName") == "PubMed" else None
    authors = pub.get("authors") or []
    first = (authors[0].get("name") or "").split(",")[0] if authors else ""
    year = (pub.get("publicationYear") or pub.get("publicationDate") or "")
    citation = " ".join(x for x in (first, f"({year})" if year else "", pub.get("publicationJournal") or "") if x)
    ss = ScoreSet(
        urn=d.get("urn", ""), title=d.get("title") or "", short_description=d.get("shortDescription") or "",
        published=(d.get("publishedDate") or "")[:10], num_variants=d.get("numVariants"),
        target_accession=acc, pmid=pmid, citation=citation,
    )
    cals = d.get("scoreCalibrations") or []
    if cals:
        cal = cals[0]
        ss.calibration_title = cal.get("title") or ""
        for fc in cal.get("functionalClassifications") or []:
            rng = fc.get("range") or [None, None]
            ss.classes.append(FunctionalClass(
                label=fc.get("label") or fc.get("functionalClassification") or "",
                classification=fc.get("functionalClassification") or "not_specified",
                lo=rng[0], hi=rng[1],
                incl_lo=bool(fc.get("inclusiveLowerBound", True)),
                incl_hi=bool(fc.get("inclusiveUpperBound", False)),
            ))
    return ss


def single_gene_sets(search_payload: dict, gene: str) -> list[dict]:
    """検索結果のうち、対象遺伝子がその 1 つだけの score set。多遺伝子の寄せ集めは除く。"""
    out = []
    for ss in search_payload.get("scoreSets") or []:
        names = {(g.get("name") or g.get("mappedHgncName") or "") for g in (ss.get("targetGenes") or [])}
        if names == {gene}:
            out.append(ss)
    return out


_NT_RE = re.compile(r"^(?:(?P<acc>[A-Z]{2}_\d+)(?:\.(?P<ver>\d+))?:)?c\.(?P<pos>\d+)(?P<ref>[ACGT])>(?P<alt>[ACGT])$")


def find_in_scores(csv_text: str, hgvs_pro: str,
                   cds_change: tuple[int, str, str] | None = None,
                   refseq_base: str | None = None) -> tuple[float, str, str | None] | None:
    """スコア表から、この変異の行を探す。

    返り値は (スコア, 照合の種類, 実験側の転写産物番号)。照合の種類は
      "nt"  塩基表記（hgvs_nt）が、評価対象の変異の c. 表記と位置・塩基とも一致
      "aa"  アミノ酸表記（hgvs_pro）が一致（塩基は不明）
    塩基単位の実験（SGE など）では塩基の違いが結果に影響しうるので、塩基の一致を優先し、
    塩基表記のある行はアミノ酸だけでは照合しない（レビュー対応 6）。
    転写産物番号の版だけが違う行は塩基照合の対象にし、別の転写産物なら照合しない。
    """
    rows = list(csv.DictReader(io.StringIO(csv_text)))

    def score_of(r: dict) -> float | None:
        try:
            return float(r.get("score"))
        except (TypeError, ValueError):
            return None

    if cds_change:
        pos, ref, alt = cds_change
        for r in rows:
            m = _NT_RE.match((r.get("hgvs_nt") or "").strip())
            if not m:
                continue
            acc = m.group("acc")
            if acc and refseq_base and acc.split(".")[0] != refseq_base.split(".")[0]:
                continue
            if int(m.group("pos")) == pos and m.group("ref") == ref and m.group("alt") == alt:
                sc = score_of(r)
                if sc is not None:
                    return sc, "nt", (r.get("hgvs_nt") or "").split(":")[0] if acc else None
    for r in rows:
        if r.get("hgvs_pro") == hgvs_pro:
            nt = (r.get("hgvs_nt") or "").strip()
            if nt and nt not in ("NA", "-") and _NT_RE.match(nt):
                continue    # 塩基表記のある行は塩基で照合すべきなので、アミノ酸では拾わない
            sc = score_of(r)
            if sc is not None:
                return sc, "aa", None
    return None


# -------------------------------------------------------------- 通信とキャッシュ

def _get_text(url: str, timeout: float) -> str:
    req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8")


def _post_json(url: str, body: dict, timeout: float) -> dict:
    req = urllib.request.Request(
        url, data=json.dumps(body).encode(),
        headers={"Accept": "application/json", "Content-Type": "application/json", "User-Agent": USER_AGENT},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _cached_text(path: Path, fetch, max_age_days: int | None, online: bool) -> str | None:
    fresh = path.exists() and (max_age_days is None or
                               (time.time() - path.stat().st_mtime) < max_age_days * 86400)
    if fresh:
        return path.read_text(encoding="utf-8")
    if not online:
        return path.read_text(encoding="utf-8") if path.exists() else None
    text = fetch()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return text


def lookup(gene: str, hgvs_pro: str, cache_dir: Path, online: bool = True,
           timeout: float = 60.0, cds_change: tuple[int, str, str] | None = None,
           refseq_base: str | None = None) -> MaveResult:
    """遺伝子の score set を集め、この置換の実測値を探す。

    cds_change（c. の位置と塩基）と refseq_base（転写産物番号、版なし）を渡すと、
    塩基表記しか持たないデータセットも塩基で照合できる。
    """
    safe_gene = "".join(ch for ch in gene if ch.isalnum() or ch in "-_")
    try:
        search_text = _cached_text(
            cache_dir / "mavedb" / f"search_{safe_gene}.json",
            lambda: json.dumps(_post_json(f"{API_ROOT}/score-sets/search", {"targets": [gene]}, timeout)),
            SEARCH_MAX_AGE_DAYS, online,
        )
        if search_text is None:
            return MaveResult(status="error", reason="offline")
        sets = single_gene_sets(json.loads(search_text), gene)
        if not sets:
            return MaveResult(status="no_dataset")
        hits: list[MaveHit] = []
        for raw in sets:
            urn = raw["urn"]
            safe_urn = urn.replace(":", "_")
            detail_text = _cached_text(
                cache_dir / "mavedb" / f"{safe_urn}.json",
                lambda u=urn: _get_text(f"{API_ROOT}/score-sets/{u}", timeout), None, online)
            scores_text = _cached_text(
                cache_dir / "mavedb" / f"{safe_urn}.scores.csv",
                lambda u=urn: _get_text(f"{API_ROOT}/score-sets/{u}/scores", timeout), None, online)
            if detail_text is None or scores_text is None:
                continue
            ss = parse_score_set(json.loads(detail_text))
            found = find_in_scores(scores_text, hgvs_pro, cds_change, refseq_base)
            if found is None:
                continue
            score, kind, acc = found
            hits.append(MaveHit(score_set=ss, hgvs_pro=hgvs_pro, score=score,
                                functional_class=ss.classify(score), match=kind, nt_accession=acc))
        hits.sort(key=lambda h: h.score_set.published, reverse=True)
        return MaveResult(status="found" if hits else "no_match", n_score_sets=len(sets), hits=hits)
    except urllib.error.HTTPError as exc:
        return MaveResult(status="error", reason=f"HTTP {exc.code}")
    except (urllib.error.URLError, OSError, ValueError, KeyError) as exc:
        return MaveResult(status="error", reason=str(getattr(exc, "reason", exc)))
