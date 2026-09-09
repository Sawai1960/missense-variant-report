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

from .variant import AA1_TO_3, ParseError, apply_cds_substitution

API_ROOT = "https://api.mavedb.org/api/v1"
_CDNA_SNV = re.compile(r"c\.(\d+)([ACGT])>([ACGT])$")
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


def _protein_change_from_nt(hgvs_nt: str | None, cds: str) -> str | None:
    """c. 表記の 1 塩基置換を、手元の CDS で翻訳して p. 表記にする。

    SGE などのデータセットは hgvs_pro 欄が空で、c. 表記しか持たないことがある。
    参照塩基が CDS と合わない行（転写産物の版の違いなど）は None。
    """
    if not hgvs_nt:
        return None
    m = _CDNA_SNV.search(hgvs_nt)
    if not m:
        return None
    try:
        aa_ref, pos, aa_alt = apply_cds_substitution(cds, int(m.group(1)), m.group(2), m.group(3))
    except ParseError:
        return None
    if aa_ref == aa_alt or aa_alt not in AA1_TO_3 or aa_ref not in AA1_TO_3:
        return None
    return f"p.{AA1_TO_3[aa_ref]}{pos}{AA1_TO_3[aa_alt]}"


def find_in_scores(csv_text: str, hgvs_pro: str, cds: str | None = None) -> float | None:
    """スコア表から、この置換の行を探す。

    hgvs_pro が一致する行を優先する。無ければ、cds が与えられている場合に限り
    hgvs_nt（c. 表記の 1 塩基置換）を翻訳して照合する。
    """
    rows = list(csv.DictReader(io.StringIO(csv_text)))

    def score_of(r: dict) -> float | None:
        try:
            return float(r.get("score"))
        except (TypeError, ValueError):
            return None

    for r in rows:
        if r.get("hgvs_pro") == hgvs_pro:
            return score_of(r)
    if cds:
        for r in rows:
            if r.get("hgvs_pro") in (None, "", "NA") and \
                    _protein_change_from_nt(r.get("hgvs_nt"), cds) == hgvs_pro:
                return score_of(r)
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
           timeout: float = 60.0, cds: str | None = None) -> MaveResult:
    """遺伝子の score set を集め、この置換の実測値を探す。

    cds を渡すと、hgvs_pro を持たないデータセット（c. 表記のみ）も照合できる。
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
            score = find_in_scores(scores_text, hgvs_pro, cds)
            if score is None:
                continue
            hits.append(MaveHit(score_set=ss, hgvs_pro=hgvs_pro, score=score,
                                functional_class=ss.classify(score)))
        hits.sort(key=lambda h: h.score_set.published, reverse=True)
        return MaveResult(status="found" if hits else "no_match", n_score_sets=len(sets), hits=hits)
    except urllib.error.HTTPError as exc:
        return MaveResult(status="error", reason=f"HTTP {exc.code}")
    except (urllib.error.URLError, OSError, ValueError, KeyError) as exc:
        return MaveResult(status="error", reason=str(getattr(exc, "reason", exc)))
