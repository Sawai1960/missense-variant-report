"""集めた証拠を 1 枚のレポートにまとめる。

このモジュールは判定を下さない。各指標を並べ、指標同士が一致しているかどうかを
示すところまでを担う。最終的な解釈は人が行う。

利用者に見せる文字列はすべて i18n.t() を通す。言語は呼び出し側が
i18n.use_lang() / set_lang() で決め、Report.lang に記録される。
"""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from datetime import datetime

from .acmg import Assignment, assign, binary_cutoff
from .config import FUNCVEP_MODELS
from .i18n import get_lang, has, join, t
from .clingen import GeneDisease
from .clinvar_api import ConditionResult, is_generic_condition
from .gnomad import GnomadResult
from .mavedb import MaveResult
from .spliceai import SpliceResult
from .togovar import JapanResult
from .lookup import ResolvedVariant, Resolution, clinvar_stars
from .variant import AA1_TO_3

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


def acknowledgement() -> str:
    return t("ack.text")


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
    # damaging / neutral / mixed / none。まとめの箱の色分けに使う
    concordance_kind: str = "none"
    population_rows: list[Row] = field(default_factory=list)
    gnomad: GnomadResult | None = None
    japan: JapanResult | None = None
    residue_rows: list[Row] = field(default_factory=list)
    splice: SpliceResult | None = None
    mave_rows: list[Row] = field(default_factory=list)
    conditions: ConditionResult | None = None
    adopted_model: str | None = None      # PP3/BP4 に採用したモデル（代替を含む）
    adoption_note: str = ""


@dataclass
class Report:
    query: str
    created: str
    gene: str | None
    ensg: str | None
    lang: str = "ja"
    organization: str = ""
    variants: list[VariantReport] = field(default_factory=list)
    gene_rows: list[Row] = field(default_factory=list)
    target_rows: list[Row] = field(default_factory=list)
    provenance_rows: list[Row] = field(default_factory=list)
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


def _constraint(x, digits: int, cutoff: float, high_key: str, low_key: str) -> str:
    """制約指標の値に、閾値で分けた一言を添える。数値でなければ値だけ。"""
    shown = _fmt(x, digits)
    try:
        f = float(x)
    except (TypeError, ValueError):
        return shown
    if f != f:
        return shown
    label = t(high_key) if f >= cutoff else t(low_key)
    return f"{shown}{t('sep.wide')}{label}"


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


def _japan_rows(j: JapanResult | None, retrieved: str) -> list[Row]:
    """TogoVar 経由の日本人集団の頻度。"""
    if j is None or j.status == "error":
        reason = j.reason if j else "not queried"
        return [Row(t("row.japan"), t("af.failed"), t("note.japan_failed", reason=reason))]
    if j.status == "absent":
        return [Row(t("row.japan"), t("japan.absent"), t("note.japan_absent", retrieved=retrieved))]
    def item(s) -> str:
        out = t("japan.item", label=s.label, af=f"{s.af:.3e}", ac=f"{s.ac:,}", an=f"{s.an:,}")
        if s.hom is not None:
            out += t("japan.hom", hom=f"{s.hom:,}")
        return out

    # 一般集団の参照は ToMMo 54KJPN。患者由来・研究コホートは「参考」として分けて示す
    ref, extra = j.reference, j.supplementary
    value = t("sep.list").join(item(s) for s in ref) if ref else t("japan.ref_absent")
    if extra:
        value += t("japan.supplementary", items=t("sep.list").join(item(s) for s in extra))
    if any(s.af > 0.05 for s in ref):
        value += t("sep.wide") + t("af.ba1")
    note = t("note.japan", retrieved=retrieved)
    if not ref and extra:
        note += t("note.japan_supplementary_only")
    return [Row(t("row.japan"), value, note)]


def _population_rows(g: GnomadResult | None, online: bool, retrieved: str,
                     j: JapanResult | None = None) -> list[Row]:
    """gnomAD の照会結果を、記録あり／記録なし／取得できず／未照会で書き分ける。"""
    if not online:
        return [Row(t("row.af"), t("af.offline"), t("note.af_offline"))]
    return _gnomad_rows(g, retrieved) + _japan_rows(j, retrieved)


