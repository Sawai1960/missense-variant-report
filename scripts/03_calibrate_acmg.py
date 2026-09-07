"""FuncVEP スコアを ACMG の PP3/BP4 の証拠強度に較正する。

手法は Pejaver ら (2022, Am J Hum Genet) と Tavtigian ら (2018) に従う。
ClinVar のラベル付きミスセンス変異でスコアの分布を求め、局所的な陽性尤度比が
各強度の下限（C^(1/8), C^(1/4), C^(1/2), C。C = 350）を超える境界を閾値とする。

    python scripts/03_calibrate_acmg.py

出力: index/acmg_thresholds.json

重要な注意
  ここで使う ClinVar は FuncVEP-CTI の学習に使われた臨床予測器と情報源が重なる。
  したがって CTI の較正結果は楽観的に偏りうる。CTE / SP の較正はその影響が小さい。
  論文の Supplementary Table 13 の較正値が入手できるなら、そちらを優先すること。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import duckdb
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from funcvep_report.acmg import LR_BENIGN, LR_PATHOGENIC  # noqa: E402
from funcvep_report.config import MODELS, load_config  # noqa: E402

BOOTSTRAP = 100
WINDOW = 0.03          # 局所尤度比を測る窓の半幅（スコア軸上）
GRID = 2001            # 0..1 を刻む数
MIN_IN_WINDOW = 15     # 窓内にこの数だけ変異が無ければ推定しない

PATHOGENIC = ("pathogenic", "likely pathogenic", "pathogenic/likely pathogenic")
BENIGN = ("benign", "likely benign", "benign/likely benign")


def load_labelled(cfg, con) -> tuple[np.ndarray, dict[str, np.ndarray]]:
    """ClinVar のラベルと FuncVEP スコアを突き合わせて返す。"""
    fv = cfg.paths.funcvep.as_posix()
    cv = cfg.paths.clinvar.as_posix()
    cols = ", ".join(f"f.{m}" for m in MODELS)

    sig_p = ",".join(f"'{s}'" for s in PATHOGENIC)
    sig_b = ",".join(f"'{s}'" for s in BENIGN)

    df = con.execute(
        f"""
        WITH labelled AS (
            SELECT chrom, pos, ref, alt, gene, review_status,
                   CASE WHEN lower(trim(significance)) IN ({sig_p}) THEN 1
                        WHEN lower(trim(significance)) IN ({sig_b}) THEN 0
                   END AS label
            FROM read_parquet('{cv}')
            WHERE lower(trim(significance)) IN ({sig_p},{sig_b})
              AND review_status IN (
                  'practice guideline',
                  'reviewed by expert panel',
                  'criteria provided, multiple submitters, no conflicts')
        ),
        joined AS (
            SELECT l.label, l.gene, {cols},
                   row_number() OVER (PARTITION BY l.gene, l.label
                                      ORDER BY l.pos) AS rn
            FROM labelled l
            JOIN read_parquet('{fv}/**/*.parquet') f
              ON f.chrom = l.chrom AND f.pos = l.pos
             AND f.ref = l.ref AND f.alt = l.alt
        )
        SELECT label, {', '.join(MODELS)} FROM joined WHERE rn <= {cfg.max_variants_per_gene}
        """
    ).df()

    labels = df["label"].to_numpy(dtype=np.int8)
    scores = {m: df[m].to_numpy(dtype=float) for m in MODELS}
    return labels, scores


def local_lr(scores: np.ndarray, labels: np.ndarray, grid: np.ndarray,
             rng: np.random.Generator | None = None) -> np.ndarray:
    """グリッド各点での局所的な陽性尤度比。推定できない点は NaN。"""
    if rng is not None:
        idx = rng.integers(0, len(scores), len(scores))
        scores, labels = scores[idx], labels[idx]

    n_p = int((labels == 1).sum())
    n_b = int((labels == 0).sum())
    if n_p == 0 or n_b == 0:
        return np.full(len(grid), np.nan)

    sp = np.sort(scores[labels == 1])
    sb = np.sort(scores[labels == 0])

    lo, hi = grid - WINDOW, grid + WINDOW
    cnt_p = np.searchsorted(sp, hi, "right") - np.searchsorted(sp, lo, "left")
    cnt_b = np.searchsorted(sb, hi, "right") - np.searchsorted(sb, lo, "left")

    out = np.full(len(grid), np.nan)
    enough = (cnt_p + cnt_b) >= MIN_IN_WINDOW
    # 0 除算を避けるため Laplace 補正を入れる
    with np.errstate(divide="ignore", invalid="ignore"):
        lr = ((cnt_p + 0.5) / (n_p + 1)) / ((cnt_b + 0.5) / (n_b + 1))
    out[enough] = lr[enough]
    return out


def thresholds_from_lr(grid: np.ndarray, lr: np.ndarray) -> dict:
    """尤度比の曲線から、各強度を満たす境界スコアを読み取る。

    PP3 側は「そのスコア以上で常に基準を満たす」最小のスコアを採る。
    こうすると曲線の凹凸で閾値が甘くなることを避けられる。
    """
    res: dict[str, dict[str, float]] = {"PP3": {}, "BP4": {}}
    valid = ~np.isnan(lr)

    for strength, need in LR_PATHOGENIC.items():
        ok = valid & (lr >= need)
        # 上端から連続して満たしている区間の下限を探す
        cut = None
        for i in range(len(grid) - 1, -1, -1):
            if valid[i] and not ok[i]:
                break
            if ok[i]:
                cut = float(grid[i])
        if cut is not None and cut < 1.0:
            res["PP3"][strength] = cut

    for strength, need in LR_BENIGN.items():
        ok = valid & (lr <= need)
        cut = None
        for i in range(len(grid)):
            if valid[i] and not ok[i]:
                break
            if ok[i]:
                cut = float(grid[i])
        if cut is not None and cut > 0.0:
            res["BP4"][strength] = cut

    # 強い基準が弱い基準より緩くなる矛盾を取り除く
    prev = None
    for s in ("supporting", "moderate", "strong", "very_strong"):
        v = res["PP3"].get(s)
        if v is None:
            continue
        if prev is not None and v < prev:
            res["PP3"][s] = prev
        prev = res["PP3"][s]
    prev = None
    for s in ("supporting", "moderate", "strong", "very_strong"):
        v = res["BP4"].get(s)
        if v is None:
            continue
        if prev is not None and v > prev:
            res["BP4"][s] = prev
        prev = res["BP4"][s]
    return res


def main() -> int:
    cfg = load_config()
    for p, name in ((cfg.paths.funcvep, "funcvep"), (cfg.paths.clinvar, "clinvar")):
        if not p.exists():
            print(f"{name} の索引がありません。先に scripts/02_build_index.py を実行してください。")
            return 1

    con = duckdb.connect()
    con.execute("PRAGMA memory_limit='6GB'")

    print("ClinVar と FuncVEP を突き合わせています…")
    labels, scores = load_labelled(cfg, con)
    n_p, n_b = int((labels == 1).sum()), int((labels == 0).sum())
    print(f"  病的 {n_p:,} 件 / 良性 {n_b:,} 件")
    if n_p < 500 or n_b < 500:
        print("  較正に足る件数がありません。処理を中止します。")
        return 1

    grid = np.linspace(0.0, 1.0, GRID)
    rng = np.random.default_rng(42)
    out_models: dict[str, dict] = {}

    for model in MODELS:
        s = scores[model]
        keep = ~np.isnan(s)
        sm, lm = s[keep], labels[keep]
        print(f"\n[{model}] 有効 {len(sm):,} 件")

        # ブートストラップで尤度比の下側 5 パーセンタイルを採る（保守的）
        draws = np.vstack([
            local_lr(sm, lm, grid, rng) for _ in range(BOOTSTRAP)
        ])
        all_nan = np.all(np.isnan(draws), axis=0)
        lr_low = np.full(grid.shape, np.nan)
        if not all_nan.all():
            lr_low[~all_nan] = np.nanpercentile(draws[:, ~all_nan], 5, axis=0)

        t = thresholds_from_lr(grid, lr_low)
        out_models[model] = t
        for crit in ("PP3", "BP4"):
            if t[crit]:
                shown = ", ".join(f"{k} {v:.4f}" for k, v in t[crit].items())
                print(f"  {crit}: {shown}")
            else:
                print(f"  {crit}: 該当する強度なし")

    clinvar_date = con.execute(
        f"SELECT max(last_evaluated) FROM read_parquet("
        f"'{cfg.paths.clinvar.as_posix()}')"
    ).fetchone()[0]

    payload = {
        "meta": {
            "method": "Pejaver 2022 / Tavtigian 2018 の局所尤度比法",
            "prior_pathogenic": cfg.prior_pathogenic,
            "min_review_stars": cfg.min_review_stars,
            "max_variants_per_gene": cfg.max_variants_per_gene,
            "window": WINDOW,
            "bootstrap": BOOTSTRAP,
            "percentile": 5,
            "n_pathogenic": n_p,
            "n_benign": n_b,
            "clinvar_date": str(clinvar_date),
            "caveat": (
                "ClinVar は FuncVEP-CTI の特徴量に含まれる臨床学習済み予測器と"
                "情報源が重なるため、CTI の較正は楽観的に偏りうる。"
            ),
        },
        "models": out_models,
    }
    dest = cfg.thresholds_path
    dest.parent.mkdir(parents=True, exist_ok=True)
    with dest.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
    print(f"\n保存しました: {dest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
