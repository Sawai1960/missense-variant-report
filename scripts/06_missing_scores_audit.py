"""公開予測表とモデルの学習セットの食い違いを数え、著者への照会用に書き出す。

著者（Kayaalp ら, 2026-09-05 私信）によれば、学習に使われた変異はモデルごとに
推論から除外される。一部のモデルの学習にだけ使われた変異は行が残ってその列が空欄になり、
6 モデル全部の学習に使われた変異は行ごと消える。生物学的・配列的・QC 上の除外ではなく、
収録が無いこと自体は病原性について情報を持たない。

本スクリプトはこの説明が手元のデータでどこまで成り立つかを実測し、成り立たない例を
3 つに分類して書き出す。

  absent_not_in_training   表に無く、どの学習セットにも無い（当初の疑問の残り）
  absent_single_family     片方のファミリーの学習にしか使われていないのに行ごと無い
  scored_despite_training  学習に使われたのにスコアが入っている

先に scripts/05_fetch_training_sets.py を実行しておくこと。

出力
  画面           件数の内訳
  --write-list   上記 3 分類を 1 つの TSV に書き出す（category 列で区別）
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import duckdb

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from funcvep_report.config import load_config  # noqa: E402

# ClinVar のレビュー状態のうち 2 星以上に相当するもの
TWO_STAR_OR_BETTER = (
    "criteria provided, multiple submitters, no conflicts",
    "reviewed by expert panel",
    "practice guideline",
)

PATHOGENIC = ("Pathogenic", "Likely pathogenic", "Pathogenic/Likely pathogenic")
BENIGN = ("Benign", "Likely benign", "Benign/Likely benign")


def create_views(con, paths, funcvep_glob: str) -> None:
    """以降の集計が使うビューを作る。"""
    con.execute(f"""CREATE TEMP VIEW fv AS SELECT
        chrom::VARCHAR AS chrom, pos, ref, alt, ensg AS f_ensg,
        chrom::VARCHAR || '-' || pos || '-' || ref || '-' || alt AS variant_id,
        FuncVEP_CTI, FuncVEP_CTE, FuncVEP_SP,
        ClinVEP_CTI, ClinVEP_CTE, ClinVEP_SP
        FROM read_parquet('{funcvep_glob}')""")

    con.execute(f"""CREATE TEMP VIEW ts AS SELECT
        variant_id, ensg AS t_ensg, models, n_models
        FROM read_parquet('{paths.index / "training_sets.parquet"}')""")

    con.execute(f"""CREATE TEMP VIEW cvall AS SELECT
        chrom || '-' || pos || '-' || ref || '-' || alt AS variant_id,
        gene, significance, variation_id
        FROM read_parquet('{paths.clinvar}')""")

    # 2 星以上・MANE Select 上のミスセンス SNV。ミスセンスかどうかは ClinVar の
    # name の p. 表記で判定する（同義置換 p.Xxx123= と終止 Ter を除く）。
    # アプリ本体はコドンを実際に翻訳して判定するため、境界例で数件ずれうる。
    con.execute(f"""CREATE TEMP VIEW cv AS SELECT
        chrom || '-' || pos || '-' || ref || '-' || alt AS variant_id,
        gene, significance, variation_id,
        CASE WHEN significance IN {PATHOGENIC} THEN 'P/LP'
             WHEN significance IN {BENIGN}     THEN 'B/LB' END AS side
        FROM read_parquet('{paths.clinvar}') c
        WHERE review_status IN {TWO_STAR_OR_BETTER}
          AND length(ref) = 1 AND length(alt) = 1 AND ref <> alt
          AND name LIKE '%(p.%'
          AND name NOT LIKE '%=)%'
          AND name NOT LIKE '%Ter)%'
          AND significance IN {PATHOGENIC + BENIGN}
          AND EXISTS (
              SELECT 1 FROM read_parquet('{paths.mane}') m
              WHERE m.gene = c.gene AND c.name LIKE m.refseq_nuc_base || '.%'
          )""")

    con.execute("""CREATE TEMP VIEW audit AS SELECT
        cv.variant_id, cv.gene, cv.significance, cv.side, cv.variation_id,
        CASE WHEN fv.pos IS NULL THEN 'absent'
             WHEN fv.FuncVEP_CTI IS NULL AND fv.FuncVEP_CTE IS NULL
                  AND fv.FuncVEP_SP IS NULL THEN 'blank'
             WHEN fv.FuncVEP_CTI IS NULL THEN 'partial'
             ELSE 'scored' END AS status,
        coalesce(ts.n_models, 0) AS n_train_models,
        coalesce(ts.models, '')  AS train_models
        FROM cv
        LEFT JOIN fv USING (variant_id)
        LEFT JOIN ts USING (variant_id)""")

    # 学習に使われたのにスコアが入っている変異。ノートブック 04 の keep_mask が
    # (ID, ensg) の組で照合するため、公開表側の ensg が学習セットと違うと外れる。
    con.execute("""CREATE TEMP VIEW leaked AS SELECT
        ts.variant_id, ts.models, ts.t_ensg, fv.f_ensg
        FROM ts JOIN fv USING (variant_id)
        WHERE (ts.models LIKE 'FuncVEP%' AND ts.models NOT LIKE '%ClinVEP%'
               AND (fv.FuncVEP_CTI IS NOT NULL OR fv.FuncVEP_CTE IS NOT NULL
                    OR fv.FuncVEP_SP IS NOT NULL))
           OR (ts.models LIKE 'ClinVEP%' AND ts.models NOT LIKE '%FuncVEP%'
               AND (fv.ClinVEP_CTI IS NOT NULL OR fv.ClinVEP_CTE IS NOT NULL
                    OR fv.ClinVEP_SP IS NOT NULL))""")

    con.execute("""CREATE TEMP VIEW combined AS
        SELECT 'absent_not_in_training' AS category, a.variant_id, a.gene,
               a.variation_id, a.significance AS clinvar_significance,
               a.train_models, '' AS training_ensg, '' AS released_ensg
        FROM audit a WHERE a.status = 'absent' AND a.n_train_models = 0
        UNION ALL
        SELECT 'absent_single_family', ts.variant_id, coalesce(c.gene, ''),
               coalesce(c.variation_id, ''), coalesce(c.significance, ''),
               ts.models, ts.t_ensg, ''
        FROM ts LEFT JOIN fv USING (variant_id)
                LEFT JOIN cvall c USING (variant_id)
        WHERE ts.n_models = 3 AND fv.pos IS NULL
        UNION ALL
        SELECT 'scored_despite_training', l.variant_id, coalesce(c.gene, ''),
               coalesce(c.variation_id, ''), coalesce(c.significance, ''),
               l.models, l.t_ensg, l.f_ensg
        FROM leaked l LEFT JOIN cvall c USING (variant_id)""")


def report(con) -> None:
    print("2 星以上のミスセンス変異の内訳")
    print(f"{'':10}{'合計':>9}{'スコアあり':>12}{'空欄':>9}{'不在':>9}")
    for side in ("P/LP", "B/LB"):
        r = con.execute("""SELECT count(*),
            count(*) FILTER (status = 'scored'),
            count(*) FILTER (status IN ('blank','partial')),
            count(*) FILTER (status = 'absent')
            FROM audit WHERE side = ?""", [side]).fetchone()
        print(f"{side:10}{r[0]:>9,}{r[1]:>12,}{r[2]:>9,}{r[3]:>9,}")

    print("\n収録が無い変異を、学習セットで説明できるか")
    print(f"{'':10}{'不在':>9}{'6モデル学習':>13}{'一部で学習':>12}{'説明なし':>11}")
    for side, n, a, s, z in con.execute("""
        SELECT side, count(*),
               count(*) FILTER (n_train_models = 6),
               count(*) FILTER (n_train_models BETWEEN 1 AND 5),
               count(*) FILTER (n_train_models = 0)
        FROM audit WHERE status = 'absent' GROUP BY side ORDER BY side""").fetchall():
        print(f"{side:10}{n:>9,}{a:>13,}{s:>12,}{z:>11,}")

    tot = con.execute("""SELECT count(*) FILTER (status='absent'),
        count(*) FILTER (status='absent' AND n_train_models = 6) FROM audit""").fetchone()
    if tot[0]:
        print(f"\n不在 {tot[0]:,} 件のうち {tot[1]:,} 件 "
              f"({100.0 * tot[1] / tot[0]:.1f}%) は 6 モデル全部の学習セットに含まれ、"
              "著者の説明と一致します。")

    print("\n説明では起きないはずの事象（ClinVar の星に依らず、学習セット全体が対象）")
    n_absent = con.execute(
        "SELECT count(*) FROM ts LEFT JOIN fv USING (variant_id) "
        "WHERE ts.n_models = 3 AND fv.pos IS NULL").fetchone()[0]
    n_leak = con.execute("SELECT count(*) FROM leaked").fetchone()[0]
    print(f"  {'片方のファミリーの学習のみ・行ごと不在':<40}{n_absent:>7,} 件")
    print(f"  {'学習に使われたのにスコアあり':<40}{n_leak:>7,} 件")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write-list", type=Path, default=None,
                    help="3 分類をまとめて書き出す TSV のパス")
    args = ap.parse_args()

    cfg = load_config()
    paths = cfg.paths
    if not (paths.index / "training_sets.parquet").exists():
        raise SystemExit(
            "学習セットの索引がありません。"
            "先に python scripts/05_fetch_training_sets.py を実行してください。"
        )

    funcvep_glob = str(paths.funcvep / "**" / "*.parquet").replace("\\", "/")
    con = duckdb.connect()
    con.execute("PRAGMA threads=4")
    create_views(con, paths, funcvep_glob)
    report(con)

    if args.write_list:
        args.write_list.parent.mkdir(parents=True, exist_ok=True)
        con.execute(
            "COPY (SELECT * FROM combined ORDER BY category, variant_id) "
            "TO ? (FORMAT CSV, DELIMITER E'\t', HEADER)", [str(args.write_list)]
        )
        print(f"\n{args.write_list} に書き出しました。")
        for cat, n in con.execute(
            "SELECT category, count(*) FROM combined GROUP BY 1 ORDER BY 1"
        ).fetchall():
            print(f"  {cat:<26}{n:>7,} 件")
    con.close()


if __name__ == "__main__":
    main()
