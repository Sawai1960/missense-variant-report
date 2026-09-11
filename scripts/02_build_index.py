"""raw/ の生ファイルを検索しやすい Parquet に変換して index/ へ置く。

    python scripts/02_build_index.py                 すべて
    python scripts/02_build_index.py mane clinvar    一部だけ
    python scripts/02_build_index.py --cleanup       変換後に巨大な中間 TSV を消す

各手順は独立していて、既に出力があれば飛ばす。作り直したいときは
index/ の該当ファイルを消してから再実行すること。
"""

from __future__ import annotations

import gzip
import re
import shutil
import sys
import zipfile
from pathlib import Path

import duckdb

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from funcvep_report.config import load_config  # noqa: E402
from funcvep_report.variant import translate_codon  # noqa: E402

CHROMS = [str(i) for i in range(1, 23)] + ["X", "Y"]


def _memory_limit_gb(default: int = 8) -> int:
    """空きメモリの半分を上限にする（4〜32 GB に収める）。"""
    try:
        import ctypes

        class _Status(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong),
                        ("dwMemoryLoad", ctypes.c_ulong),
                        ("ullTotalPhys", ctypes.c_ulonglong),
                        ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong),
                        ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong),
                        ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]

        st = _Status()
        st.dwLength = ctypes.sizeof(_Status)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st))
        free_gb = st.ullAvailPhys / (1 << 30)
        return max(4, min(32, int(free_gb / 2)))
    except Exception:  # noqa: BLE001
        return default


def human(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:,.1f} {unit}"
        n /= 1024
    return f"{n:.1f} GB"


def _done(path: Path, label: str) -> bool:
    if path.exists():
        size = sum(f.stat().st_size for f in path.rglob("*") if f.is_file()) \
            if path.is_dir() else path.stat().st_size
        print(f"  済  {label} ({human(size)})")
        return True
    return False


# ---------------------------------------------------------------------------
# MANE
# ---------------------------------------------------------------------------

def build_mane(cfg, con: duckdb.DuckDBPyConnection) -> None:
    out = cfg.paths.mane
    if _done(out, "mane.parquet"):
        return
    src = cfg.paths.raw / "MANE.summary.txt.gz"
    print(f"  変換 {src.name} -> {out.name}")
    con.execute(
        f"""
        COPY (
            SELECT
                "symbol"                                        AS gene,
                regexp_replace("Ensembl_Gene", '\\..*$', '')     AS ensg,
                regexp_replace("Ensembl_nuc",  '\\..*$', '')     AS enst,
                "RefSeq_nuc"                                    AS refseq_nuc,
                regexp_replace("RefSeq_nuc",  '\\..*$', '')      AS refseq_nuc_base,
                "RefSeq_prot"                                   AS refseq_prot,
                "GRCh38_chr"                                    AS chr_accession,
                -- NC_000001.11 -> '1', NC_000023 -> 'X', NC_000024 -> 'Y'
                CASE CAST(substr("GRCh38_chr", 8, 2) AS INTEGER)
                     WHEN 23 THEN 'X' WHEN 24 THEN 'Y'
                     ELSE CAST(CAST(substr("GRCh38_chr", 8, 2) AS INTEGER) AS VARCHAR)
                END                                             AS chrom,
                CAST("chr_start" AS BIGINT)                     AS chr_start,
                CAST("chr_end"   AS BIGINT)                     AS chr_end,
                "chr_strand"                                    AS strand,
                "MANE_status"                                   AS mane_status
            FROM read_csv('{src.as_posix()}', delim='\t', header=true,
                          compression='gzip', all_varchar=true)
        ) TO '{out.as_posix()}' (FORMAT PARQUET, COMPRESSION ZSTD)
        """
    )
    n = con.execute(f"SELECT count(*) FROM '{out.as_posix()}'").fetchone()[0]
    print(f"       {n:,} 転写産物")