def _gnomad_rows(g: GnomadResult | None, retrieved: str) -> list[Row]:
    if g is None or g.status == "error":
        reason = g.reason if g else "not queried"
        return [Row(t("row.af"), t("af.failed"), t("note.af_failed", reason=reason))]
    if g.status == "absent":
        depth = f"{g.depth_mean:.0f}" if g.depth_mean is not None else t("dash")
        frac = f"{g.over_20:.0%}" if g.over_20 is not None else t("dash")
        if g.well_covered is None:
            key = "note.af_absent_nocov"
        elif g.well_covered:
            key = "note.af_absent"
        else:
            key = "note.af_absent_lowcov"
        return [Row(t("row.af"), t("af.absent"),
                    t(key, retrieved=retrieved, depth=depth, frac=frac))]
    value = t("af.value", af=f"{g.af:.3e}", ac=f"{g.ac:,}", an=f"{g.an:,}")
    if g.filters:
        value += t("af.filtered", filters=", ".join(g.filters))
    rows = [Row(t("row.af"), value, t("note.af", retrieved=retrieved))]
    # BA1/BS1 は集団別の最大頻度で見る。0.05 超は「候補」に留める（疾患別の例外は未確認）
    if g.grpmax_an:
        gm = t("af.value", af=f"{g.grpmax_af:.3e}", ac=f"{g.grpmax_ac:,}", an=f"{g.grpmax_an:,}")
        if g.grpmax_af > 0.05:
            gm += t("sep.wide") + t("af.ba1")
        rows.append(Row(t("row.grpmax", pop=t(f"pop.{g.grpmax_id}") if has(f"pop.{g.grpmax_id}") else g.grpmax_id),
                        gm, t("note.grpmax")))
    elif g.af > 0.05:
        rows[0] = Row(t("row.af"), value + t("sep.wide") + t("af.ba1"), t("note.af", retrieved=retrieved))
    rows.append(Row(t("row.hom"), f"{g.hom:,}", t("note.hom")))
    if g.eas_an:
        if g.eas_ac:
            eas = t("af.value", af=f"{g.eas_af:.3e}", ac=f"{g.eas_ac:,}", an=f"{g.eas_an:,}")
            if g.eas_hom:
                eas += t("japan.hom", hom=f"{g.eas_hom:,}")
        else:
            eas = t("af.zero", an=f"{g.eas_an:,}")
        rows.append(Row(t("row.eas"), eas, t("note.eas")))
    return rows


_DISEASE_STOPWORDS = {"and", "of", "the", "with", "disease", "diseases", "disorder",
                      "disorders", "syndrome", "related", "type", "form", "familial"}


def _disease_tokens(s: str, gene: str | None = None) -> list[str]:
    """疾患名を照合用の語に分ける。

    大文字小文字と記号を無視し、"obsolete" の接頭辞、遺伝子記号、短い大文字の略号
    （HBB/LCRB のような座位の注記）、一般語（disease, syndrome など）を除く。
    """
    s = re.sub(r"^obsolete\s+", "", (s or "").strip(), flags=re.I)
    out = []
    for raw in re.split(r"[^A-Za-z0-9]+", s):
        if not raw:
            continue
        if gene and raw.lower() == gene.lower():
            continue
        if raw.isalpha() and raw.isupper() and 3 <= len(raw) <= 5:
            continue
        w = raw.lower()
        if w in _DISEASE_STOPWORDS:
            continue
        out.append(w)
    return out


def matches_phenotype(disease: str, phenotypes: list[str], gene: str | None = None) -> bool:
    """ClinGen の疾患名が、この変異の ClinVar 表現型のどれかと一致するか。

    疾患名の語がすべて表現型の語に（前方一致で）含まれるときに一致とみなす。
    "type 2" と "type 2E" のような枝番の違いは前方一致で吸収する。
    """
    want = _disease_tokens(disease, gene)
    if not want:
        return False
    for ph in phenotypes:
        have = _disease_tokens(ph, gene)
        if all(any(h.startswith(w) for h in have) for w in want):
            return True
    return False


