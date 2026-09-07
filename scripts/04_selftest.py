"""索引が正しく組み上がっているかを既知の変異で確かめる。

    python scripts/04_selftest.py

確かめること
  1. 既知の病的／良性変異が解決でき、ゲノム座標が特定できるか
  2. FuncVEP のスコアが引けるか（＝座標系が本当に GRCh38 で揃っているか）
  3. ClinVar の判定が期待どおりに付くか
  4. MANE の転写産物のうち何割が AlphaMissense に載っているか（網羅率）
  5. 遺伝子記号からの入力と HGVS からの入力が同じ座標に行き着くか
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from funcvep_report.config import load_config  # noqa: E402
from funcvep_report.lookup import Store, resolve  # noqa: E402

# (入力, 期待する ClinVar の向き) — None は問わない
CASES: list[tuple[str, str | None]] = [
    ("BRCA1 p.Arg1699Trp", "pathogenic"),
    ("NM_007294.4:c.5095C>T", "pathogenic"),
    ("TP53 p.Arg175His", "pathogenic"),
    ("NM_000546.6:c.524G>A", "pathogenic"),
    ("FGFR3 p.Gly380Arg", "pathogenic"),
    ("NM_000142.5:c.1138G>A", "pathogenic"),
    ("CFTR p.Arg117His", None),        # 表現度が多様で判定が割れる例
    ("MECP2 p.Arg106Trp", None),       # Rett 症候群。CGG>TGG の 1 塩基置換
    ("MECP2 p.Arg133Cys", None),       # Rett 症候群。比較的軽症とされる
    ("NM_004992.4:c.316C>T", None),    # 上と同じ変異を HGVS で
    ("BRCA2 p.Asn372His", "benign"),   # 一般集団に多い多型
    ("SMAD4 p.Arg361His", "pathogenic"),
    ("LDLR p.Gly592Glu", None),
    ("HBB p.Glu7Val", None),           # 鎌状赤血球症。番号の付け方が 2 通りある
]

# 同じ変異を 2 つの表記で入れて一致を見る
PAIRS = [
    ("BRCA1 p.Arg1699Trp", "NM_007294.4:c.5095C>T"),
    ("FGFR3 p.Gly380Arg", "NM_000142.5:c.1138G>A"),
    ("TP53 p.Arg175His", "NM_000546.6:c.524G>A"),
    ("MECP2 p.Arg106Trp", "NM_004992.4:c.316C>T"),
]

# 解決できないことが正しい入力。理由の説明が的確かを見る。
SHOULD_FAIL: list[tuple[str, str]] = [
    # MECP2 の 168 番コドンは CGA。Cys へは 2 塩基の変化が要る
    ("MECP2 p.Arg168Cys", "1 塩基の置換では変えられません"),
    ("TP53 p.Arg175Ter", "ナンセンス"),
    ("BRCA1 p.Arg1699=", "同義置換"),
    ("NOTAGENE p.Arg100Cys", "見つかりません"),
    # 遺伝子の領域内に同じ表記の行はあるが、別アイソフォームのもの。
    # 以前はこれを採用して 50 kb 離れた座標のスコアを表示していた。
    ("COL18A1 p.Ala2Val", "残基番号の付き方が違います"),
    ("RANBP1 p.Glu82Asp", "残基番号の付き方が違います"),
    # 転写産物 ID は MANE と一致するのに、AlphaMissense 側の番号体系が違う例
    ("FPGT p.Ala3Asp", "残基番号の付き方が違います"),
]


def direction(significance: str | None) -> str | None:
    if not significance:
        return None
    s = significance.lower()
    if "pathogenic" in s and "conflict" not in s:
        return "pathogenic"
    if "benign" in s and "conflict" not in s:
        return "benign"
    return None


def main() -> int:
    cfg = load_config()
    store = Store(cfg)
    avail = store.availability()

    print("索引の状態")
    for k, v in avail.items():
        print(f"  {'あり' if v else 'なし'}  {k}")
    missing = [k for k in ("mane", "cds", "alphamissense") if not avail[k]]
    if missing:
        print(f"\n必須の索引がありません: {missing}")
        return 1
    print()

    ok = warn = ng = 0
    results: dict[str, tuple] = {}
    timings: list[float] = []

    print("=" * 78)
    print("既知の変異の解決")
    print("=" * 78)
    for query, expect in CASES:
        t0 = time.perf_counter()
        res = resolve(query, store)
        timings.append(time.perf_counter() - t0)
        if res.error:
            print(f"NG   {query:32s} {res.error.splitlines()[0]}")
            ng += 1
            continue

        # 同じアミノ酸置換に複数の塩基置換が対応することがある。
        # 報告にはスコアが付いている候補を優先して選ぶ。
        v = next((x for x in res.variants if x.evidence.funcvep.get("FuncVEP_CTI")
                  is not None), res.variants[0])
        ev = v.evidence
        results[query] = frozenset(x.genomic.funcvep_id for x in res.variants)

        fv = ev.funcvep.get("FuncVEP_CTI")
        cv_sig = (ev.clinvar or {}).get("significance")
        got = direction(cv_sig)

        parts = [
            f"{v.gene} p.{v.protein_variant}",
            str(v.genomic),
            f"CTI={fv:.3f}" if fv is not None else "CTI=なし",
            f"AM={ev.am_score:.3f}" if ev.am_score is not None else "AM=なし",
            f"REVEL={ev.revel:.3f}" if ev.revel is not None else "REVEL=なし",
            f"ClinVar={cv_sig or 'なし'}",
        ]
        if len(res.variants) > 1:
            parts.append(f"候補{len(res.variants)}件")
        line = f"     {query:32s} " + " | ".join(parts)

        if avail["funcvep"] and fv is None:
            print("WARN" + line[4:])
            reason = {
                "blank": "予測表に行はあるがスコアが空欄（学習に使われた変異）",
                "absent": "予測表にこの変異の行自体が無い（表は全変異を網羅していない）",
            }.get(ev.funcvep_status, "理由を判定できません")
            print(f"       FuncVEP のスコアが出ません: {reason}")
            warn += 1
        elif expect and got and got != expect:
            print("NG  " + line[4:])
            print(f"       ClinVar の向きが期待 {expect} と違います（{got}）")
            ng += 1
        else:
            print("OK  " + line[4:])
            ok += 1

        for w in res.warnings:
            print(f"       注意: {w}")

    print()
    print("=" * 78)
    print("拒否されるべき入力が、理由とともに拒否されるか")
    print("=" * 78)
    for query, fragment in SHOULD_FAIL:
        res = resolve(query, store)
        if res.error is None:
            print(f"NG   {query:32s} 拒否されるべきなのに解決されました")
            ng += 1
        elif fragment in res.error:
            first = res.error.splitlines()[0]
            print(f"OK   {query:32s} {first}")
            for extra in res.error.splitlines()[1:]:
                if extra.strip():
                    print(f"       {extra}")
            ok += 1
        else:
            print(f"NG   {query:32s} 理由が想定と違います")
            print(f"       期待した語: {fragment}")
            print(f"       実際: {res.error.splitlines()[0]}")
            ng += 1

    print()
    print("=" * 78)
    print("表記が違っても同じ座標に行き着くか")
    print("=" * 78)
    for a, b in PAIRS:
        ra, rb = results.get(a), results.get(b)
        if not ra or not rb:
            print(f"     {a} / {b}: どちらかが解決できず確認できません")
            continue
        if ra == rb:
            print(f"OK   {a:32s} = {b:28s} {sorted(ra)}")
            ok += 1
        else:
            print(f"NG   {a:32s} ≠ {b:28s} {sorted(ra)} vs {sorted(rb)}")
            ng += 1

    print()
    print("=" * 78)
    print("AlphaMissense への対応づけ")
    print("=" * 78)
    if not avail["alphamissense"]:
        print("  AlphaMissense の索引がないため確認できません")
    else:
        con = store.con
        mane = store._glob(store.p.mane)
        n_genes = con.execute(
            f"SELECT count(DISTINCT gene) FROM {mane}").fetchone()[0]

        if store._ready(store.p.transcript_map):
            tm = store._glob(store.p.transcript_map)
            mapped, exact = con.execute(
                f"""SELECT count(DISTINCT gene),
                           count(DISTINCT gene) FILTER (WHERE id_matches)
                    FROM {tm}"""
            ).fetchone()
            print(f"  MANE の {n_genes:,} 遺伝子のうち {mapped:,} 件 "
                  f"({100 * mapped / n_genes:.1f}%) を対応表で解決できます")
            print(f"  うち転写産物 ID がそのまま一致するのは {exact:,} 件 "
                  f"({100 * exact / mapped:.1f}%)")
            print(f"  残る {n_genes - mapped:,} 遺伝子は"
                  "ゲノム領域での探索に回ります（やや遅くなります）")
        else:
            am = store._glob(store.p.alphamissense)
            covered = con.execute(
                f"""SELECT count(DISTINCT m.gene) FROM {mane} m
                    WHERE m.enst IN (SELECT DISTINCT enst FROM {am})"""
            ).fetchone()[0]
            print(f"  対応表が未作成です。転写産物 ID の直接一致のみで "
                  f"{covered:,} / {n_genes:,} 遺伝子 "
                  f"({100 * covered / n_genes:.1f}%)")
            print("  python scripts/02_build_index.py transcript_map "
                  "で対応表を作ると改善します")

    if timings:
        print()
        print("=" * 78)
        print("1 件あたりの所要時間")
        print("=" * 78)
        ordered = sorted(timings)
        print(f"  中央値 {ordered[len(ordered) // 2]:.2f} 秒　"
              f"最短 {ordered[0]:.2f} 秒　最長 {ordered[-1]:.2f} 秒")
        if ordered[len(ordered) // 2] > 3:
            print("  1 件に 3 秒以上かかっています。画面の応答が鈍く感じられます。")

    print()
    print(f"結果: OK {ok} / 注意 {warn} / NG {ng}")
    return 0 if ng == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