_VERSION_RE = re.compile(r"^VERSION\s+(\S+)")
_CDS_RE = re.compile(r"^     CDS             (?:join\()?<?(\d+)\.\.>?(\d+)\)?\s*$")


def _iter_gbff_cds(path: Path):
    """GenBank flat file から (accession, CDS 配列) を取り出す。

    MANE の mRNA レコードでは CDS は連続した 1 区間なので、複雑な join は
    数が少ない。解釈できなかったものは飛ばして件数だけ報告する。
    """
    acc = None
    cds_span: tuple[int, int] | None = None
    in_origin = False
    seq_parts: list[str] = []
    skipped = 0

    with gzip.open(path, "rt", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if line.startswith("VERSION"):
                m = _VERSION_RE.match(line)
                acc = m.group(1) if m else None
            elif line.startswith("     CDS "):
                m = _CDS_RE.match(line.rstrip("\n"))
                cds_span = (int(m.group(1)), int(m.group(2))) if m else None
                if m is None:
                    skipped += 1
            elif line.startswith("ORIGIN"):
                in_origin = True
                seq_parts = []
            elif line.startswith("//"):
                if acc and cds_span and seq_parts:
                    seq = "".join(seq_parts).upper()
                    s, e = cds_span
                    yield acc, seq[s - 1:e]
                acc, cds_span, in_origin, seq_parts = None, None, False, []
            elif in_origin:
                seq_parts.append(re.sub(r"[^a-zA-Z]", "", line))

    if skipped:
        print(f"       CDS 位置を解釈できず飛ばしたレコード: {skipped} 件")


def build_cds(cfg, con: duckdb.DuckDBPyConnection) -> None:
    out = cfg.paths.cds
    if _done(out, "mane_cds.parquet"):
        return
    src = cfg.paths.raw / "MANE.refseq_rna.gbff.gz"
    print(f"  変換 {src.name} -> {out.name}  （数分かかる）")

    import pyarrow as pa
    import pyarrow.parquet as pq

    accs: list[str] = []
    seqs: list[str] = []
    bad = 0
    for acc, cds in _iter_gbff_cds(src):
        if len(cds) % 3 != 0:
            bad += 1
            continue
        accs.append(acc)
        seqs.append(cds)

    table = pa.table({
        "refseq_nuc": pa.array(accs, pa.string()),
        "refseq_nuc_base": pa.array([a.split(".")[0] for a in accs], pa.string()),
        "cds": pa.array(seqs, pa.string()),
        "cds_len": pa.array([len(s) for s in seqs], pa.int32()),
    })
    out.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, out, compression="zstd")
    print(f"       {len(accs):,} 転写産物の CDS を保存"
          + (f"（3 の倍数でない {bad} 件は除外）" if bad else ""))


def build_constraint(cfg, con: duckdb.DuckDBPyConnection) -> None:
    out = cfg.paths.gene_constraint
    if _done(out, "gnomad_constraint.parquet"):
        return
    src = cfg.paths.raw / "gnomad_constraint_metrics.txt"
    print(f"  変換 {src.name} -> {out.name}")
    con.execute(
        f"""
        COPY (
            -- 元ファイルは 1.77E-16 のような指数表記や欠測を含むため、
            -- 文字列として読んでから明示的に数値化する。
            SELECT "ensg"                          AS ensg,
                   TRY_CAST("lof.pLI"     AS DOUBLE) AS pLI,
                   TRY_CAST("lof.z_score" AS DOUBLE) AS lof_z,
                   TRY_CAST("mis.z_score" AS DOUBLE) AS mis_z,
                   TRY_CAST("syn.z_score" AS DOUBLE) AS syn_z
            FROM read_csv('{src.as_posix()}', delim='\t', header=true,
                          all_varchar=true)
        ) TO '{out.as_posix()}' (FORMAT PARQUET, COMPRESSION ZSTD)
        """
    )