def primary_phenotype(raw: str | None) -> str | None:
    """ClinVar の表現型欄の筆頭の疾患名。

    欄には各提出者の疾患名がすべて並び、遺伝子パネル由来の疾患も混じる。総称
    （not provided、N conditions、○○-related disorder、セミコロン区切りの一覧）を
    除いた最初のものを、この変異の主な疾患とみなす。
    """
    for part in str(raw or "").split("|"):
        p = part.strip()
        if not p or is_generic_condition(p):
            continue
        return p
    return None


def _condition_row(c: ConditionResult, fallback_raw: str | None, limit: int = 6) -> Row:
    """ClinVar の疾患名の行。提出件数が取れていれば件数順に、無ければ索引の一覧で。"""
    rows = c.specific if c and c.status == "found" else []
    if not rows:
        return Row(t("row.phenotypes"), _phenotypes(fallback_raw), t("note.phenotypes"))
    items = [t("cond.item", name=r.condition, cls=r.classification or t("dash"),
               n=r.submissions, stars=clinvar_stars(r.review_status)) for r in rows[:limit]]
    value = t("sep.list").join(items)
    if len(rows) > limit:
        value += t("phenotypes.more", n=len(rows) - limit)
    return Row(t("row.conditions"), value, t("note.conditions"))


def _moi_row(c: ConditionResult | None) -> list[Row]:
    """提出者が記入した遺伝形式の集計（参考）。記入が無ければ出さない。"""
    if not c or c.status != "found" or not c.moi:
        return []
    items = [t("moi.item", code=t("moi.unknown") if code == "unknown" else
               t("moi.somatic") if code == "somatic" else code, n=n)
             for code, n in c.moi.items()]
    filled = sum(c.moi.values())
    return [Row(t("row.moi"), t("sep.list").join(items) + t("moi.summary", filled=filled, total=c.n_scv),
                t("note.moi"))]


def _clingen_rows(gene_validity: list[GeneDisease] | None, retrieved: str,
                  phenotypes: list[str] | None = None) -> list[Row]:
    """ClinGen の遺伝子と疾患の関係（遺伝子単位）。一覧そのものが無ければ何も出さない。

    この変異の ClinVar 表現型と一致する疾患は先頭に置いて印を付ける。
    """
    if gene_validity is None:
        return []
    if not gene_validity:
        return [Row(t("row.clingen"), t("clingen.none"), t("note.clingen_none"))]
    lang = get_lang()
    phenotypes = phenotypes or []
    gene = gene_validity[0].gene if gene_validity else None
    matched = [g for g in gene_validity if matches_phenotype(g.disease, phenotypes, gene)]
    others = [g for g in gene_validity if g not in matched]
    items = [t("clingen.item", disease=g.disease, moi=g.moi, cls=g.classification, date=g.date)
             + t("clingen.match", pheno=phenotypes[0]) for g in matched]
    items += [t("clingen.item", disease=g.disease, moi=g.moi, cls=g.classification, date=g.date)
              for g in others]
    sep = "；" if lang == "ja" else "; "
    return [Row(t("row.clingen"), sep.join(items), t("note.clingen", retrieved=retrieved))]


def _splice_row(s: SpliceResult | None, online: bool) -> Row:
    if not online:
        return Row("SpliceAI", t("af.offline"), t("note.spliceai"))
    if s is None or s.status == "error":
        reason = s.reason if s else "not queried"
        return Row("SpliceAI", t("af.failed"), t("note.spliceai_failed", reason=reason))
    if s.status != "scored":
        return Row("SpliceAI", t("splice.none"), t("note.spliceai_none"))
    kind = t(f"splice.kind.{s.max_type}")
    value = t("splice.value", ds=f"{s.max_ds:.2f}", kind=kind, dp=s.dp[s.max_type])
    value += t("sep.wide") + t(f"splice.level.{s.level}")
    return Row("SpliceAI", value, t("note.spliceai"))


