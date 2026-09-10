"""入力された変異を解決し、各データ源から証拠を集める。

処理の流れ:
    入力 → MANE で遺伝子・転写産物を確定
         → （HGVS c. の場合）CDS からアミノ酸変化を計算
         → AlphaMissense を橋渡しにアミノ酸変化をゲノム座標へ変換
         → 座標で FuncVEP・REVEL・ClinVar を引く

FuncVEP のスコア表は chr-pos-ref-alt でしか引けず、アミノ酸変化の情報を持たない。
そのため座標への変換が必須で、AlphaMissense がその役割を担う。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import duckdb

from .config import FUNCVEP_MODELS, MODELS, Config
from .i18n import join, t
from .variant import (
    AA1_TO_3,
    CodingInput,
    ParseError,
    ProteinInput,
    apply_cds_substitution,
    parse,
    translate_codon,
)


@dataclass(frozen=True)
class GenomicVariant:
    chrom: str
    pos: int
    ref: str
    alt: str

    @property
    def funcvep_id(self) -> str:
        return f"{self.chrom}-{self.pos}-{self.ref}-{self.alt}"

    def __str__(self) -> str:
        return f"chr{self.chrom}:{self.pos:,} {self.ref}>{self.alt}"


@dataclass
class Evidence:
    """1 つのゲノム変異について集めた証拠。欠けている項目は None のまま。"""

    funcvep: dict[str, float] = field(default_factory=dict)
    am_score: float | None = None
    am_class: str | None = None
    revel: float | None = None
    clinvar: dict | None = None
    # 予測表にその変異の行があったか。None は FuncVEP の索引自体が無い場合。
    in_funcvep_table: bool | None = None
    # 同じ残基の ClinVar 行（この変異自身も含む）。索引が無いときは None。
    same_residue: list[dict] | None = None
    # この変異を学習に使ったモデル名。学習セットの索引が無いときは None。
    train_models: list[str] | None = None

    @property
    def has_funcvep(self) -> bool:
        return bool(self.funcvep)

    @property
    def funcvep_status(self) -> str:
        """スコアが出ないとき、その理由を区別する。

        スコアが無い理由は 2 つあり、意味がまったく違う。
          scored  スコアがある
          blank   予測表に行はあるがスコアが空欄。学習に使われた変異で、
                  「予測できなかった」ではなく「出さない」の意味
          absent  予測表にその変異の行自体が無い。6 モデル全部の学習に
                  使われた場合に起きる（著者私信 2026-09-05）
          absent_unexplained
                  行が無いが、学習セットにも見当たらない。理由が未確定
          unknown FuncVEP の索引が無いので判定できない
        """
        if any(self.funcvep.get(m) is not None for m in FUNCVEP_MODELS):
            return "scored"
        if self.in_funcvep_table is None:
            return "unknown"
        if self.in_funcvep_table:
            return "blank"
        if self.train_models is None or self.train_models:
            return "absent"
        return "absent_unexplained"


@dataclass
class ResolvedVariant:
    gene: str
    ensg: str
    enst: str
    refseq_nuc: str
    aa_ref: str
    position: int
    aa_alt: str
    genomic: GenomicVariant
    evidence: Evidence

    @property
    def protein_variant(self) -> str:
        return f"{self.aa_ref}{self.position}{self.aa_alt}"

    @property
    def hgvs_p(self) -> str:
        return f"p.{self.aa_ref}{self.position}{self.aa_alt}"

    @property
    def hgvs_p3(self) -> str:
        """3 文字表記（p.Pro8Leu）。見出しや ClinVar との照合に使う。"""
        return f"p.{AA1_TO_3.get(self.aa_ref, self.aa_ref)}{self.position}{AA1_TO_3.get(self.aa_alt, self.aa_alt)}"


@dataclass
class Resolution:
    query: str
    variants: list[ResolvedVariant] = field(default_factory=list)
    gene: str | None = None
    ensg: str | None = None
    constraint: dict | None = None
    warnings: list[str] = field(default_factory=list)
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None and bool(self.variants)


class MissingIndex(RuntimeError):
    pass


# 予備経路（遺伝子の領域からの探索）で拾った転写産物を採用する条件。
# 同じ遺伝子でもアイソフォームが違えば残基番号がずれ、たまたま同じ残基番号に
# 同じアミノ酸が来ることがある。実測では COL18A1 p.Ala2Val がそれで、
# 50 kb 離れた別の座標を返していた。参照アミノ酸の照合では防げないので、
# 転写産物全体の一致率で判断する。
MIN_REGION_AGREEMENT = 0.95
MIN_REGION_COMPARED = 20


def _is_nan(x) -> bool:
    return isinstance(x, float) and x != x


def _clean(x) -> float | None:
    """欠測を一貫して None にする。NaN のまま持ち回ると表示や比較が崩れる。"""
    if x is None or _is_nan(x):
        return None
    return float(x)


class Store:
    """索引済み Parquet への問い合わせ口。"""

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.p = cfg.paths
        self._con: duckdb.DuckDBPyConnection | None = None
        # 予備経路での一致率の計算結果。同じ照会で何度も引かないため。
        self._mane_residues: dict[str, dict[int, str]] = {}
        self._agreement: dict[tuple[str, str], tuple[float, int]] = {}

    # -- 接続と可用性 ------------------------------------------------------
    @property
    def con(self) -> duckdb.DuckDBPyConnection:
        if self._con is None:
            self._con = duckdb.connect()
            self._con.execute("PRAGMA memory_limit='4GB'")
        return self._con

    @staticmethod
    def _ready(path: Path) -> bool:
        """索引として使える状態か。

        構築中のディレクトリは存在するだけで中身が空のことがある。
        存在の有無だけを見ると、まだ書き込み中のものを「あり」と誤認する。
        """
        if path.is_dir():
            return any(path.rglob("*.parquet"))
        return path.is_file() and path.stat().st_size > 0

    def availability(self) -> dict[str, bool]:
        return {
            "mane": self._ready(self.p.mane),
            "cds": self._ready(self.p.cds),
            "alphamissense": self._ready(self.p.alphamissense),
            "funcvep": self._ready(self.p.funcvep),
            "revel": self._ready(self.p.revel),
            "clinvar": self._ready(self.p.clinvar),
            "constraint": self._ready(self.p.gene_constraint),
        }

    def missing(self) -> list[str]:
        return [k for k, v in self.availability().items() if not v]

    def _glob(self, path: Path) -> str:
        return f"read_parquet('{path.as_posix()}/**/*.parquet')" if path.is_dir() \
            else f"read_parquet('{path.as_posix()}')"

    # -- MANE --------------------------------------------------------------
    def mane_by_gene(self, gene: str) -> list[dict]:
        rows = self.con.execute(
            f"SELECT * FROM {self._glob(self.p.mane)} WHERE upper(gene) = ? "
            "ORDER BY CASE WHEN mane_status LIKE '%Select%' THEN 0 ELSE 1 END",
            [gene.upper()],
        ).df().to_dict("records")
        return rows

    def mane_by_transcript(self, tx: str) -> list[dict]:
        base = tx.split(".")[0]
        col = "enst" if base.startswith("ENST") else "refseq_nuc_base"
        return self.con.execute(
            f"SELECT * FROM {self._glob(self.p.mane)} WHERE {col} = ?", [base]
        ).df().to_dict("records")

    def gene_suggestions(self, gene: str, limit: int = 8) -> list[str]:
        rows = self.con.execute(
            f"SELECT DISTINCT gene FROM {self._glob(self.p.mane)} "
            "WHERE gene LIKE ? ORDER BY gene LIMIT ?",
            [gene.upper()[:3] + "%", limit],
        ).fetchall()
        return [r[0] for r in rows]

    def am_transcript_for(self, ensg: str, mane_enst: str) -> dict | None:
        """AlphaMissense 側が使っている転写産物と、残基番号のずれ。

        AlphaMissense は古い GENCODE で作られており、MANE と ID が一致するのは
        約 7 割。対応表は座標経由で実測したものなので ID の世代差に強い。

        アイソフォームが違うと残基番号がずれる。一定のずれ幅で説明できる場合は
        offset を返し、説明できない場合は offset を None にする。
        番号がずれたまま照会すると別の残基のスコアを返してしまうため、
        ここを取り違えないことが重要になる。
        """
        if not self._ready(self.p.transcript_map):
            return None
        row = self.con.execute(
            f"SELECT am_enst, aa_agreement FROM {self._glob(self.p.transcript_map)} "
            "WHERE ensg = ? AND mane_enst = ?",
            [ensg, mane_enst],
        ).fetchone()
        if not row:
            return None
        am_enst, agreement = row[0], float(row[1] or 0.0)
        if agreement >= 0.95:
            return {"am_enst": am_enst, "offset": 0, "agreement": agreement}

        offset = None
        fit = self.p.index / "numbering_offsets.parquet"
        if self._ready(fit):
            f = self.con.execute(
                f"SELECT fit_offset, fit_agreement FROM {self._glob(fit)} "
                "WHERE mane_enst = ? AND am_enst = ?",
                [mane_enst, am_enst],
            ).fetchone()
            if f and float(f[1] or 0) >= 0.95:
                offset = int(f[0])
        return {"am_enst": am_enst, "offset": offset, "agreement": agreement}

    def numbering_note(self, ensg: str, mane_enst: str) -> str | None:
        """残基番号のずれが照会失敗の原因になっていそうなら、その説明文。"""
        info = self.am_transcript_for(ensg, mane_enst)
        if not info or info["agreement"] >= 0.95:
            return None
        if info["offset"] is None:
            return t("lk.numbering_note")
        return None

    def transcript_agreement(self, refseq_nuc: str, chrom: str,
                             am_enst: str) -> tuple[float, int]:
        """MANE の転写産物と AlphaMissense の転写産物で、残基番号の付き方が
        揃っているかを測る。返すのは (一致率, 比較できた残基数)。

        索引構築時に transcript_map へ記録しているものと同じ計算を、
        対応表に載っていない遺伝子について照会時に行う。
        """
        key = (refseq_nuc, am_enst)
        if key in self._agreement:
            return self._agreement[key]

        mane = self._mane_residues.get(refseq_nuc)
        if mane is None:
            mane = {}
            cds = self.cds_for(refseq_nuc)
            if cds:
                for i in range(0, len(cds) - 2, 3):
                    aa = translate_codon(cds[i:i + 3])
                    if aa == "*":
                        break
                    mane[i // 3 + 1] = aa
            self._mane_residues[refseq_nuc] = mane

        result = (0.0, 0)
        if mane and self._ready(self.p.alphamissense):
            rows = self.con.execute(
                f"""SELECT DISTINCT
                        CAST(regexp_extract(protein_variant,
                             '^[A-Z]([0-9]+)', 1) AS INTEGER) AS aa_pos,
                        regexp_extract(protein_variant, '^([A-Z])', 1) AS aa
                    FROM {self._glob(self.p.alphamissense)}
                    WHERE chrom = ? AND enst = ?""",
                [chrom, am_enst],
            ).fetchall()
            shared = [(p, a) for p, a in rows if p in mane]
            if shared:
                hit = sum(1 for p, a in shared if mane[p] == a)
                result = (hit / len(shared), len(shared))
        self._agreement[key] = result
        return result

    def cds_for(self, refseq_nuc: str) -> str | None:
        row = self.con.execute(
            f"SELECT cds FROM {self._glob(self.p.cds)} WHERE refseq_nuc_base = ?",
            [refseq_nuc.split(".")[0]],
        ).fetchone()
        return row[0] if row else None

    def constraint_for(self, ensg: str) -> dict | None:
        if not self._ready(self.p.gene_constraint):
            return None
        df = self.con.execute(
            f"SELECT * FROM {self._glob(self.p.gene_constraint)} WHERE ensg = ?",
            [ensg],
        ).df()
        return df.to_dict("records")[0] if len(df) else None

    # -- AlphaMissense（座標への橋渡し） ------------------------------------
    def am_by_protein(self, chrom: str, enst: str,
                      protein_variant: str) -> list[dict]:
        """染色体で絞ってから転写産物とアミノ酸変化で引く。

        chrom を条件に入れることでパーティションが 1 つに絞られ、
        さらに構築時に enst 順に並べてあるので行グループ単位で読み飛ばせる。
        """
        if not self._ready(self.p.alphamissense):
            raise MissingIndex("alphamissense")
        return self.con.execute(
            f"SELECT * FROM {self._glob(self.p.alphamissense)} "
            "WHERE chrom = ? AND enst = ? AND protein_variant = ?",
            [chrom, enst, protein_variant],
        ).df().to_dict("records")

    def am_by_region(self, chrom: str, start: int, end: int,
                     protein_variant: str) -> list[dict]:
        """転写産物 ID で一致しなかったときの予備経路。遺伝子の領域内を探す。"""
        if not self._ready(self.p.alphamissense):
            raise MissingIndex("alphamissense")
        return self.con.execute(
            f"SELECT * FROM {self._glob(self.p.alphamissense)} "
            "WHERE chrom = ? AND pos BETWEEN ? AND ? AND protein_variant = ?",
            [chrom, start, end, protein_variant],
        ).df().to_dict("records")

    # -- 座標で引く各データ源 ----------------------------------------------
    def _where_variants(self, variants: list[GenomicVariant]) -> tuple[str, list]:
        clause = " OR ".join(
            ["(chrom = ? AND pos = ? AND ref = ? AND alt = ?)"] * len(variants)
        )
        params: list = []
        for v in variants:
            params += [v.chrom, v.pos, v.ref, v.alt]
        return clause, params

    def funcvep_for(self, variants: list[GenomicVariant]) -> dict[str, dict]:
        if not variants or not self._ready(self.p.funcvep):
            return {}
        clause, params = self._where_variants(variants)
        cols = ", ".join(MODELS)
        df = self.con.execute(
            f"SELECT chrom, pos, ref, alt, ensg, {cols} "
            f"FROM {self._glob(self.p.funcvep)} WHERE {clause}",
            params,
        ).df()
        out = {}
        for r in df.to_dict("records"):
            key = f"{r['chrom']}-{r['pos']}-{r['ref']}-{r['alt']}"
            out[key] = r
        return out

    def training_for(self, variants: list[GenomicVariant]) -> dict[str, list[str]]:
        """その変異を学習に使ったモデル名を返す。

        6 モデル全部に含まれる変異は、全モデルの推論から除かれた結果として
        統合テーブルから行ごと消える（著者私信 2026-09-05）。索引が無ければ
        空の辞書を返し、呼び出し側は理由を断定しない。
        """
        if not variants or not self._ready(self.p.training_sets):
            return {}
        keys = [v.funcvep_id for v in variants]
        marks = ", ".join("?" for _ in keys)
        df = self.con.execute(
            f"SELECT variant_id, models FROM read_parquet('{self.p.training_sets}') "
            f"WHERE variant_id IN ({marks})",
            keys,
        ).df()
        return {
            r["variant_id"]: [m for m in str(r["models"]).split(",") if m]
            for r in df.to_dict("records")
        }

    def revel_for(self, variants: list[GenomicVariant]) -> dict[str, float]:
        if not variants or not self._ready(self.p.revel):
            return {}
        clause, params = self._where_variants(variants)
        df = self.con.execute(
            f"SELECT chrom, pos, ref, alt, max(revel) AS revel "
            f"FROM {self._glob(self.p.revel)} WHERE {clause} "
            "GROUP BY chrom, pos, ref, alt",
            params,
        ).df()
        return {
            f"{r['chrom']}-{r['pos']}-{r['ref']}-{r['alt']}": r["revel"]
            for r in df.to_dict("records")
        }

    def clinvar_same_residue(self, gene: str, aa_ref3: str, position: int) -> list[dict]:
        """同じ遺伝子・同じ残基番号を持つ ClinVar の全行。

        ClinVar の name 欄（例 NM_006158.5(NEFL):c.23C>T (p.Pro8Leu)）から
        p. 表記を正規表現で切り出す。LIKE では p.Pro8 が p.Pro80 にも当たるので、
        番号は切り出した値で厳密に比べる。
        """
        if not self._ready(self.p.clinvar):
            return []
        pat = r"p\.([A-Z][a-z]{2})(\d+)([A-Z][a-z]{2}|=|Ter)"
        df = self.con.execute(
            f"SELECT *, regexp_extract(name, ?, 1) AS aa_ref3, "
            f"regexp_extract(name, ?, 2) AS aa_pos, regexp_extract(name, ?, 3) AS aa_alt3 "
            f"FROM {self._glob(self.p.clinvar)} WHERE gene = ? AND name LIKE ?",
            [pat, pat, pat, gene, f"%p.{aa_ref3}{position}%"],
        ).df()
        return [r for r in df.to_dict("records")
                if r["aa_ref3"] == aa_ref3 and str(r["aa_pos"]) == str(position)]

    def clinvar_for(self, variants: list[GenomicVariant]) -> dict[str, dict]:
        if not variants or not self._ready(self.p.clinvar):
            return {}
        clause, params = self._where_variants(variants)
        df = self.con.execute(
            f"SELECT * FROM {self._glob(self.p.clinvar)} WHERE {clause}", params
        ).df()
        out: dict[str, dict] = {}
        for r in df.to_dict("records"):
            key = f"{r['chrom']}-{r['pos']}-{r['ref']}-{r['alt']}"
            out.setdefault(key, r)     # 同一座標に複数行あるときは先頭を採る
        return out


CLINVAR_STARS = {
    "practice guideline": 4,
    "reviewed by expert panel": 3,
    "criteria provided, multiple submitters, no conflicts": 2,
    "criteria provided, conflicting classifications": 1,
    "criteria provided, conflicting interpretations": 1,
    "criteria provided, single submitter": 1,
    "no assertion criteria provided": 0,
    "no classification provided": 0,
    "no classifications from unflagged records": 0,
}


def clinvar_stars(review_status: str | None) -> int:
    if not review_status:
        return 0
    return CLINVAR_STARS.get(review_status.strip().lower(), 0)


def _keep_same_gene(store: Store, hits: list[dict], ensg: str) -> list[dict]:
    """FuncVEP 側で同じ遺伝子に属すると確認できた候補だけを残す。

    遺伝子が重なる領域では、領域からの探索が隣の遺伝子の変異を拾いうる。
    別の遺伝子のスコアを黙って表示してしまうと誤りに気づけないため、
    座標ごとの ensg で裏を取る。FuncVEP の索引が無いときは判定できないので
    そのまま通す（その場合は照会結果にスコアも付かない）。
    """
    if not store._ready(store.p.funcvep) or not hits:
        return hits
    variants = [
        GenomicVariant(str(h["chrom"]), int(h["pos"]), h["ref"], h["alt"])
        for h in hits
    ]
    fv = store.funcvep_for(variants)
    if not fv:
        return hits
    kept = [
        h for h, v in zip(hits, variants)
        if fv.get(v.funcvep_id, {}).get("ensg") in (None, ensg)
    ]
    return kept or []


def _reachable_by_one_base(codon: str) -> set[str]:
    """そのコドンから 1 塩基の置換で到達できるアミノ酸。終止コドンは除く。"""
    out = set()
    for i in range(3):
        for base in "ACGT":
            if base != codon[i]:
                aa = translate_codon(codon[:i] + base + codon[i + 1:])
                if aa not in ("*", "X"):
                    out.add(aa)
    out.discard(translate_codon(codon))
    return out


def _explain_no_coordinate(store: Store, row: dict, aa_ref: str,
                           position: int, aa_alt: str,
                           rejected: list[tuple[str, float, int]] | None = None,
                           ) -> str:
    """座標を特定できなかった理由を、可能な限り具体的に述べる。

    「見つかりません」だけでは、入力の誤りなのか索引の不足なのか分からない。
    多くは 1 塩基置換では作れない置換なので、その場合は到達可能な置換を示す。
    """
    gene = row["gene"]
    pv = f"{aa_ref}{position}{aa_alt}"
    head = t("lk.no_coord_head", gene=gene, pv=pv)

    cds = store.cds_for(row["refseq_nuc"])
    if cds is not None:
        start = (position - 1) * 3
        codon = cds[start:start + 3]
        if len(codon) == 3:
            reachable = _reachable_by_one_base(codon)
            if aa_alt not in reachable:
                listed = join(sorted(reachable)) or t("lk.none")
                return head + t("lk.not_one_base", gene=gene, position=position,
                                codon=codon, aa_ref=aa_ref, aa_alt=aa_alt,
                                listed=listed)

    # 領域内に候補はあったが、番号体系が違うので採らなかった場合
    if rejected:
        seen: dict[str, tuple[float, int]] = {}
        for enst, agr, n in rejected:
            seen.setdefault(enst, (agr, n))
        listed = join(
            t("lk.rejected_item", enst=enst, agr=agr, n=n)
            for enst, (agr, n) in list(seen.items())[:3]
        )
        return head + t("lk.rejected", gene=gene, pv=pv, listed=listed)

    # 番号体系のずれが原因かどうかを対応表から確かめる
    note = store.numbering_note(row["ensg"], row["enst"])
    if note:
        return head + note

    return head + t("lk.not_in_am")


def resolve(text: str, store: Store) -> Resolution:
    """1 行の入力を解決して証拠を集める。例外は投げず Resolution.error に入れる。"""
    res = Resolution(query=text.strip())

    try:
        parsed = parse(text)
    except ParseError as exc:
        res.error = str(exc)
        return res

    if not store._ready(store.p.mane):
        res.error = t("lk.no_mane_index")
        return res

    # --- 転写産物と遺伝子を決める ---
    if isinstance(parsed, CodingInput):
        rows = store.mane_by_transcript(parsed.transcript)
        if not rows:
            res.error = t("lk.tx_not_found", tx=parsed.transcript)
            return res
        row = rows[0]
        cds = store.cds_for(row["refseq_nuc"])
        if cds is None:
            res.error = t("lk.no_cds", refseq=row["refseq_nuc"])
            return res
        try:
            aa_ref, position, aa_alt = apply_cds_substitution(
                cds, parsed.cds_position, parsed.ref_base, parsed.alt_base
            )
        except ParseError as exc:
            res.error = str(exc)
            return res
        if aa_ref == aa_alt:
            res.error = t("lk.synonymous", aa_ref=aa_ref, position=position)
            return res
        if aa_alt == "*":
            res.error = t("lk.stop_gain", aa_ref=aa_ref, position=position)
            return res
        if parsed.gene and parsed.gene.upper() != row["gene"].upper():
            res.warnings.append(
                t("lk.gene_mismatch", input_gene=parsed.gene, tx_gene=row["gene"])
            )
    else:
        rows = store.mane_by_gene(parsed.gene)
        if not rows:
            hints = store.gene_suggestions(parsed.gene)
            res.error = t("lk.gene_not_found", gene=parsed.gene) + (
                t("lk.hints", hints=", ".join(hints)) if hints else ""
            )
            return res
        aa_ref, position, aa_alt = parsed.aa_ref, parsed.position, parsed.aa_alt

        # 1 つの遺伝子に MANE 転写産物が複数ある（MANE Select と
        # MANE Plus Clinical）ことがあり、番号の付き方が異なる。
        # 参照アミノ酸が一致する転写産物を選ぶ。先頭で決め打ちにすると
        # MECP2 のように正しい入力を誤って拒否してしまう。
        row = None
        mismatches: list[str] = []
        for cand in rows:
            cds = store.cds_for(cand["refseq_nuc"])
            if cds is None:
                continue
            start = (position - 1) * 3
            if start + 3 > len(cds):
                mismatches.append(
                    t("lk.too_short", refseq=cand["refseq_nuc"], n=len(cds) // 3 - 1)
                )
                continue
            actual = translate_codon(cds[start:start + 3])
            if actual == aa_ref:
                row = cand
                break
            mismatches.append(
                t("lk.residue_is", refseq=cand["refseq_nuc"], position=position,
                  actual=actual)
            )

        if row is None:
            if not mismatches:
                # CDS が索引に無い。照合はできないが先へ進める。
                row = rows[0]
                res.warnings.append(t("lk.cds_skipped", refseq=row["refseq_nuc"]))
            else:
                res.error = t("lk.no_matching_tx", gene=parsed.gene, position=position,
                              aa_ref=aa_ref, mismatches=join(mismatches, wide=True))
                return res

        if len(rows) > 1:
            others = ", ".join(r["refseq_nuc"] for r in rows if r is not row)
            res.warnings.append(
                t("lk.multi_mane", gene=row["gene"], refseq=row["refseq_nuc"],
                  status=row["mane_status"], others=others)
            )

    res.gene = row["gene"]
    res.ensg = row["ensg"]
    res.constraint = store.constraint_for(row["ensg"])
    protein_variant = f"{aa_ref}{position}{aa_alt}"

    # --- アミノ酸変化をゲノム座標に変換する ---
    rejected_isoforms: list[tuple[str, float, int]] = []
    try:
        # 対応表があれば AlphaMissense 側の転写産物 ID と残基番号に読み替える。
        info = store.am_transcript_for(row["ensg"], row["enst"])
        am_enst = (info or {}).get("am_enst") or row["enst"]
        offset = (info or {}).get("offset", 0)

        hits = []
        if offset is not None:
            am_pv = f"{aa_ref}{position + offset}{aa_alt}"
            hits = store.am_by_protein(row["chrom"], am_enst, am_pv)
            if hits and info is None:
                # 対応表に無い遺伝子では、MANE の転写産物 ID をそのまま当てている。
                # ID が一致しても番号の付き方まで一致する保証はない。実測では
                # FPGT が同じ ENST00000370898 で一致率 0.064 だった。
                agr, compared = store.transcript_agreement(
                    row["refseq_nuc"], row["chrom"], am_enst)
                if compared < MIN_REGION_COMPARED or agr < MIN_REGION_AGREEMENT:
                    rejected_isoforms.append((am_enst, agr, compared))
                    hits = []
            if hits and offset:
                res.warnings.append(
                    t("lk.offset_warn", offset=offset, gene=row["gene"],
                      pv=protein_variant, am_pv=am_pv)
                )
        if not hits:
            found = store.am_by_region(
                row["chrom"], int(row["chr_start"]), int(row["chr_end"]),
                protein_variant,
            )
            if found:
                # 領域からの拾い上げは隣接する別遺伝子を掴む恐れがあるので、
                # まず FuncVEP 側の ensg が一致するものだけを残す。
                found = _keep_same_gene(store, found, row["ensg"])
            for h in found:
                # ensg が同じでもアイソフォームが違えば座標は別物になる。
                # 残基番号の付き方が MANE と揃っているものだけを採る。
                agr, compared = store.transcript_agreement(
                    row["refseq_nuc"], row["chrom"], str(h["enst"]))
                if compared >= MIN_REGION_COMPARED and agr >= MIN_REGION_AGREEMENT:
                    hits.append(h)
                else:
                    rejected_isoforms.append((str(h["enst"]), agr, compared))
            if hits:
                res.warnings.append(t("lk.region_warn"))
    except MissingIndex:
        res.error = t("lk.no_am_index")
        return res

    if not hits:
        res.error = _explain_no_coordinate(
            store, row, aa_ref, position, aa_alt, rejected_isoforms)
        return res

    variants = [
        GenomicVariant(str(h["chrom"]), int(h["pos"]), h["ref"], h["alt"])
        for h in hits
    ]
    if len(variants) > 1:
        res.warnings.append(t("lk.multi_nuc", n=len(variants)))

    # --- 証拠を集める ---
    fv = store.funcvep_for(variants)
    rv = store.revel_for(variants)
    cv = store.clinvar_for(variants)
    same_residue = (store.clinvar_same_residue(row["gene"], AA1_TO_3[aa_ref], position)
                    if store._ready(store.p.clinvar) else None)
    ts = store.training_for(variants)
    ts_ready = store._ready(store.p.training_sets)

    for h, gv in zip(hits, variants):
        key = gv.funcvep_id
        ev = Evidence(
            am_score=_clean(h.get("am_score")),
            am_class=h.get("am_class"),
            revel=_clean(rv.get(key)),
            clinvar=cv.get(key),
            same_residue=same_residue,
        )
        if store._ready(store.p.funcvep):
            ev.in_funcvep_table = key in fv
        if ts_ready:
            ev.train_models = ts.get(key, [])
        if key in fv:
            # 論文の方式では、学習に使われた変異のスコアは空欄（NaN）にしてある。
            # NaN をそのまま数値として扱うと「nan」と表示されてしまうので落とす。
            ev.funcvep = {
                m: float(fv[key][m]) for m in MODELS
                if fv[key].get(m) is not None and not _is_nan(fv[key][m])
            }
            if fv[key].get("ensg") and fv[key]["ensg"] != row["ensg"]:
                res.warnings.append(
                    t("lk.ensg_mismatch", fv_ensg=fv[key]["ensg"], ensg=row["ensg"])
                )
        res.variants.append(
            ResolvedVariant(
                gene=row["gene"], ensg=row["ensg"], enst=row["enst"],
                refseq_nuc=row["refseq_nuc"],
                aa_ref=aa_ref, position=position, aa_alt=aa_alt,
                genomic=gv, evidence=ev,
            )
        )

    if store._ready(store.p.funcvep):
        # スコアが出ない理由は 2 つあり、利用者の受け取り方が変わるので分けて伝える。
        statuses = {v.evidence.funcvep_status for v in res.variants}
        if statuses == {"blank"}:
            res.warnings.append(t("lk.warn_blank"))
        elif statuses == {"absent"}:
            res.warnings.append(t("lk.warn_absent"))
        elif statuses == {"absent_unexplained"}:
            res.warnings.append(t("lk.warn_absent_unexplained"))
        elif statuses and "scored" not in statuses:
            res.warnings.append(t("lk.warn_mixed"))

    return res