# ---------------------------------------------------------------------------
# ClinVar
# ---------------------------------------------------------------------------

def build_clinvar(cfg, con: duckdb.DuckDBPyConnection) -> None:
    out = cfg.paths.clinvar
    if _done(out, "clinvar.parquet"):
        return
    src = cfg.paths.raw / "variant_summary.txt.gz"
    print(f"  変換 {src.name} -> {out.name}")
    con.execute(
        f"""
        COPY (
            SELECT
                "Chromosome"                AS chrom,
                CAST("PositionVCF" AS BIGINT) AS pos,
                "ReferenceAlleleVCF"        AS ref,
                "AlternateAlleleVCF"        AS alt,
                "GeneSymbol"                AS gene,
                "Name"                      AS name,
                "ClinicalSignificance"      AS significance,
                "ReviewStatus"              AS review_status,
                "NumberSubmitters"          AS n_submitters,
                "PhenotypeList"             AS phenotypes,
                "VariationID"               AS variation_id,
                "LastEvaluated"             AS last_evaluated
            FROM read_csv('{src.as_posix()}', delim='\t', header=true,
                          compression='gzip', all_varchar=true,
                          ignore_errors=true, quote='')
            WHERE "Assembly" = 'GRCh38'
              AND "Type" = 'single nucleotide variant'
              AND "PositionVCF" ~ '^[0-9]+$'
              AND length("ReferenceAlleleVCF") = 1
              AND length("AlternateAlleleVCF") = 1
              AND "Chromosome" IN ({','.join(f"'{c}'" for c in CHROMS)})
        ) TO '{out.as_posix()}' (FORMAT PARQUET, COMPRESSION ZSTD)
        """
    )
    n = con.execute(f"SELECT count(*) FROM '{out.as_posix()}'").fetchone()[0]
    print(f"       {n:,} 件の一塩基置換")


# ---------------------------------------------------------------------------
# AlphaMissense（アミノ酸変化 ↔ ゲノム座標の橋渡し）
# ---------------------------------------------------------------------------

def build_alphamissense(cfg, con: duckdb.DuckDBPyConnection) -> None:
    out = cfg.paths.alphamissense
    if _done(out, "alphamissense/"):
        return
    src = cfg.paths.raw / "AlphaMissense_hg38.tsv.gz"
    print(f"  変換 {src.name} -> {out.name}/  （10〜20 分かかる）")
    out.mkdir(parents=True, exist_ok=True)
    con.execute(
        f"""
        COPY (
            SELECT
                replace("#CHROM", 'chr', '')                     AS chrom,
                CAST("POS" AS BIGINT)                            AS pos,
                "REF"                                            AS ref,
                "ALT"                                            AS alt,
                "uniprot_id"                                     AS uniprot,
                regexp_replace("transcript_id", '\\..*$', '')     AS enst,
                "protein_variant"                                AS protein_variant,
                CAST("am_pathogenicity" AS DOUBLE)               AS am_score,
                "am_class"                                       AS am_class
            FROM read_csv('{src.as_posix()}', delim='\t', header=true,
                          compression='gzip', comment='#', all_varchar=true,
                          column_names=['#CHROM','POS','REF','ALT','genome',
                                        'uniprot_id','transcript_id',
                                        'protein_variant','am_pathogenicity',
                                        'am_class'])
            WHERE replace("#CHROM", 'chr', '') IN ({','.join(f"'{c}'" for c in CHROMS)})
            -- 染色体内を転写産物とアミノ酸変化の順に並べておくと、
            -- 「遺伝子 + アミノ酸置換」での照会が行グループ単位で絞り込める。
            ORDER BY chrom, enst, protein_variant
        ) TO '{out.as_posix()}'
          (FORMAT PARQUET, COMPRESSION ZSTD, PARTITION_BY (chrom),
           OVERWRITE_OR_IGNORE true)
        """
    )
    n = con.execute(
        f"SELECT count(*) FROM read_parquet('{out.as_posix()}/**/*.parquet')"
    ).fetchone()[0]
    print(f"       {n:,} 変異")