def _mave_rows(m: MaveResult | None, online: bool) -> list[Row]:
    """機能実験の実測値。実験データセットの無い遺伝子では節ごと出さない。"""
    if not online or m is None or m.status == "no_dataset":
        return []
    if m.status == "error":
        return [Row(t("row.mave"), t("af.failed"), t("note.mave_failed", reason=m.reason))]
    if m.status == "no_match":
        return [Row(t("row.mave"), t("mave.no_match", n=m.n_score_sets), t("note.mave_no_match"))]
    rows = []
    for h in m.hits:
        ss = h.score_set
        if h.functional_class is not None:
            fc = h.functional_class
            label = t(f"mave.class.{fc.classification}") if fc.classification in ("normal", "abnormal") else fc.label
            value = f"{h.score:.3f}{t('sep.wide')}{label}"
        else:
            value = f"{h.score:.3f}{t('sep.wide')}{t('mave.class.uncalibrated')}"
        value += t("sep.wide") + (t("mave.match_nt", acc=h.nt_accession or ss.target_accession or t("dash"))
                                  if h.match == "nt" else t("mave.match_aa"))
        note = t("note.mave", urn=ss.urn, citation=ss.citation or t("dash"),
                 n=f"{ss.num_variants:,}" if ss.num_variants else t("dash"),
                 target=ss.target_accession or t("dash"))
        if ss.calibration_title:
            note += t("note.mave_calibration", title=ss.calibration_title)
        if not ss.full_length_numbering:
            note += t("note.mave_numbering")
        note += t("note.mave_ps3")
        rows.append(Row(ss.title[:80], value, note))
    return rows


def _qualify_bp4(label: str, splice, online: bool) -> str:
    """BP4（良性方向の予測）に、スプライシングの評価状況を添える（レビュー対応 5）。

    Δ 0.5 以上: BP4 を保留する。0.2 以上 0.5 未満: 要確認。未取得: 未評価と明記する。
    """
    if not online or splice is None or splice.status != "scored":
        return label + t("acmg.bp4_unassessed")
    if splice.level == "high":
        return t("acmg.bp4_held", ds=f"{splice.max_ds:.2f}")
    if splice.level == "moderate":
        return label + t("acmg.bp4_check", ds=f"{splice.max_ds:.2f}")
    return label


def provenance_rows(res: Resolution, versions: dict | None, code_version: str,
                    thresholds: dict | None, created: str,
                    adopted: list[str | None], primary_model: str) -> list[Row]:
    """データの版と解決経路（レビュー対応 10）。後日同じ入力で結果が変わったときに理由を追える。"""
    rows: list[Row] = []
    if versions:
        items = []
        for key, v in versions.items():
            if key.startswith("_"):
                continue
            en = get_lang() == "en"
            label = (v.get("label_en") if en else v.get("label")) or v.get("label") or key
            ver = (v.get("version_en") if en else v.get("version")) or v.get("version") or t("dash")
            date = v.get("date") or ""
            items.append(f"{label}: {ver}" + ((f" ({date})" if en else f"（{date}）") if date else ""))
        built = (versions.get("_index") or {}).get("built") or ""
        rows.append(Row(t("row.data_versions"), t("sep.list").join(items),
                        t("note.data_versions", built=built) if built else ""))
    meta = (thresholds or {}).get("meta") or {}
    rows.append(Row(t("row.threshold_version"),
                    t("thr.version_published") if meta.get("source") == "published" else t("thr.version_local"), ""))
    rows.append(Row(t("row.code_version"), code_version or t("dash"), ""))
    rows.append(Row(t("row.online_retrieved"), created, t("note.online_retrieved")))
    if res.resolution_path:
        rows.append(Row(t("row.resolution_path"), t("sep.list").join(res.resolution_path), ""))
    pm = primary_model.replace("_", "-")
    used = [a.replace("_", "-") for a in adopted if a]
    rows.append(Row(t("row.adopted_model"),
                    t("adopt.provenance", model=pm, used=t("sep.list").join(sorted(set(used))) or t("dash")), ""))
    return rows


def _is_plp(sig: str | None) -> bool:
    s = (sig or "").lower()
    return "pathogenic" in s and "conflicting" not in s and "benign" not in s


