"""集めた証拠を 1 枚のレポートにまとめる。

このモジュールは判定を下さない。各指標を並べ、指標同士が一致しているかどうかを
示すところまでを担う。最終的な解釈は人が行う。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from .acmg import Assignment, assign, binary_cutoff
from .config import FUNCVEP_MODELS
from .lookup import ResolvedVariant, Resolution, clinvar_stars

# FuncVEP のスコアを二値にするときの境。論文はモデルごとに異なる値を与えており
# （Supplementary Table 13 の binary 列）、0.5 ではない。公表値が無いときの保険。
DAMAGING_CUTOFF = 0.5
# REVEL の慣用的な境。REVEL 論文の推奨に近い中庸な値を使う。
REVEL_CUTOFF = 0.5

# スコアが出ない理由。著者（Kayaalp ら, 2026-09-05 / 2026-09-07 私信）による。
#   空欄  一部のモデルの学習に使われた。行はあるがその列が空。
#   未収録 6 モデル全部の学習に使われた。全モデルの推論から除かれ、行ごと消える。
#   学習セット外の未収録は、著者が内部ファイルと照合済み。注釈差（当方の
#   ミスセンスが公開用データセットでは stop-gain/loss 扱い）、元集合に不在、
#   特徴量行列への伝播漏れ、のいずれかで、個別にどれかは公開情報からは分からない。
# いずれも生物学的・配列的・QC 上の除外ではない。したがって収録が無いこと自体は
# 病原性についても予測の信頼度についても情報を持たない。ここを取り違えると、
# 「予測できないほど珍しい変異」と誤読されうる。
FUNCVEP_MISSING_LABEL = {
    "blank": "学習に使われたため非公開",
    "absent": "学習に使われたため未収録",
    "absent_unexplained": "予測表に未収録（作成工程の都合。著者確認済み）",
    "unknown": "FuncVEP の索引なし",
}

_NO_INFO = (
    "スコアが得られないこと自体は、病原性についても予測の信頼度についても"
    "何ら情報を持たない（著者私信）。AlphaMissense・REVEL・ClinVar の側で"
    "判断すること。"
)
FUNCVEP_MISSING_NOTE = {
    "blank": "この変異は一部のモデルの学習に使われたため、そのモデルのスコアが"
             "公開されていない。「予測できなかった」ではない。" + _NO_INFO,
    "absent": "この変異は 6 モデル全部の学習に使われたため、全モデルの推論から"
              "除かれ、公開予測表から行ごと消えている。" + _NO_INFO,
    "absent_unexplained": "この変異は公開予測表に無く、公開されている学習セットにも"
                          "見当たらない。著者の照合（2026-09-07 私信）によれば、"
                          "この種の未収録は予測表の作成工程に由来する"
                          "（注釈の違いによる除外・元データに不在・処理漏れの"
                          "いずれか）。" + _NO_INFO,
    "unknown": "FuncVEP の索引がないため照会できない。",
}


def missing_note(status: str, train_models: list[str] | None) -> str:
    """未収録の注記。どのモデルの学習に使われたかが分かる場合は付け足す。"""
    if status == "scored":
        return ""
    note = FUNCVEP_MISSING_NOTE.get(status, "")
    if train_models:
        note += "　学習に使ったモデル: " + "、".join(
            m.replace("_", "-") for m in train_models
        )
    return note


MODEL_NOTE = {
    "FuncVEP_CTI": "臨床学習済み予測器を特徴量に含む。ベンチマーク最良だが循環参照の risk が最も高い",
    "FuncVEP_CTE": "臨床学習済み予測器を除外。ClinVar との独立性が高い",
    "FuncVEP_SP": "他の予測器を一切使わない。最も独立だが単独性能は劣る",
    "ClinVEP_CTI": "同じ特徴量を ClinVar ラベルで学習した対照モデル",
    "ClinVEP_CTE": "同上（臨床学習済み予測器を除外）",
    "ClinVEP_SP": "同上（他の予測器を使わない）",
}


@dataclass
class Row:
    label: str
    value: str
    note: str = ""


@dataclass
class VariantReport:
    variant: ResolvedVariant
    funcvep_status: str = "scored"
    funcvep_note: str = ""
    predictions: list[Row] = field(default_factory=list)
    acmg: dict[str, Assignment | None] = field(default_factory=dict)
    others: list[Row] = field(default_factory=list)
    clinvar_rows: list[Row] = field(default_factory=list)
    concordance: str = ""
    concordance_detail: str = ""


@dataclass
class Report:
    query: str
    created: str
    gene: str | None
    ensg: str | None
    variants: list[VariantReport] = field(default_factory=list)
    gene_rows: list[Row] = field(default_factory=list)
    population_rows: list[Row] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    error: str | None = None
    threshold_note: str = ""


def _fmt(x, digits: int = 3) -> str:
    """数値なら桁を揃えて、そうでなければそのまま。欠測は長音符。

    索引の型が想定と違っても表示だけで落ちないようにしておく。
    """
    if x is None:
        return "—"
    try:
        f = float(x)
    except (TypeError, ValueError):
        return str(x)
    if f != f:                      # NaN
        return "—"
    return f"{f:.{digits}f}"


def _phenotypes(raw: str | None, limit: int = 6) -> str:
    """ClinVar の表現型欄を読みやすく整える。

    元は縦棒区切りで、同義語や 'not provided' が並ぶことが多い。
    重複を除いて数を絞る。
    """
    if not raw:
        return "—"
    seen: list[str] = []
    for part in str(raw).split("|"):
        p = part.strip()
        if not p or p.lower() in ("not provided", "not specified", "-"):
            continue
        if p not in seen:
            seen.append(p)
    if not seen:
        return "記載なし"
    shown = "、".join(seen[:limit])
    if len(seen) > limit:
        shown += f"　ほか {len(seen) - limit} 件"
    return shown


def _call(score: float | None, cutoff: float,
          hi: str = "Damaging", lo: str = "Neutral") -> str:
    if score is None:
        return "—"
    return hi if score >= cutoff else lo


def build(res: Resolution, thresholds: dict | None,
          gnomad_af: float | None = None,
          gnomad_hom: int | None = None,
          threshold_note: str = "") -> Report:
    rep = Report(
        query=res.query,
        created=datetime.now().strftime("%Y-%m-%d %H:%M"),
        gene=res.gene,
        ensg=res.ensg,
        warnings=list(res.warnings),
        error=res.error,
        threshold_note=threshold_note,
    )
    if res.error:
        return rep

    # --- 遺伝子レベル ---
    if res.constraint:
        c = res.constraint
        rep.gene_rows = [
            Row("遺伝子", f"{res.gene}（{res.ensg}）"),
            Row("pLI", _fmt(c.get("pLI"), 3),
                "1 に近いほど機能喪失変異に不寛容"),
            Row("missense z", _fmt(c.get("mis_z"), 2),
                "正で大きいほどミスセンス変異に不寛容"),
            Row("LoF z", _fmt(c.get("lof_z"), 2), ""),
        ]
    else:
        rep.gene_rows = [Row("遺伝子", f"{res.gene}（{res.ensg}）")]

    # --- 集団頻度（手入力または API） ---
    if gnomad_af is not None:
        rep.population_rows.append(
            Row("gnomAD アレル頻度", f"{gnomad_af:.3e}",
                "0.01 を超えるなら BA1、疾患頻度に照らして高いなら BS1 を検討")
        )
        if gnomad_hom is not None:
            rep.population_rows.append(
                Row("ホモ接合体数", str(gnomad_hom),
                    "常染色体劣性疾患で 0 でないなら BS2 を検討")
            )
    else:
        rep.population_rows.append(
            Row("gnomAD アレル頻度", "未入力",
                "検査報告書の値を画面で入力すると表示されます")
        )

    # --- 変異ごと ---
    for rv in res.variants:
        vr = VariantReport(variant=rv)
        ev = rv.evidence

        vr.funcvep_status = ev.funcvep_status
        vr.funcvep_note = missing_note(vr.funcvep_status, ev.train_models)

        for model in FUNCVEP_MODELS:
            score = ev.funcvep.get(model)
            a = assign(score, model, thresholds)
            vr.acmg[model] = a
            if score is None:
                value = "—"
                head = FUNCVEP_MISSING_LABEL.get(vr.funcvep_status, "スコアなし")
            else:
                value = f"{_fmt(score)}　{_call(score, binary_cutoff(model, thresholds))}"
                head = a.label if a else "PP3/BP4 未較正"
            vr.predictions.append(
                Row(model.replace("_", "-"), value, head + "｜" + MODEL_NOTE[model])
            )

        clin_scores = {k: v for k, v in ev.funcvep.items() if k.startswith("ClinVEP")}
        clin_trained = [m for m in (ev.train_models or []) if m.startswith("ClinVEP")]
        if clin_scores:
            vr.others.append(
                Row(
                    "ClinVEP（対照）",
                    " / ".join(f"{k.split('_')[1]} {_fmt(v)}"
                               for k, v in clin_scores.items()),
                    "同じ特徴量を ClinVar ラベルで学習した対照。FuncVEP と大きく食い違う場合は"
                    "機能的影響と臨床的病原性が乖離している可能性",
                )
            )
        elif clin_trained:
            # 対照が引けないのは、その変異が ClinVEP の学習に使われたから。
            # 空欄の理由を書かないと「対照が壊れている」と誤読されうる。
            vr.others.append(
                Row(
                    "ClinVEP（対照）", "—",
                    "この変異は " + "、".join(m.replace("_", "-") for m in clin_trained)
                    + " の学習に使われたため、対照のスコアは公開されていない",
                )
            )

        vr.others.append(
            Row("AlphaMissense", f"{_fmt(ev.am_score)}　{ev.am_class or '—'}",
                "CC BY-NC-SA 4.0 / 集団頻度で弱ラベル付けした半教師あり学習")
        )
        vr.others.append(
            Row("REVEL", f"{_fmt(ev.revel)}　{_call(ev.revel, REVEL_CUTOFF)}",
                f"{REVEL_CUTOFF} を境とした慣用的な二値判定")
        )

        # --- ClinVar ---
        if ev.clinvar:
            cv = ev.clinvar
            stars = clinvar_stars(cv.get("review_status"))
            vr.clinvar_rows = [
                Row("臨床的意義", str(cv.get("significance") or "—"),
                    f"レビュー {stars} 星（{cv.get('review_status')}）"),
                Row("提出者数", str(cv.get("n_submitters") or "—"), ""),
                Row("最終評価", str(cv.get("last_evaluated") or "—"), ""),
                Row("表現型", _phenotypes(cv.get("phenotypes")), ""),
                Row("ClinVar 表記", str(cv.get("name") or "—")[:200],
                    f"VariationID {cv.get('variation_id')}"),
            ]
        else:
            vr.clinvar_rows = [
                Row("臨床的意義", "ClinVar に登録なし",
                    "新規変異、あるいは未提出の変異である可能性")
            ]

        # --- 指標同士の一致 ---
        calls: dict[str, bool | None] = {}
        for model in FUNCVEP_MODELS:
            s = ev.funcvep.get(model)
            calls[model] = None if s is None else s >= binary_cutoff(model, thresholds)
        if ev.am_class:
            calls["AlphaMissense"] = (
                True if ev.am_class == "likely_pathogenic"
                else False if ev.am_class == "likely_benign" else None
            )
        if ev.revel is not None:
            calls["REVEL"] = ev.revel >= REVEL_CUTOFF

        decided = {k: v for k, v in calls.items() if v is not None}
        n_dmg = sum(1 for v in decided.values() if v)
        n_tot = len(decided)
        if n_tot == 0:
            vr.concordance = "判定できる指標がありません"
        elif n_dmg == n_tot:
            vr.concordance = f"{n_tot} 指標すべてが damaging 側"
        elif n_dmg == 0:
            vr.concordance = f"{n_tot} 指標すべてが neutral 側"
        else:
            vr.concordance = f"{n_tot} 指標中 {n_dmg} が damaging 側（不一致）"
        vr.concordance_detail = "　".join(
            f"{k}:{'D' if v else 'N'}" for k, v in decided.items()
        )

        rep.variants.append(vr)

    return rep


DISCLAIMER = [
    "FuncVEP が予測するのはタンパク質の機能への影響（damaging / neutral）であり、"
    "臨床的病原性そのものではない。両者を混同しないこと。",
    "ACMG/AMP 基準では計算による証拠 PP3/BP4 として扱う。機能実験の証拠 PS3/BS3 ではない。",
    "対象はミスセンス変異のみ。スプライスへの影響、フレームシフト、ナンセンス変異は評価されない。",
    "本レポートは変異解釈の補助資料であり、単独で臨床判断の根拠としてはならない。"
    "家系内分離、表現型の一致、機能実験、専門家の検討と併せて評価すること。",
]