# ---------------------------------------------------------------------------
# REVEL
# ---------------------------------------------------------------------------

def build_revel(cfg, con: duckdb.DuckDBPyConnection) -> None:
    out = cfg.paths.revel
    if _done(out, "revel/"):
        return
    src = cfg.paths.raw / "revel-v1.3_all_chromosomes.zip"
    tmp = cfg.paths.tmp / "revel_with_transcript_ids"
    if not tmp.exists():
        print(f"  展開 {src.name}")
        cfg.paths.tmp.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(src) as zf:
            inner = next(n for n in zf.namelist() if not n.endswith("/"))
            with zf.open(inner) as fin, tmp.open("wb") as fout:
                shutil.copyfileobj(fin, fout, length=1 << 22)

    print(f"  変換 {tmp.name} -> {out.name}/")
    out.mkdir(parents=True, exist_ok=True)
    con.execute(
        f"""
        COPY (
            SELECT chr                       AS chrom,
                   CAST(grch38_pos AS BIGINT) AS pos,
                   ref, alt, aaref, aaalt,
                   CAST(REVEL AS DOUBLE)     AS revel
            FROM read_csv('{tmp.as_posix()}', delim=',', header=true,
                          all_varchar=true, ignore_errors=true)
            WHERE grch38_pos ~ '^[0-9]+$'
              AND chr IN ({','.join(f"'{c}'" for c in CHROMS)})
            ORDER BY chrom, pos
        ) TO '{out.as_posix()}'
          (FORMAT PARQUET, COMPRESSION ZSTD, PARTITION_BY (chrom),
           OVERWRITE_OR_IGNORE true)
        """
    )
    n = con.execute(
        f"SELECT count(*) FROM read_parquet('{out.as_posix()}/**/*.parquet')"
    ).fetchone()[0]
    print(f"       {n:,} 変異")


# ---------------------------------------------------------------------------
# FuncVEP 本体
# ---------------------------------------------------------------------------

def build_funcvep(cfg, con: duckdb.DuckDBPyConnection) -> None:
    out = cfg.paths.funcvep
    if _done(out, "funcvep/"):
        return
    src = cfg.paths.raw / "FuncVEP_and_ClinVEP_scores.zip"
    tsv = cfg.paths.tmp / "FuncVEP_and_ClinVEP_scores.tsv"

    if not tsv.exists():
        print(f"  展開 {src.name} -> {tsv.name}  （約 11 GB。10〜20 分）")
        cfg.paths.tmp.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(src) as zf:
            inner = next(n for n in zf.namelist() if n.endswith(".tsv"))
            with zf.open(inner) as fin, tsv.open("wb") as fout:
                shutil.copyfileobj(fin, fout, length=1 << 22)
        print(f"       展開後 {human(tsv.stat().st_size)}")

    print(f"  変換 {tsv.name} -> {out.name}/  （20〜40 分）")
    out.mkdir(parents=True, exist_ok=True)
    con.execute(
        f"""
        COPY (
            SELECT
                split_part("ID", '-', 1)                  AS chrom,
                CAST(split_part("ID", '-', 2) AS BIGINT)  AS pos,
                split_part("ID", '-', 3)                  AS ref,
                split_part("ID", '-', 4)                  AS alt,
                "ensg",
                CAST("FuncVEP_CTI" AS DOUBLE) AS FuncVEP_CTI,
                CAST("FuncVEP_CTE" AS DOUBLE) AS FuncVEP_CTE,
                CAST("FuncVEP_SP"  AS DOUBLE) AS FuncVEP_SP,
                CAST("ClinVEP_CTI" AS DOUBLE) AS ClinVEP_CTI,
                CAST("ClinVEP_CTE" AS DOUBLE) AS ClinVEP_CTE,
                CAST("ClinVEP_SP"  AS DOUBLE) AS ClinVEP_SP
            FROM read_csv('{tsv.as_posix()}', delim='\t', header=true,
                          all_varchar=true)
            WHERE split_part("ID", '-', 1)
                  IN ({','.join(f"'{c}'" for c in CHROMS)})
            -- 元の TSV は ID の文字列順、つまり位置が数値順ではない。
            -- 数値順に並べ直すと行グループの位置範囲が狭まり、
            -- 座標での照会が全走査にならずに済む。
            ORDER BY chrom, pos
        ) TO '{out.as_posix()}'
          (FORMAT PARQUET, COMPRESSION ZSTD, PARTITION_BY (chrom),
           OVERWRITE_OR_IGNORE true)
        """
    )
    n = con.execute(
        f"SELECT count(*) FROM read_parquet('{out.as_posix()}/**/*.parquet')"
    ).fetchone()[0]
    print(f"       {n:,} 変異")