def _is_blb(sig: str | None) -> bool:
    s = (sig or "").lower()
    return "benign" in s and "conflicting" not in s and "pathogenic" not in s


def _short_name(name: str | None) -> tuple[str, str]:
    """ClinVar の name から c. 表記と p. 表記を取り出す。"""
    name = name or ""
    c = re.search(r"(c\.[^ ()]+)", name)
    pm = re.search(r"\((p\.[^)]+)\)", name)
    return (c.group(1) if c else t("dash")), (pm.group(1) if pm else t("dash"))


def residue_rows(same_residue: list[dict], genomic, aa_alt1: str) -> list[Row]:
    """同じ残基の ClinVar 判定を PS1 / PM5 の観点で並べる。

    same_residue は同じ遺伝子・同じ残基番号の ClinVar 行（aa_alt3 を含む）。
    この変異自身（座標と塩基が同じ行）は除く。同義置換とナンセンスは対象外。
    """
    aa_alt3 = AA1_TO_3.get(aa_alt1, aa_alt1)
    same_change: list[dict] = []
    other_change: list[dict] = []
    for r in same_residue:
        if (str(r.get("chrom")) == str(genomic.chrom) and int(r.get("pos")) == genomic.pos
                and r.get("ref") == genomic.ref and r.get("alt") == genomic.alt):
            continue
        alt3 = r.get("aa_alt3")
        if alt3 in ("=", "Ter", "", None):
            continue
        if not (r.get("significance") or "").strip("- "):
            continue    # 判定の無い行（"-"）は根拠にならないので載せない
        (same_change if alt3 == aa_alt3 else other_change).append(r)

    def item(r: dict) -> str:
        c, pv = _short_name(r.get("name"))
        cond = primary_phenotype(r.get("phenotypes")) or t("dash")
        return t("residue.item", cdna=c, pdot=pv, sig=r.get("significance") or t("dash"),
                 stars=clinvar_stars(r.get("review_status")), cond=cond,
                 date=str(r.get("last_evaluated") or t("dash")))

    def weak(rs: list[dict]) -> bool:
        """病的判定がすべて 1 星以下（単一提出者、基準なし）か。"""
        return bool(rs) and max(clinvar_stars(r.get("review_status")) for r in rs) <= 1

    def order(rs: list[dict]) -> list[dict]:
        return sorted(rs, key=lambda r: (not _is_plp(r.get("significance")),
                                         -clinvar_stars(r.get("review_status"))))

    rows: list[Row] = []
    plp_same = [r for r in same_change if _is_plp(r.get("significance"))]
    intro = t("note.residue_intro")
    sep = "。" if get_lang() == "ja" else ". "
    note1 = intro
    if plp_same:
        note1 += sep + t("note.ps1") + (t("note.residue_weak") if weak(plp_same) else "")
    rows.append(Row(
        t("row.same_change"),
        t("sep.list").join(item(r) for r in order(same_change)) or t("residue.none"),
        note1,
    ))
    plp_other = [r for r in other_change if _is_plp(r.get("significance"))]
    blb_other = [r for r in other_change if _is_blb(r.get("significance"))]
    note = ""
    if plp_other:
        note = t("note.pm5", n=len(plp_other)) + (t("note.residue_weak") if weak(plp_other) else "")
        if blb_other:
            note += t("note.pm5_benign_too", n=len(blb_other))
    elif blb_other:
        note = t("note.residue_benign", n=len(blb_other))
    rows.append(Row(
        t("row.other_change"),
        t("sep.list").join(item(r) for r in order(other_change)) or t("residue.none"),
        note,
    ))
    return rows


