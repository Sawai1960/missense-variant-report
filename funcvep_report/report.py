"""集めた証拠を 1 枚のレポートにまとめる。

このモジュールは判定を下さない。各指標を並べ、指標同士が一致しているかどうかを
示すところまでを担う。最終的な解釈は人が行う。

利用者に見せる文字列はすべて i18n.t() を通す。言語は呼び出し側が
i18n.use_lang() / set_lang() で決め、Report.lang に記録される。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from .acmg import Assignment, assign, binary_cutoff
from .config import FUNCVEP_MODELS
from .i18n import get_lang, has, join, t
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
_MISSING_STATUSES = ("blank", "absent", "absent_unexplained", "unknown")


def missing_label(status: str) -> str:
    """スコア欄に出す短いラベル。"""
    key = status if status in _MISSING_STATUSES else "default"
    return t(f"missing_label.{key}")


def missing_note(status: str, train_models: list[str] | None) -> str:
    """未収録の注記。どのモデルの学習に使われたかが分かる場合は付け足す。"""
    if status == "scored":
        return ""
    note = t(f"missing_note.{status}") if status in _MISSING_STATUSES else ""
    if train_models:
        note += t("trained_models",
                  models=join(m.replace("_", "-") for m in train_models))
    return note


def model_note(model: str) -> str:
    return t(f"model_note.{model}")


def disclaimer() -> list[str]:
    return [t(f"disclaimer.{i}") for i in (1, 2, 3, 4)]


def funcvep_intro() -> str:
    """FuncVEP 欄の冒頭に置く、論文の要点の説明。"""
    return t("intro.funcvep")


# 参考文献。並び順は本文での登場順（FuncVEP → 判定基準 → 他ツール → 基準）。
_REFERENCE_KEYS = (
    "ref.funcvep", "ref.thresholds", "ref.tiers", "ref.pejaver", "ref.acmg",
    "ref.alphamissense", "ref.revel", "ref.clinvar", "ref.gnomad",
)


def references() -> list[str]:
    return [t(k) for k in _REFERENCE_KEYS]


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
    concordance_rows: list[Row] = field(default_factory=list)


@dataclass
class Report:
    query: str
    created: str
    gene: str | None
    ensg: str | None
    lang: str = "ja"
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
        return t("dash")
    try:
        f = float(x)
    except (TypeError, ValueError):
        return str(x)
    if f != f:                      # NaN
        return t("dash")
    return f"{f:.{digits}f}"


def _phenotypes(raw: str | None, limit: int = 6) -> str:
    """ClinVar の表現型欄を読みやすく整える。

    元は縦棒区切りで、同義語や 'not provided' が並ぶことが多い。
    重複を除いて数を絞る。
    """
    if not raw:
        return t("dash")
    seen: list[str] = []
    for part in str(raw).split("|"):
        p = part.strip()
        if not p or p.lower() in ("not provided", "not specified", "-"):
            continue
        if p not in seen:
            seen.append(p)
    if not seen:
        return t("phenotypes.none")
    shown = join(seen[:limit])
    if len(seen) > limit:
        shown += t("phenotypes.more", n=len(seen) - limit)
    return shown


def _gloss(term: str | None, seen: set[str]) -> str:
    """判定語（Damaging など）の初回出現にだけ和訳を添える。日本語版のみ。"""
    if term is None:
        return t("dash")
    key = f"gloss.{term}"
    if get_lang() != "ja" or term in seen or not has(key):
        return term
    seen.add(term)
    return t(key)


def _call(score: float | None, cutoff: float,
          hi: str = "Damaging", lo: str = "Neutral") -> str:
    if score is None:
        return t("dash")
    return hi if score >= cutoff else lo


def build(res: Resolution, thresholds: dict | None,
          gnomad_af: float | None = None,
          gnomad_hom: int | None = None,
          threshold_note: str = "") -> Report:
    wide = t("sep.wide")
    seen_terms: set[str] = set()
    rep = Report(
        query=res.query,
        created=datetime.now().strftime("%Y-%m-%d %H:%M"),
        gene=res.gene,
        ensg=res.ensg,
        lang=get_lang(),
        warnings=list(res.warnings),
        error=res.error,
        threshold_note=threshold_note,
    )
    if res.error:
        return rep

    # --- 遺伝子レベル ---
    gene_value = t("gene_value", gene=res.gene, ensg=res.ensg)
    if res.constraint:
        c = res.constraint
        rep.gene_rows = [
            Row(t("row.gene"), gene_value),
            Row("pLI", _fmt(c.get("pLI"), 3), t("note.pli")),
            Row("missense z", _fmt(c.get("mis_z"), 2), t("note.mis_z")),
            Row("LoF z", _fmt(c.get("lof_z"), 2), t("note.lof_z")),
        ]
    else:
        rep.gene_rows = [Row(t("row.gene"), gene_value)]

    # --- 集団頻度（手入力または API） ---
    if gnomad_af is not None:
        rep.population_rows.append(
            Row(t("row.af"), f"{gnomad_af:.3e}", t("note.af"))
        )
        if gnomad_hom is not None:
            rep.population_rows.append(
                Row(t("row.hom"), str(gnomad_hom), t("note.hom"))
            )
    else:
        rep.population_rows.append(
            Row(t("row.af"), t("af.not_entered"), t("note.af_not_entered"))
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
                value = t("dash")
                head = missing_label(vr.funcvep_status)
            else:
                value = (f"{_fmt(score)}{wide}"
                         f"{_gloss(_call(score, binary_cutoff(model, thresholds)), seen_terms)}")
                head = a.label if a else t("uncalibrated")
            vr.predictions.append(
                Row(model.replace("_", "-"), value, head + "｜" + model_note(model))
            )

        clin_scores = {k: v for k, v in ev.funcvep.items() if k.startswith("ClinVEP")}
        clin_trained = [m for m in (ev.train_models or []) if m.startswith("ClinVEP")]
        if clin_scores:
            vr.others.append(
                Row(
                    t("row.clinvep"),
                    " / ".join(f"{k.split('_')[1]} {_fmt(v)}"
                               for k, v in clin_scores.items()),
                    t("note.clinvep"),
                )
            )
        elif clin_trained:
            # 対照が引けないのは、その変異が ClinVEP の学習に使われたから。
            # 空欄の理由を書かないと「対照が壊れている」と誤読されうる。
            vr.others.append(
                Row(
                    t("row.clinvep"), t("dash"),
                    t("note.clinvep_trained",
                      models=join(m.replace("_", "-") for m in clin_trained)),
                )
            )

        vr.others.append(
            Row("AlphaMissense",
                f"{_fmt(ev.am_score)}{wide}{_gloss(ev.am_class, seen_terms)}" if ev.am_score is not None
                else t("dash"),
                t("note.alphamissense"))
        )
        vr.others.append(
            Row("REVEL",
                f"{_fmt(ev.revel)}{wide}{_gloss(_call(ev.revel, REVEL_CUTOFF), seen_terms)}"
                if ev.revel is not None else t("dash"),
                t("note.revel", cutoff=REVEL_CUTOFF))
        )

        # --- ClinVar ---
        if ev.clinvar:
            cv = ev.clinvar
            stars = clinvar_stars(cv.get("review_status"))
            vr.clinvar_rows = [
                Row(t("row.significance"), str(cv.get("significance") or t("dash")),
                    t("note.review", stars=stars, status=cv.get("review_status"))),
                Row(t("row.submitters"), str(cv.get("n_submitters") or t("dash")), ""),
                Row(t("row.last_evaluated"), str(cv.get("last_evaluated") or t("dash")), ""),
                Row(t("row.phenotypes"), _phenotypes(cv.get("phenotypes")), ""),
                Row(t("row.clinvar_name"), str(cv.get("name") or t("dash"))[:200],
                    t("note.variation_id", id=cv.get("variation_id"))),
            ]
        else:
            vr.clinvar_rows = [
                Row(t("row.significance"), t("clinvar.none"), t("note.clinvar_none"))
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
            vr.concordance = t("conc.none")
        elif n_tot == 1:
            vr.concordance = t("conc.single_damaging" if n_dmg else "conc.single_neutral")
        elif n_dmg == n_tot:
            vr.concordance = t("conc.all_damaging", n=n_tot)
        elif n_dmg == 0:
            vr.concordance = t("conc.all_neutral", n=n_tot)
        else:
            vr.concordance = t("conc.mixed", n=n_tot, d=n_dmg)
        # 縦に並べる: damaging 側 / neutral 側 / 要約
        if decided:
            dmg = [k.replace("_", "-") for k, v in decided.items() if v]
            neu = [k.replace("_", "-") for k, v in decided.items() if not v]
            vr.concordance_rows = [
                Row(t("row.damaging_side"), join(dmg) or t("conc.no_tool")),
                Row(t("row.neutral_side"), join(neu) or t("conc.no_tool")),
            ]
        vr.concordance_rows.append(Row(t("row.summary"), vr.concordance))

        rep.variants.append(vr)

    return rep