def build_transcript_map(cfg, con: duckdb.DuckDBPyConnection) -> None:
    """MANE の遺伝子と AlphaMissense の転写産物 ID を対応づける。

    AlphaMissense は MANE v1.5 より古い GENCODE で作られており、転写産物 ID が
    直接一致するのは約 7 割にとどまる（例: TP53 は MANE が ENST00000269305、
    AlphaMissense は ENST00000445888）。残りを毎回ゲノム領域の走査で探すのは
    遅いうえ、遺伝子が重なる領域では別の遺伝子を拾いかねない。

    そこで AlphaMissense の各転写産物から座標をいくつか取り、FuncVEP 側の
    ensg を引いて「転写産物 ID → 遺伝子」の対応を実測で作る。座標が根拠なので
    ID の世代差に左右されない。
    """
    out = cfg.paths.index / "transcript_map.parquet"
    if _done(out, "transcript_map.parquet"):
        return
    for need, label in ((cfg.paths.alphamissense, "alphamissense"),
                        (cfg.paths.funcvep, "funcvep"),
                        (cfg.paths.mane, "mane")):
        if not need.exists():
            print(f"  {label} の索引が先に必要です。飛ばします。")
            SKIPPED.append(f"transcript_map（{label} の索引が必要）")
            return

    am = f"read_parquet('{cfg.paths.alphamissense.as_posix()}/**/*.parquet')"
    fv = f"read_parquet('{cfg.paths.funcvep.as_posix()}/**/*.parquet')"
    mane = f"read_parquet('{cfg.paths.mane.as_posix()}')"

    print("  作成 transcript_map.parquet")
    con.execute(
        f"""
        COPY (
            WITH sample AS (
                -- 転写産物ごとに先頭 25 変異だけ見れば遺伝子は決まる
                SELECT chrom, enst, pos, ref, alt, uniprot
                FROM {am}
                QUALIFY row_number() OVER (PARTITION BY enst ORDER BY pos) <= 25
            ),
            voted AS (
                SELECT s.enst, f.ensg, any_value(s.uniprot) AS uniprot,
                       count(*) AS hits
                FROM sample s
                JOIN {fv} f
                  ON f.chrom = s.chrom AND f.pos = s.pos
                 AND f.ref = s.ref AND f.alt = s.alt
                GROUP BY s.enst, f.ensg
            ),
            best AS (
                -- 1 つの転写産物が複数遺伝子に当たることがあるので多数決
                SELECT * FROM voted
                QUALIFY row_number() OVER (PARTITION BY enst ORDER BY hits DESC) = 1
            )
            SELECT m.gene, m.ensg, m.chrom,
                   m.enst        AS mane_enst,
                   b.enst        AS am_enst,
                   b.uniprot     AS uniprot,
                   b.hits        AS support,
                   (m.enst = b.enst) AS id_matches
            FROM {mane} m
            JOIN best b ON b.ensg = m.ensg
            QUALIFY row_number() OVER (PARTITION BY m.gene, m.enst
                                       ORDER BY b.hits DESC) = 1
        ) TO '{out.as_posix()}' (FORMAT PARQUET, COMPRESSION ZSTD)
        """
    )
    _verify_transcript_map(cfg, con, out)

    total, matched, exact, agree = con.execute(
        f"""SELECT (SELECT count(DISTINCT gene) FROM {mane}),
                   count(DISTINCT gene),
                   count(DISTINCT gene) FILTER (WHERE id_matches),
                   count(DISTINCT gene) FILTER (WHERE aa_agreement >= 0.95)
            FROM read_parquet('{out.as_posix()}')"""
    ).fetchone()
    print(f"       MANE の {total:,} 遺伝子のうち {matched:,} 件を対応づけ "
          f"({100 * matched / total:.1f}%)")
    print(f"       うち転写産物 ID がそのまま一致するのは {exact:,} 件 "
          f"({100 * exact / matched:.1f}%)")
    print(f"       アミノ酸の番号の付き方まで一致するのは {agree:,} 件 "
          f"({100 * agree / matched:.1f}%)")
    if matched < total:
        print(f"       残る {total - matched:,} 遺伝子は照会時に"
              "ゲノム領域での探索に回ります。")