def build(res: Resolution, thresholds: dict | None,
          gnomad_af: float | None = None,
          gnomad_hom: int | None = None,
          threshold_note: str = "",
          gnomad_results: dict[str, GnomadResult] | None = None,
          gnomad_online: bool = True,
          japan_results: dict[str, JapanResult] | None = None,
          gene_validity: list[GeneDisease] | None = None,
          splice_results: dict[str, SpliceResult] | None = None,
          mave_result: MaveResult | None = None,
          organization: str = "",
          condition_results: dict[str, ConditionResult] | None = None,
          primary_model: str = "FuncVEP_CTI",
          versions: dict | None = None,
          code_version: str = "") -> Report:
    wide = t("sep.wide")
    seen_terms: set[str] = set()
    rep = Report(
        query=res.query,
        created=datetime.now().strftime("%Y-%m-%d %H:%M"),
        gene=res.gene,
        ensg=res.ensg,
        lang=get_lang(),
        organization=organization,
        warnings=list(res.warnings),
        error=res.error,
        threshold_note=threshold_note,
    )
    if res.error:
        return rep

    # --- 評価対象の変異（冒頭に置く） ---
    for i, rv in enumerate(res.variants, 1):
        label = (t("pdf.variant_n", i=i, n=len(res.variants))
                 if len(res.variants) > 1 else t("pdf.variant"))
        note = t("target.note", refseq=rv.refseq_nuc, enst=rv.enst)
        if res.transcript_note:
            note += wide + res.transcript_note
        if rv.hgvs_c:
            note += wide + rv.hgvs_c
        rep.target_rows.append(Row(
            label,
            t("target.value", gene=rv.gene, hgvs=rv.hgvs_p3, genomic=str(rv.genomic)),
            note,
        ))

    # --- 遺伝子レベル ---
    gene_value = t("gene_value", gene=res.gene, ensg=res.ensg)
    if res.constraint:
        c = res.constraint
        rep.gene_rows = [
            Row(t("row.gene"), gene_value),
            Row("pLI", _constraint(c.get("pLI"), 3, 0.9,
                                   "constraint.pli_high", "constraint.pli_low"),
                t("note.pli")),
            Row("missense z", _constraint(c.get("mis_z"), 2, 3.09,
                                          "constraint.mis_high", "constraint.mis_low"),
                t("note.mis_z")),
            Row("LoF z", _constraint(c.get("lof_z"), 2, 3.09,
                                     "constraint.lof_high", "constraint.lof_low"),
                t("note.lof_z")),
        ]
    else:
        rep.gene_rows = [Row(t("row.gene"), gene_value)]
    # 照合には ClinVar の主な疾患だけを使う。提出件数が取れていれば最多のもの、
    # 無ければ索引の一覧の筆頭（候補が複数なら最初に見つかったもの）
    phenotypes: list[str] = []
    for rv in res.variants:
        c = (condition_results or {}).get(rv.genomic.funcvep_id)
        top = (c.top_condition if c and c.status == "found" else None) \
            or primary_phenotype((rv.evidence.clinvar or {}).get("phenotypes"))
        if top:
            phenotypes = [top]
            break
    rep.gene_rows += _clingen_rows(gene_validity, rep.created, phenotypes)

    # --- 集団頻度（手入力）。gnomAD の自動取得は変異ごとに載せる ---
    if gnomad_af is not None:
        value = f"{gnomad_af:.3e}"
        if gnomad_af > 0.05:
            value += wide + t("af.ba1")
        rep.population_rows.append(Row(t("row.af"), value, t("note.af_manual")))
        if gnomad_hom is not None:
            rep.population_rows.append(
                Row(t("row.hom"), str(gnomad_hom), t("note.hom"))
            )

    # --- 変異ごと ---
    for rv in res.variants:
        vr = VariantReport(variant=rv)
        ev = rv.evidence
        vr.splice = (splice_results or {}).get(rv.genomic.funcvep_id)
        vr.conditions = (condition_results or {}).get(rv.genomic.funcvep_id)
        vr.mave_rows = _mave_rows(mave_result, gnomad_online)
        if gnomad_online and vr.splice and vr.splice.level in ("moderate", "high"):
            rep.warnings.append(t("warn.spliceai", ds=f"{vr.splice.max_ds:.2f}",
                                  kind=t(f"splice.kind.{vr.splice.max_type}"),
                                  hgvs=f"{rv.gene} {rv.hgvs_p}", genomic=str(rv.genomic)))
        vr.gnomad = (gnomad_results or {}).get(rv.genomic.funcvep_id)
        vr.japan = (japan_results or {}).get(rv.genomic.funcvep_id)
        vr.population_rows = _population_rows(vr.gnomad, gnomad_online, rep.created, vr.japan)

        vr.funcvep_status = ev.funcvep_status
        vr.funcvep_note = missing_note(vr.funcvep_status, ev.train_models)

        # PP3/BP4 に採用するモデルは事前に 1 つ決める（設定 primary_model）。採用モデルの
        # スコアが無いときだけ、独立性の順（CTE → SP）で代替する。他モデルは参考
        order = [primary_model] + [m for m in FUNCVEP_MODELS if m != primary_model]
        vr.adopted_model = next((m for m in order if ev.funcvep.get(m) is not None), None)
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
                if a and a.criterion == "BP4":
                    head = _qualify_bp4(head, vr.splice, gnomad_online)
                head += t("acmg.adopted") if model == vr.adopted_model else t("acmg.reference")
            vr.predictions.append(
                Row(model.replace("_", "-"), value, head + t("sep.note") + model_note(model))
            )
        pm = primary_model.replace("_", "-")
        if vr.adopted_model is None:
            vr.adoption_note = t("adopt.none", model=pm)
        elif vr.adopted_model == primary_model:
            vr.adoption_note = t("adopt.note", model=pm)
        else:
            vr.adoption_note = t("adopt.fallback", model=pm, used=vr.adopted_model.replace("_", "-"))

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
        vr.others.append(_splice_row(vr.splice, gnomad_online))

        # --- ClinVar ---
        if ev.clinvar:
            cv = ev.clinvar
            stars = clinvar_stars(cv.get("review_status"))
            vr.clinvar_rows = [
                Row(t("row.significance"),
                    str(cv.get("significance") or t("dash")) + (wide + t("clinvar.expert") if stars >= 3 else ""),
                    t("note.review", stars=stars, status=cv.get("review_status"))),
                Row(t("row.submitters"), str(cv.get("n_submitters") or t("dash")), ""),
                Row(t("row.last_evaluated"), str(cv.get("last_evaluated") or t("dash")), ""),
                _condition_row((condition_results or {}).get(rv.genomic.funcvep_id),
                               cv.get("phenotypes")),
                *_moi_row((condition_results or {}).get(rv.genomic.funcvep_id)),
                Row(t("row.clinvar_name"), str(cv.get("name") or t("dash"))[:200],
                    t("note.variation_id", id=cv.get("variation_id"))),
            ]
        else:
            vr.clinvar_rows = [
                Row(t("row.significance"), t("clinvar.none"), t("note.clinvar_none"))
            ]

        # --- 同じ残基の既知判定（PS1 / PM5） ---
        if ev.same_residue is not None:
            vr.residue_rows = residue_rows(ev.same_residue, rv.genomic, rv.aa_alt)

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
        vr.concordance_kind = ("none" if n_tot == 0 else "damaging" if n_dmg == n_tot
                               else "neutral" if n_dmg == 0 else "mixed")
        splice_level = vr.splice.level if (gnomad_online and vr.splice and vr.splice.status == "scored") else None
        if splice_level == "high" and vr.concordance_kind == "neutral":
            vr.concordance_kind = "mixed"     # タンパク質への影響が低くても、スプライシング異常の可能性がある
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
        if splice_level == "high":
            vr.concordance_rows.append(Row(t("row.splice_flag"), t("conc.splice_high", ds=f"{vr.splice.max_ds:.2f}")))
        elif splice_level == "moderate":
            vr.concordance_rows.append(Row(t("row.splice_flag"), t("conc.splice_moderate", ds=f"{vr.splice.max_ds:.2f}")))
        elif splice_level is None and vr.concordance_kind == "neutral":
            vr.concordance_rows.append(Row(t("row.splice_flag"), t("conc.splice_unassessed")))

        rep.variants.append(vr)

    rep.provenance_rows = provenance_rows(
        res, versions, code_version, thresholds, rep.created,
        [vr.adopted_model for vr in rep.variants], primary_model)

    return rep
