"""LitVar2（NCBI）で、この変異に言及した論文を探す。

LitVar2 は PubMed / PMC の全文から変異の記載を抽出して rsID 単位にまとめている。
ここでは「遺伝子 + 1 文字表記の置換」（例 BRCA1 R1699W）または rsID で変異を
特定し、PMID の一覧を取り、上位数件の書誌を PubMed の esummary で補う。
画面だけに出し、報告書（PDF）には載せない。
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field

AUTOCOMPLETE_URL = "https://www.ncbi.nlm.nih.gov/research/litvar2-api/variant/autocomplete/?query={q}"
PUBLICATIONS_URL = "https://www.ncbi.nlm.nih.gov/research/litvar2-api/variant/get/{vid}/publications"
ESUMMARY_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi?db=pubmed&retmode=json&id={ids}"
USER_AGENT = "funcvep-report/0.1"


@dataclass
class Paper:
    pmid: int
    title: str
    year: str
    journal: str
    first_author: str

    @property
    def url(self) -> str:
        return f"https://pubmed.ncbi.nlm.nih.gov/{self.pmid}/"


@dataclass
class LitResult:
    status: str                       # found / none / error
    variant_id: str | None = None
    rsid: str | None = None
    count: int = 0
    papers: list[Paper] = field(default_factory=list)
    reason: str = ""

    @property
    def url(self) -> str | None:
        if not self.rsid:
            return None
        return f"https://www.ncbi.nlm.nih.gov/research/litvar2/docsum?variant=litvar%40{self.rsid}%23%23"


def pick_variant(items: list[dict], gene: str, pv1: str, rsids: list[str]) -> dict | None:
    """候補から、遺伝子が合い、rsID か p. 表記が一致するものを選ぶ。"""
    want_name = f"p.{pv1}".lower()
    for it in items:
        genes = [g.upper() for g in (it.get("gene") or [])]
        if gene.upper() not in genes:
            continue
        if it.get("rsid") in rsids:
            return it
        if (it.get("name") or "").lower() == want_name or (it.get("hgvs") or "").lower() == want_name:
            return it
    return None


def _get_json(url: str, timeout: float):
    req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _summaries(pmids: list[int], timeout: float) -> list[Paper]:
    if not pmids:
        return []
    d = _get_json(ESUMMARY_URL.format(ids=",".join(str(p) for p in pmids)), timeout)
    res = d.get("result") or {}
    out = []
    for uid in res.get("uids") or []:
        r = res.get(uid) or {}
        authors = r.get("authors") or []
        year = re.match(r"\d{4}", r.get("pubdate") or "")
        out.append(Paper(pmid=int(uid), title=r.get("title") or "", year=year.group(0) if year else "",
                         journal=r.get("source") or "", first_author=(authors[0].get("name") if authors else "")))
    return out


def lookup(gene: str, pv1: str, rsids: list[str] | None = None, n_papers: int = 10,
           timeout: float = 30.0) -> LitResult:
    """変異を特定して PMID を集める。失敗は status="error"。"""
    rsids = rsids or []
    try:
        items = []
        for q in ([f"{gene} {pv1}"] + rsids):
            items += _get_json(AUTOCOMPLETE_URL.format(q=urllib.parse.quote(q)), timeout) or []
        hit = pick_variant(items, gene, pv1, rsids)
        if hit is None:
            return LitResult(status="none")
        vid = hit["_id"]
        pubs = _get_json(PUBLICATIONS_URL.format(vid=urllib.parse.quote(vid, safe="")), timeout) or {}
        pmids = [int(p) for p in (pubs.get("pmids") or [])]
        count = int(pubs.get("pmids_count") or len(pmids))
        # LitVar は新しい順に返すので先頭から取る
        papers = _summaries(pmids[:n_papers], timeout)
        return LitResult(status="found" if count else "none", variant_id=vid, rsid=hit.get("rsid"),
                         count=count, papers=papers)
    except urllib.error.HTTPError as exc:
        return LitResult(status="error", reason=f"HTTP {exc.code}")
    except (urllib.error.URLError, OSError, ValueError, KeyError) as exc:
        return LitResult(status="error", reason=str(getattr(exc, "reason", exc)))