def _verify_transcript_map(cfg, con: duckdb.DuckDBPyConnection,
                           map_path: Path) -> None:
    """対応づけた転写産物同士でアミノ酸の番号の付き方が一致するかを測る。

    同じ遺伝子でもアイソフォームが違えば残基番号がずれる。例えば MECP2 は
    NM_004992（486 残基）で R168、NM_001110792（498 残基）で R181 が同じ残基を指す。
    番号体系が違う相手に p.Arg168Cys をそのまま当てると、黙って別の残基の
    スコアを返してしまう。これは臨床上あってはならない誤りなので、
    参照アミノ酸の一致率を測って記録しておく。
    """
    import pyarrow as pa

    print("       アミノ酸の番号体系が一致するかを照合しています…")

    # MANE の CDS を翻訳して (転写産物, 残基位置, アミノ酸) の表にする
    cds_rows = con.execute(
        f"SELECT refseq_nuc_base, cds FROM read_parquet("
        f"'{cfg.paths.cds.as_posix()}')"
    ).fetchall()
    mane_tx = con.execute(
        f"SELECT refseq_nuc_base, enst FROM read_parquet("
        f"'{cfg.paths.mane.as_posix()}')"
    ).fetchall()
    tx_of = {}
    for base, enst in mane_tx:
        tx_of.setdefault(base, enst)

    ensts: list[str] = []
    poss: list[int] = []
    aas: list[str] = []
    for base, cds in cds_rows:
        enst = tx_of.get(base)
        if not enst:
            continue
        for i in range(0, len(cds) - 2, 3):
            aa = translate_codon(cds[i:i + 3])
            if aa == "*":
                break
            ensts.append(enst)
            poss.append(i // 3 + 1)
            aas.append(aa)

    mane_protein = pa.table({
        "mane_enst": pa.array(ensts, pa.string()),
        "aa_pos": pa.array(poss, pa.int32()),
        "aa": pa.array(aas, pa.string()),
    })
    con.register("mane_protein", mane_protein)
    print(f"       MANE 側の残基 {len(ensts):,} 個を展開しました")

    am = f"read_parquet('{cfg.paths.alphamissense.as_posix()}/**/*.parquet')"
    tmp_out = map_path.with_suffix(".verified.parquet")
    con.execute(
        f"""
        COPY (
            WITH am_res AS (
                -- protein_variant（例 R175H）から参照アミノ酸と位置を取り出す
                SELECT DISTINCT
                    enst AS am_enst,
                    CAST(regexp_extract(protein_variant, '^[A-Z](\\d+)', 1)
                         AS INTEGER) AS aa_pos,
                    regexp_extract(protein_variant, '^([A-Z])', 1) AS aa
                FROM {am}
            ),
            scored AS (
                SELECT m.gene, m.mane_enst, m.am_enst,
                       count(*) AS compared,
                       avg(CASE WHEN a.aa = p.aa THEN 1.0 ELSE 0.0 END) AS agreement
                FROM read_parquet('{map_path.as_posix()}') m
                JOIN am_res a  ON a.am_enst  = m.am_enst
                JOIN mane_protein p
                  ON p.mane_enst = m.mane_enst AND p.aa_pos = a.aa_pos
                GROUP BY m.gene, m.mane_enst, m.am_enst
            )
            SELECT m.*,
                   coalesce(s.agreement, 0.0) AS aa_agreement,
                   coalesce(s.compared, 0)    AS aa_compared
            FROM read_parquet('{map_path.as_posix()}') m
            LEFT JOIN scored s
              ON s.gene = m.gene AND s.mane_enst = m.mane_enst
             AND s.am_enst = m.am_enst
        ) TO '{tmp_out.as_posix()}' (FORMAT PARQUET, COMPRESSION ZSTD)
        """
    )
    con.unregister("mane_protein")
    map_path.unlink()
    tmp_out.rename(map_path)

    _fit_numbering_offsets(cfg, con, map_path, ensts, poss, aas)


def _fit_numbering_offsets(cfg, con: duckdb.DuckDBPyConnection, map_path: Path,
                           ensts: list[str], poss: list[int],
                           aas: list[str]) -> None:
    """番号体系がずれている対応について、一定のずれ幅で説明できるか調べる。

    アイソフォームの違いは多くの場合、N 末端側の長さの差による一律のずれとして
    現れる（MECP2 の e2 R168 と e1 R181 など）。ずれ幅が 1 つ見つかって
    ほぼ全残基を説明できるなら、番号を機械的に読み替えられる。
    説明できない場合はずれ幅を記録せず、照会時に理由を示して止める。
    """
    import pyarrow as pa
    import pyarrow.parquet as pq

    bad = con.execute(
        f"""SELECT gene, mane_enst, am_enst FROM read_parquet(
                '{map_path.as_posix()}')
            WHERE aa_agreement < 0.95"""
    ).fetchall()
    if not bad:
        return
    print(f"       番号体系がずれている {len(bad):,} 件のずれ幅を調べています…")

    # MANE 側を転写産物ごとの配列に組み直す
    mane_seq: dict[str, dict[int, str]] = {}
    for e, p, a in zip(ensts, poss, aas):
        mane_seq.setdefault(e, {})[p] = a

    am_targets = {r[2] for r in bad}
    am = f"read_parquet('{cfg.paths.alphamissense.as_posix()}/**/*.parquet')"
    con.execute(
        f"""CREATE OR REPLACE TEMP TABLE am_bad AS
            SELECT DISTINCT enst,
                   CAST(regexp_extract(protein_variant, '^[A-Z](\\d+)', 1)
                        AS INTEGER) AS aa_pos,
                   regexp_extract(protein_variant, '^([A-Z])', 1) AS aa
            FROM {am}
            WHERE enst IN ({','.join(f"'{e}'" for e in am_targets)})"""
    )
    am_rows = con.execute(
        "SELECT enst, aa_pos, aa FROM am_bad ORDER BY enst, aa_pos"
    ).fetchall()
    am_seq: dict[str, dict[int, str]] = {}
    for e, p, a in am_rows:
        am_seq.setdefault(e, {})[p] = a

    genes, mtx, atx, offs, agrs = [], [], [], [], []
    resolved = 0
    for gene, mane_enst, am_enst in bad:
        ms = mane_seq.get(mane_enst)
        as_ = am_seq.get(am_enst)
        if not ms or not as_:
            continue
        best_off, best_agr = 0, 0.0
        for off in range(-80, 81):
            hit = tot = 0
            for pos, aa in as_.items():
                m = ms.get(pos - off)
                if m is not None:
                    tot += 1
                    hit += (m == aa)
            if tot >= 50:
                agr = hit / tot
                if agr > best_agr:
                    best_off, best_agr = off, agr
        genes.append(gene)
        mtx.append(mane_enst)
        atx.append(am_enst)
        offs.append(best_off)
        agrs.append(best_agr)
        if best_agr >= 0.95 and best_off != 0:
            resolved += 1

    tbl = pa.table({
        "gene": pa.array(genes, pa.string()),
        "mane_enst": pa.array(mtx, pa.string()),
        "am_enst": pa.array(atx, pa.string()),
        "fit_offset": pa.array(offs, pa.int32()),
        "fit_agreement": pa.array(agrs, pa.float64()),
    })
    fit_path = cfg.paths.index / "numbering_offsets.parquet"
    pq.write_table(tbl, fit_path, compression="zstd")
    print(f"       うち {resolved:,} 件は一定のずれ幅で読み替えできます")
    print(f"       残り {len(genes) - resolved:,} 件は照会時に理由を示して止めます")


# 並び順は依存関係の順。transcript_map は alphamissense・funcvep・mane の索引を使うので最後
STEPS = {
    "mane": [build_mane, build_cds],
    "constraint": [build_constraint],
    "clinvar": [build_clinvar],
    "alphamissense": [build_alphamissense],
    "revel": [build_revel],
    "funcvep": [build_funcvep],
    "transcript_map": [build_transcript_map],
}


# 依存する索引が無くて飛ばした段階。最後にまとめて知らせる
SKIPPED: list[str] = []


def main(argv: list[str]) -> int:
    cfg = load_config()
    cfg.paths.index.mkdir(parents=True, exist_ok=True)

    keys = [a for a in argv if not a.startswith("-")] or list(STEPS)
    unknown = [k for k in keys if k not in STEPS]
    if unknown:
        print(f"不明な指定: {unknown}。使えるのは {list(STEPS)}")
        return 1

    con = duckdb.connect()
    # 8,700 万行の並べ替えを行うので、空きメモリの半分程度まで使わせる。
    # 足りなければ temp_directory に溢れるだけで、失敗はしない。
    con.execute(f"PRAGMA memory_limit='{_memory_limit_gb()}GB'")
    con.execute(f"PRAGMA temp_directory='{cfg.paths.tmp.as_posix()}'")

    print(f"索引の出力先: {cfg.paths.index}")
    for key in keys:
        print(f"\n[{key}]")
        for fn in STEPS[key]:
            src_missing = None
            try:
                fn(cfg, con)
            except FileNotFoundError as exc:
                src_missing = exc
            if src_missing:
                print(f"  未取得のため飛ばします: {src_missing}")
                SKIPPED.append(f"{key}（{src_missing}）")

    # このスクリプトが作った中間ファイルだけを対象にする。
    # 利用者が置いた他のファイルには触らない。
    intermediates = [
        cfg.paths.tmp / n
        for n in ("FuncVEP_and_ClinVEP_scores.tsv", "revel_with_transcript_ids")
    ]
    present = [p for p in intermediates if p.exists()]

    if "--cleanup" in argv:
        for p in present:
            size = p.stat().st_size
            p.unlink()
            print(f"\n削除しました: {p.name} ({human(size)})")
    elif present:
        total = sum(p.stat().st_size for p in present)
        print(f"\n変換用の中間ファイルが {cfg.paths.tmp} に {human(total)} 残っています。")
        print("索引ができていれば不要です。--cleanup を付けて再実行すると削除します。")

    if SKIPPED:
        print("\n次の段階は飛ばしました。原因を直して再実行してください:")
        for item in SKIPPED:
            print(f"  - {item}")
        return 1
    print("\n索引の作成が終わりました。streamlit run app.py で起動できます。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
