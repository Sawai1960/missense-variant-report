"""利用者に見せる文字列の日英対訳表。

言語は contextvars で保持する。Streamlit は照会ごとに別スレッドで画面スクリプトを
走らせるため、モジュール変数にすると同時に開いている別の利用者の言語が混ざる。
既定は日本語で、何も設定しなければ従来どおり動く。

    from .i18n import t, use_lang
    with use_lang("en"):
        t("pdf.title")            # -> "Missense Variant Report"
    t("lk.multi_nuc", n=2)        # 書式は str.format と同じ

文体の方針（2026-09-08）: 読み手は遺伝の専門でない医師も含む。医学用語は使うが、
機械学習・バイオインフォマティクスの用語（特徴量、予測器、推論、較正、不寛容）は
使わず、「材料」「予測ツール」「予測」「判定基準」「一般の人々に少ない」と言い換える。
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar

LANGS = ("ja", "en")
LANG_NAMES = {"ja": "日本語", "en": "English"}

_lang: ContextVar[str] = ContextVar("funcvep_report_lang", default="ja")


def get_lang() -> str:
    return _lang.get()


def set_lang(lang: str) -> None:
    if lang not in LANGS:
        raise ValueError(f"unsupported language: {lang}")
    _lang.set(lang)


@contextmanager
def use_lang(lang: str):
    token = _lang.set(lang if lang in LANGS else "ja")
    try:
        yield
    finally:
        _lang.reset(token)


def t(key: str, **kw) -> str:
    ja, en = _STRINGS[key]
    s = en if get_lang() == "en" else ja
    return s.format(**kw) if kw else s


def has(key: str) -> bool:
    return key in _STRINGS


def join(items, wide: bool = False) -> str:
    """一覧の区切り。日本語は読点、英語はコンマ。"""
    sep = t("sep.wide" if wide else "sep.list")
    return sep.join(items)


# 著者私信で共通する注意書き。何度も出るのでここにまとめる。
_NO_INFO_JA = (
    "スコアが無いこと自体は、病気との関係についても予測の確からしさについても"
    "何の情報も持たない（著者らに確認済み）。AlphaMissense・REVEL・ClinVar の"
    "情報で判断すること。"
)
_NO_INFO_EN = (
    "The absence of a score carries no information about pathogenicity or "
    "prediction confidence (confirmed with the authors). Rely on "
    "AlphaMissense, REVEL and ClinVar."
)

# 参考文献。両言語で共通の書誌はそのまま並べる。
_REF_FUNCVEP = (
    "Kayaalp B, Çil K, Conil C, Cobat A, Kars ME, Itan Y, Casanova JL, Özçelik T. "
    "Prediction of human missense variant effects from functional evidence. "
    "Nature Genetics (2026). doi:10.1038/s41588-026-02727-3"
)
_REF_AM = (
    "Cheng J, et al. Accurate proteome-wide missense variant effect prediction "
    "with AlphaMissense. Science 381, eadg7492 (2023)."
)
_REF_REVEL = (
    "Ioannidis NM, et al. REVEL: an ensemble method for predicting the "
    "pathogenicity of rare missense variants. Am J Hum Genet 99, 877–885 (2016)."
)
_REF_GNOMAD = (
    "Karczewski KJ, et al. The mutational constraint spectrum quantified from "
    "variation in 141,456 humans. Nature 581, 434–443 (2020)."
)
_REF_CLINVAR = (
    "Landrum MJ, et al. ClinVar: improving access to variant interpretations and "
    "supporting evidence. Nucleic Acids Res 46, D1062–D1067 (2018)."
)
_REF_ACMG = (
    "Richards S, et al. Standards and guidelines for the interpretation of "
    "sequence variants: a joint consensus recommendation of the ACMG and the AMP. "
    "Genet Med 17, 405–424 (2015)."
)
_REF_PEJAVER = (
    "Pejaver V, et al. Calibration of computational tools for missense variant "
    "pathogenicity classification and ClinGen recommendations for PP3/BP4 "
    "criteria. Am J Hum Genet 109, 2163–2177 (2022)."
)
_REF_TIERS = (
    "Bergquist T, Stenton SL, Nadeau EAW, et al. Calibration of additional "
    "computational tools expands ClinGen recommendation options for variant "
    "classification with PP3/BP4 criteria. Genet Med 27, 101402 (2025). "
    "doi:10.1016/j.gim.2025.101402"
)

_STRINGS: dict[str, tuple[str, str]] = {
    # ---------------------------------------------------------------- 共通
    "sep.list": ("、", ", "),
    "sep.wide": ("　", "  "),
    "dash": ("—", "—"),

    # ------------------------------------------------------------ report.py
    "intro.funcvep": (
        "FuncVEP は Kayaalp ら（Nature Genetics, 2026）が開発した予測ツール。"
        "従来の多くのツールが ClinVar などの臨床判定や一般の人々の変異データで"
        "学習しているのに対し、FuncVEP は機能実験（変異がタンパク質の働きに"
        "与える影響を実際に測ったデータ）で学習している点が特徴で、論文では"
        "既存の 48 種のツールを上回る精度が報告されている（機能実験に基づく評価で "
        "78.8%→84.6%、臨床判定に基づく評価で 90.1%→92.4%）。本レポートは論文と"
        "ともに公開された予測済みスコア（約 7,300 万変異）を引いており、再計算は"
        "していない。",
        "FuncVEP is a predictor developed by Kayaalp et al. (Nature Genetics, 2026). "
        "Whereas most existing tools are trained on clinical classifications (e.g. "
        "ClinVar) or population data, FuncVEP is trained on functional assays — "
        "direct measurements of how a variant affects protein function. The paper "
        "reports higher accuracy than 48 existing predictors (78.8%→84.6% on "
        "functional benchmarks, 90.1%→92.4% on clinical benchmarks). This report "
        "looks up the precomputed scores released with the paper (~73 million "
        "variants); nothing is recomputed.",
    ),

    "missing_label.blank": ("非公開（モデルの学習に使用された変異）",
                            "Withheld (variant used to train the model)"),
    "missing_label.absent": ("未収録（全モデルの学習に使用された変異）",
                             "Not in table (variant used to train all models)"),
    "missing_label.absent_unexplained": (
        "未収録（予測表の作成上の理由。著者確認済み）",
        "Not in table (dataset assembly; confirmed by the authors)",
    ),
    "missing_label.unknown": ("FuncVEP の索引なし", "No FuncVEP index"),
    "missing_label.default": ("スコアなし", "No score"),

    "missing_note.blank": (
        "この変異は一部のモデルの学習に使用されている。正解が既知の変異で、"
        "スコアを公開しても予測としての意味がないため、著者らはそのモデルの"
        "スコアを公開していない。「予測できなかった」のではない。" + _NO_INFO_JA,
        "This variant was used to train some of the models. Its answer was "
        "already known to those models, so their scores would not be a "
        "meaningful prediction; the authors therefore withhold them. It does "
        "not mean the variant could not be predicted. " + _NO_INFO_EN,
    ),
    "missing_note.absent": (
        "この変異は 6 つのモデルすべての学習に使用されているため、"
        "どのモデルの予測からも除かれ、公開された予測表に行そのものが無い。"
        + _NO_INFO_JA,
        "This variant was in the training data of all six models, so it was "
        "excluded from every model's predictions and has no row in the released "
        "table. " + _NO_INFO_EN,
    ),
    "missing_note.absent_unexplained": (
        "この変異は公開された予測表に無く、公開されている学習データの"
        "一覧にも見当たらない。著者らの照合（2026-09-07 私信）によれば、この種の"
        "未収録は予測表を作る工程の都合（注釈の違いによる除外・元データに無い・"
        "処理の抜け）で生じたものである。" + _NO_INFO_JA,
        "This variant has no row in the released table and is not in any "
        "published training set. According to the authors (personal "
        "communication, 2026-09-07), such absences arise from the assembly of "
        "the released table (an annotation difference, absence from the source "
        "variant set, or loss during processing). " + _NO_INFO_EN,
    ),
    "missing_note.unknown": (
        "FuncVEP の索引がないため照会できない。",
        "The FuncVEP index is not available, so no lookup was possible.",
    ),
    "trained_models": (
        "　学習に使用したモデル: {models}",
        " Models trained on this variant: {models}",
    ),

    "model_note.FuncVEP_CTI": (
        "ClinVar などの臨床判定で学習した他の予測ツールの結果も材料に含めたモデル。"
        "論文の比較では最も高精度だが、ClinVar と同じ答えになりやすく、"
        "ClinVar から独立した証拠としては弱い",
        "Also uses, as inputs, the outputs of other predictors that were trained "
        "on clinical classifications such as ClinVar. Most accurate in the paper's "
        "comparison, but tends to agree with ClinVar and is weaker as evidence "
        "independent of it",
    ),
    "model_note.FuncVEP_CTE": (
        "臨床判定で学習した他ツールの結果を材料から外したモデル。"
        "ClinVar から独立した証拠として扱いやすい",
        "Excludes the outputs of clinically trained predictors from its inputs. "
        "Easier to treat as evidence independent of ClinVar",
    ),
    "model_note.FuncVEP_SP": (
        "他の予測ツールの結果を一切使わず、配列と構造の情報だけで予測するモデル。"
        "最も独立しているが、単独の精度は上の 2 つに劣る",
        "Uses no other predictors at all — only sequence and structure information. "
        "The most independent, but less accurate on its own than the two above",
    ),
    "model_note.ClinVEP_CTI": (
        "FuncVEP-CTI と同じ材料を、機能実験ではなく ClinVar の臨床判定で"
        "学習させた比較用モデル",
        "Comparison model trained on the same inputs as FuncVEP-CTI, but on "
        "ClinVar clinical classifications instead of functional assays",
    ),
    "model_note.ClinVEP_CTE": (
        "同上（臨床判定で学習した他ツールの結果を外したもの）",
        "As above, excluding clinically trained predictors",
    ),
    "model_note.ClinVEP_SP": (
        "同上（他の予測ツールの結果を使わないもの）",
        "As above, using no other predictors",
    ),

    "row.gene": ("遺伝子", "Gene"),
    "gene_value": ("{gene}（{ensg}）", "{gene} ({ensg})"),
    "note.pli": (
        "この遺伝子の機能喪失変異が、一般にはあまりみられないという指標（gnomAD）。"
        "1 に近いほど「壊れると影響が大きい遺伝子」",
        "Loss-of-function variants in this gene are rarely seen in the general "
        "population (gnomAD). Closer to 1 = a gene where loss has a large effect",
    ),
    "note.mis_z": (
        "この遺伝子のミスセンス変異が、一般には予想より少ないという指標（gnomAD）。"
        "値が大きいほど「ミスセンス変異の影響が出やすい遺伝子」",
        "Missense variants in this gene are rarer than expected in the general "
        "population (gnomAD). Larger values = a gene where missense variants tend to matter",
    ),
    "note.lof_z": (
        "機能喪失変異について、missense z と同じ考え方の指標",
        "The same measure as missense z, for loss-of-function variants",
    ),
    "row.af": ("gnomAD アレル頻度", "gnomAD allele frequency"),
    "note.af": ("0.01 を超えるなら BA1、疾患の頻度に照らして高いなら BS1 を検討",
                "Consider BA1 if above 0.01; BS1 if high relative to disease prevalence"),
    "row.hom": ("ホモ接合体数", "Homozygotes"),
    "note.hom": ("常染色体劣性疾患で 0 でないなら BS2 を検討",
                 "For an autosomal recessive disorder, consider BS2 if non-zero"),
    "af.not_entered": ("未入力", "Not entered"),
    "note.af_not_entered": ("検査報告書の値を画面で入力すると表示されます",
                            "Enter the value from the laboratory report to show it here"),
    "uncalibrated": ("PP3/BP4 の判定基準なし", "No PP3/BP4 thresholds"),

    "row.clinvep": ("ClinVEP（比較用）", "ClinVEP (comparison)"),
    "note.clinvep": (
        "FuncVEP と同じ材料を ClinVar の臨床判定で学習させた比較用のスコア。"
        "FuncVEP（タンパク質の働きへの影響）と ClinVEP（臨床判定の予測）が大きく"
        "食い違うときは、働きへの影響と病気との関係がずれている変異かもしれない",
        "Comparison scores from models trained on the same inputs as FuncVEP but "
        "on ClinVar clinical classifications. A large disagreement between FuncVEP "
        "(effect on protein function) and ClinVEP (predicted clinical "
        "classification) may indicate a variant where function and disease diverge",
    ),
    "note.clinvep_trained": (
        "この変異は {models} の学習に使用されているため、比較用のスコアは公開されていない",
        "Used to train {models}; the comparison score is withheld",
    ),
    "note.alphamissense": (
        "Google DeepMind の予測ツール（Cheng ら 2023, Science）。一般の人々での"
        "変異の頻度を手がかりに学習している。likely_pathogenic / ambiguous / "
        "likely_benign の 3 区分",
        "Google DeepMind's predictor (Cheng et al. 2023, Science), trained using "
        "population variant frequencies as a guide. Three classes: "
        "likely_pathogenic / ambiguous / likely_benign",
    ),
    "note.revel": (
        "複数の予測ツールを統合した従来型のスコア（Ioannidis ら 2016）。"
        "{cutoff} を境に damaging / neutral と読むのが慣例",
        "A conventional score combining several predictors (Ioannidis et al. 2016). "
        "By convention read as damaging / neutral at {cutoff}",
    ),

    "row.significance": ("臨床的意義", "Clinical significance"),
    "note.review": ("レビュー {stars} 星（{status}）", "Review {stars} star(s) ({status})"),
    "row.submitters": ("提出者数", "Submitters"),
    "row.last_evaluated": ("最終評価", "Last evaluated"),
    "row.phenotypes": ("表現型", "Phenotypes"),
    "row.clinvar_name": ("ClinVar 表記", "ClinVar name"),
    "note.variation_id": ("VariationID {id}", "VariationID {id}"),
    "clinvar.none": ("ClinVar に登録なし", "Not in ClinVar"),
    "note.clinvar_none": ("新規変異、あるいは未提出の変異である可能性",
                          "May be novel, or simply not yet submitted"),
    "phenotypes.none": ("記載なし", "Not stated"),
    "phenotypes.more": ("　ほか {n} 件", " and {n} more"),

    # 判定語の初回出現にだけ添える和訳（日本語版のみ）
    "gloss.Damaging": ("Damaging（機能を損なう）", "Damaging"),
    "gloss.Neutral": ("Neutral（影響なし）", "Neutral"),
    "gloss.likely_pathogenic": ("likely_pathogenic（病的の可能性が高い）", "likely_pathogenic"),
    "gloss.ambiguous": ("ambiguous（判定保留）", "ambiguous"),
    "gloss.likely_benign": ("likely_benign（良性の可能性が高い）", "likely_benign"),

    "conc.sides": ("damaging 側: {damaging}　／　neutral 側: {neutral}",
                   "damaging: {damaging}  /  neutral: {neutral}"),
    "conc.none": ("判定できる指標がありません", "No predictor could be called"),
    "conc.all_damaging": ("{n} 指標すべてが damaging 側",
                          "All {n} predictors on the damaging side"),
    "conc.all_neutral": ("{n} 指標すべてが neutral 側",
                         "All {n} predictors on the neutral side"),
    "conc.mixed": ("{n} 指標中 {d} が damaging 側（不一致）",
                   "{d} of {n} predictors damaging (discordant)"),

    "disclaimer.1": (
        "FuncVEP が予測するのはタンパク質の働きへの影響（damaging / neutral）であり、"
        "病気を起こすかどうか（臨床的病原性）そのものではない。両者を混同しないこと。",
        "FuncVEP predicts the effect on protein function (damaging / neutral), "
        "not clinical pathogenicity itself. Do not conflate the two.",
    ),
    "disclaimer.2": (
        "ACMG/AMP 基準では、コンピュータ予測による証拠 PP3/BP4 として扱う。"
        "実験で機能を確かめた証拠 PS3/BS3 にはならない。",
        "Under ACMG/AMP it is computational evidence (PP3/BP4), not functional "
        "assay evidence (PS3/BS3).",
    ),
    "disclaimer.3": (
        "対象はミスセンス変異（アミノ酸置換）のみ。スプライシングへの影響、"
        "フレームシフト、ナンセンス変異は評価されない。",
        "Missense variants only. Splicing effects, frameshifts and nonsense "
        "variants are not assessed.",
    ),
    "disclaimer.4": (
        "本レポートは変異解釈の補助資料であり、単独で臨床判断の根拠としてはならない。"
        "家系内での分離、症状との一致、機能実験、専門家の検討と併せて評価すること。",
        "This report supports variant interpretation and must not be the sole "
        "basis for a clinical decision. Weigh it together with segregation, "
        "phenotype fit, functional studies and expert review.",
    ),

    # ---------------------------------------------------------- 参考文献
    "pdf.references": ("参考文献", "References"),
    "ref.funcvep": (_REF_FUNCVEP, _REF_FUNCVEP),
    "ref.thresholds": (
        "同論文 Supplementary Table 13（PP3/BP4 の判定基準。2026-09-05 に著者から提供）",
        "Ibid., Supplementary Table 13 (PP3/BP4 thresholds; provided by the authors, 2026-09-05)",
    ),
    "ref.tiers": (
        _REF_TIERS + "（証拠の段階 Supporting / Moderate / Intermediate / Strong の定義。"
        "FuncVEP の著者の指示による）",
        _REF_TIERS + " (defines the Supporting / Moderate / Intermediate / Strong "
        "tiers; as indicated by the FuncVEP authors)",
    ),
    "ref.alphamissense": (_REF_AM, _REF_AM),
    "ref.revel": (_REF_REVEL, _REF_REVEL),
    "ref.gnomad": (_REF_GNOMAD, _REF_GNOMAD),
    "ref.clinvar": (_REF_CLINVAR, _REF_CLINVAR),
    "ref.acmg": (_REF_ACMG, _REF_ACMG),
    "ref.pejaver": (_REF_PEJAVER, _REF_PEJAVER),

    # -------------------------------------------------------------- acmg.py
    "acmg.none": ("該当なし（中間域）", "None (intermediate range)"),
    "thr.explain": (
        "PP3 / BP4 は ACMG/AMP 基準の証拠項目で、PP3 はコンピュータ予測が「病的」を"
        "支持する証拠、BP4 は「良性」を支持する証拠。強さは Supporting → Moderate → "
        "Intermediate → Strong の順に強い。どちらの基準にも達しないスコアは"
        "「該当なし（中間域）」で、証拠として数えない。",
        "PP3 and BP4 are ACMG/AMP evidence criteria: PP3 is computational evidence "
        "supporting pathogenicity, BP4 computational evidence supporting a benign "
        "interpretation. Strength increases Supporting → Moderate → Intermediate → "
        "Strong. A score reaching neither threshold is \"None (intermediate range)\" "
        "and does not count as evidence.",
    ),
    "thr.uncalibrated": (
        "PP3/BP4 の判定基準が設定されていません。scripts/03_calibrate_acmg.py を"
        "実行すると、お手元の ClinVar から算出します。",
        "PP3/BP4 thresholds are not set. Run scripts/03_calibrate_acmg.py "
        "to derive them from your local ClinVar.",
    ),
    "thr.published_source": ("判定基準の由来: {citation}。", "Threshold source: {citation}."),
    "thr.published_default": ("論文の公表値", "published values from the paper"),
    "thr.published_note": (
        "著者から提供された公表値をそのまま使用しています（当方で算出したものではありません）。",
        "Published values provided by the authors are used as-is (not derived locally).",
    ),
    "thr.local_head": (
        "判定基準の由来: ClinVar（{date} 時点、レビュー {stars} 星以上）の "
        "病的 {n_p:,} 件 / 良性 {n_b:,} 件から当方で算出。",
        "Threshold source: derived locally from ClinVar ({date}, review status "
        "{stars}+ stars), {n_p:,} pathogenic / {n_b:,} benign variants.",
    ),
    "thr.local_head_short": (
        "判定基準の由来: ClinVar（{date} 時点）から当方で算出。",
        "Threshold source: derived locally from ClinVar ({date}).",
    ),
    "thr.local_params": (
        "事前確率 {prior}、ブートストラップ {boot} 回の保守的な下限を採用。",
        "Prior {prior}; conservative lower bound over {boot} bootstrap draws.",
    ),
    "thr.local_warn": (
        "論文の公表値ではないため、論文の判定とは一致しません。",
        "These are not the published values, so calls will not match the paper.",
    ),
    "thr.pp3_line": ("PP3: {parts} 以上", "PP3: {parts} or above"),
    "thr.bp4_line": ("BP4: {parts} 以下", "BP4: {parts} or below"),
    "thr.binary": (
        "damaging/neutral の境: {cut:.4f}（モデルごとに異なる。0.5 ではない）",
        "damaging/neutral cutoff: {cut:.4f} (model-specific; not 0.5)",
    ),

    # ------------------------------------------------------------ pdfout.py
    "pdf.title": ("ミスセンス変異 統合レポート", "Missense Variant Report"),
    "pdf.meta": ("入力: {query}　　作成: {created}", "Query: {query}    Created: {created}"),
    "pdf.unresolved": ("解決できませんでした", "Could not resolve"),
    "pdf.warnings": ("注意", "Notes"),
    "pdf.gene": ("遺伝子", "Gene"),
    "pdf.population": ("集団頻度", "Population frequency"),
    "pdf.variant": ("変異", "Variant"),
    "pdf.variant_n": ("変異 {i} / {n}", "Variant {i} / {n}"),
    "row.genomic": ("ゲノム座標", "Genomic coordinate"),
    "row.transcript": ("転写産物", "Transcript"),
    "pdf.funcvep": ("FuncVEP（タンパク質の働きへの影響の予測）",
                    "FuncVEP (predicted effect on protein function)"),
    "pdf.others": ("他の予測ツール", "Other predictors"),
    "pdf.clinvar": ("ClinVar", "ClinVar"),
    "pdf.concordance": ("指標同士の一致", "Concordance"),
    "row.summary": ("要約", "Summary"),
    "pdf.thresholds": ("PP3/BP4 の判定基準について", "PP3/BP4 thresholds"),
    "pdf.disclaimer": ("解釈上の注意", "Interpretation caveats"),
    "pdf.font_missing": (
        "日本語フォントが見つかりません: {path}\n"
        "config.yaml の pdf_font を実在する TTF に変えてください。",
        "Font not found: {path}\nSet pdf_font in config.yaml to an existing TTF.",
    ),

    # ------------------------------------------------------------ lookup.py
    "lk.numbering_note": (
        "AlphaMissense がこの遺伝子について別のアイソフォームを使っており、"
        "残基番号の対応が一定のずれでは説明できません。\n"
        "そのまま番号を当てはめると別の残基のスコアを示す恐れがあるため、"
        "ここで止めています。",
        "AlphaMissense uses a different isoform for this gene, and the residue "
        "numbering cannot be reconciled by a constant offset.\n"
        "Applying the number as-is could return the score of a different residue, "
        "so the lookup stops here.",
    ),
    "lk.no_coord_head": (
        "{gene} p.{pv} に対応するゲノム座標を特定できませんでした。\n",
        "Could not determine a genomic coordinate for {gene} p.{pv}.\n",
    ),
    "lk.not_one_base": (
        "{gene} の {position} 番目のコドンは {codon} で、"
        "{aa_ref} から {aa_alt} へは 1 塩基の置換では変えられません"
        "（2 塩基以上の変化が必要）。\n"
        "この位置で 1 塩基置換により生じうるのは {listed} です。\n"
        "報告書の表記をもう一度ご確認ください。",
        "Codon {position} of {gene} is {codon}; {aa_ref} cannot become {aa_alt} by "
        "a single-base substitution (two or more bases would have to change).\n"
        "Single-base substitutions at this position can yield: {listed}.\n"
        "Please re-check the notation in the report.",
    ),
    "lk.none": ("なし", "none"),
    "lk.rejected_item": (
        "{enst}（一致率 {agr:.2f}、{n} 残基で比較）",
        "{enst} (agreement {agr:.2f} over {n} residues)",
    ),
    "lk.rejected": (
        "{gene} の領域内に p.{pv} と書ける行はありましたが、"
        "その転写産物は MANE と残基番号の付き方が違います: {listed}。\n"
        "同じ残基番号に同じアミノ酸が来ているだけで、指しているのは別の残基です。"
        "そのまま採用すると別の場所のスコアを表示してしまうため、ここで止めています。\n"
        "報告書の NM_ 番号を使った HGVS 表記での入力もお試しください。",
        "Rows written as p.{pv} exist within the {gene} region, but their "
        "transcripts number residues differently from MANE: {listed}.\n"
        "The same amino acid merely happens to sit at the same residue number; it "
        "is a different residue. Using it would show the score of another position, "
        "so the lookup stops here.\n"
        "Try entering the variant in HGVS form with the NM_ transcript from the report.",
    ),
    "lk.not_in_am": (
        "AlphaMissense にこのアミノ酸置換の記載がありません。"
        "この転写産物が AlphaMissense の対象外である可能性があります。\n"
        "HGVS 転写産物表記での入力もお試しください。",
        "AlphaMissense has no entry for this amino-acid substitution. The transcript "
        "may be outside AlphaMissense's coverage.\n"
        "Try entering the variant in HGVS transcript notation.",
    ),
    "lk.no_mane_index": (
        "MANE の索引がありません。scripts/02_build_index.py mane を実行してください。",
        "The MANE index is missing. Run scripts/02_build_index.py mane.",
    ),
    "lk.tx_not_found": (
        "転写産物 {tx} が MANE に見つかりません。\n"
        "MANE Select 以外の転写産物は対象外です。"
        "遺伝子記号とアミノ酸置換での入力をお試しください。",
        "Transcript {tx} was not found in MANE.\n"
        "Only MANE Select transcripts are supported. "
        "Try gene symbol plus amino-acid substitution.",
    ),
    "lk.no_cds": (
        "{refseq} の CDS 配列が索引にありません。",
        "The CDS sequence of {refseq} is not in the index.",
    ),
    "lk.synonymous": (
        "この置換は同義置換です（{aa_ref}{position} のまま変わりません）。"
        "FuncVEP はミスセンス変異のみを扱います。",
        "This substitution is synonymous ({aa_ref}{position} is unchanged). "
        "FuncVEP covers missense variants only.",
    ),
    "lk.stop_gain": (
        "この置換は終止コドンを生じます（p.{aa_ref}{position}Ter）。"
        "FuncVEP はミスセンス変異のみを扱います。",
        "This substitution creates a stop codon (p.{aa_ref}{position}Ter). "
        "FuncVEP covers missense variants only.",
    ),
    "lk.gene_mismatch": (
        "入力の遺伝子名 {input_gene} と転写産物の遺伝子 {tx_gene} が"
        "一致しません。転写産物側を採用しました。",
        "The gene entered ({input_gene}) does not match the transcript's gene "
        "({tx_gene}). The transcript's gene was used.",
    ),
    "lk.gene_not_found": (
        "遺伝子 {gene} が MANE に見つかりません。正式な HGNC 記号で入力してください。",
        "Gene {gene} was not found in MANE. Use the official HGNC symbol.",
    ),
    "lk.hints": ("\n候補: {hints}", "\nDid you mean: {hints}"),
    "lk.too_short": (
        "{refseq} は {n} 残基しかありません",
        "{refseq} has only {n} residues",
    ),
    "lk.residue_is": (
        "{refseq} の {position} 番目は {actual}",
        "residue {position} of {refseq} is {actual}",
    ),
    "lk.cds_skipped": (
        "{refseq} の CDS が索引に無いため、参照アミノ酸の確認を省きました。",
        "The CDS of {refseq} is not in the index, so the reference amino acid "
        "was not verified.",
    ),
    "lk.no_matching_tx": (
        "{gene} の {position} 番目のアミノ酸が、入力された {aa_ref} と一致する"
        "転写産物がありません。\n{mismatches}\n"
        "報告書の転写産物番号を使った HGVS 表記でお試しください。",
        "No transcript of {gene} has {aa_ref} at residue {position}.\n{mismatches}\n"
        "Try HGVS notation with the transcript from the report.",
    ),
    "lk.multi_mane": (
        "{gene} には複数の MANE 転写産物があります。"
        "参照アミノ酸が一致した {refseq}（{status}）を使いました。他: {others}",
        "{gene} has more than one MANE transcript. {refseq} ({status}), whose "
        "reference amino acid matched, was used. Others: {others}",
    ),
    "lk.offset_warn": (
        "AlphaMissense は別のアイソフォームを使っており、"
        "残基番号が {offset:+d} ずれています。"
        "{gene} p.{pv} を p.{am_pv} として照会しました。",
        "AlphaMissense uses a different isoform with residue numbering shifted by "
        "{offset:+d}. {gene} p.{pv} was looked up as p.{am_pv}.",
    ),
    "lk.region_warn": (
        "転写産物 ID が AlphaMissense と一致しなかったため、"
        "遺伝子の領域内での一致を採用しました"
        "（残基番号の付き方が MANE と一致することを確認済み）。",
        "The transcript ID did not match AlphaMissense, so a match within the gene "
        "region was used (residue numbering verified to agree with MANE).",
    ),
    "lk.no_am_index": (
        "AlphaMissense の索引がありません。アミノ酸変化からゲノム座標を求めるには"
        "この索引が必要です。scripts/02_build_index.py alphamissense を実行してください。",
        "The AlphaMissense index is missing. It is required to map an amino-acid "
        "change to genomic coordinates. Run scripts/02_build_index.py alphamissense.",
    ),
    "lk.multi_nuc": (
        "同じアミノ酸置換を生じる塩基置換が {n} 通りあります。"
        "すべて表示します。検査報告書の塩基座標と照合してください。",
        "{n} different nucleotide substitutions produce this amino-acid change. "
        "All are shown; match them against the coordinate in the laboratory report.",
    ),
    "lk.ensg_mismatch": (
        "FuncVEP 側の遺伝子 {fv_ensg} が {ensg} と一致しません。"
        "重複遺伝子領域の可能性があります。",
        "The gene in FuncVEP ({fv_ensg}) does not match {ensg}. "
        "This may be an overlapping-gene region.",
    ),
    "lk.warn_blank": (
        "FuncVEP のスコアは空欄です。モデルの学習に使用された変異は"
        "スコアが公開されていません。AlphaMissense・REVEL・ClinVar を見てください。",
        "FuncVEP scores are blank: scores of variants used to train the models are "
        "withheld. See AlphaMissense, REVEL and ClinVar.",
    ),
    "lk.warn_absent": (
        "この変異は 6 つのモデルすべての学習に使用されているため、"
        "公開された予測表から行ごと除かれています。収録が無いこと自体は病気との"
        "関係について何の情報も持ちません。AlphaMissense・REVEL・ClinVar を見てください。",
        "This variant was used to train all six models and therefore has no row "
        "in the released table. Its absence carries no information about "
        "pathogenicity. See AlphaMissense, REVEL and ClinVar.",
    ),
    "lk.warn_absent_unexplained": (
        "この変異は公開された予測表になく、公開されている学習データの"
        "一覧にも見当たりません。著者らの照合によれば予測表を作る工程の都合で"
        "生じた未収録で、収録が無いこと自体は病気との関係について何の情報も"
        "持ちません。AlphaMissense・REVEL・ClinVar を見てください。",
        "This variant has no row in the released table and is not in any "
        "published training set. Per the authors, such absences arise from the "
        "assembly of the released table and carry no information about "
        "pathogenicity. See AlphaMissense, REVEL and ClinVar.",
    ),
    "lk.warn_mixed": (
        "FuncVEP のスコアが得られません（候補ごとに理由が異なります）。"
        "AlphaMissense・REVEL・ClinVar を見てください。",
        "No FuncVEP score is available (the reason differs between candidates). "
        "See AlphaMissense, REVEL and ClinVar.",
    ),

    # ----------------------------------------------------------- variant.py
    "vp.bad_aa": ("アミノ酸として解釈できません: {token}",
                  "Not a recognisable amino acid: {token}"),
    "vp.empty": ("入力が空です。", "The input is empty."),
    "vp.synonymous": (
        "同義置換（p.Xxx123=）は対象外です。FuncVEP はミスセンス変異のみを扱います。",
        "Synonymous changes (p.Xxx123=) are not supported. FuncVEP covers "
        "missense variants only.",
    ),
    "vp.nonsense": (
        "ナンセンス変異（終止コドン生成）は対象外です。FuncVEP はミスセンス変異のみを扱います。",
        "Nonsense variants (stop gain) are not supported. FuncVEP covers "
        "missense variants only.",
    ),
    "vp.same_aa": ("参照アミノ酸と変異アミノ酸が同じです。",
                   "The reference and variant amino acids are the same."),
    "vp.unrecognized": (
        "入力形式を認識できません。次のいずれかで入力してください。\n"
        "  ・遺伝子記号 + アミノ酸置換    例) BRCA1 p.Arg1699Trp / BRCA1 R1699W\n"
        "  ・HGVS 転写産物表記            例) NM_007294.4:c.5095C>T",
        "Unrecognised input. Use one of:\n"
        "  - gene symbol + amino-acid substitution   e.g. BRCA1 p.Arg1699Trp / BRCA1 R1699W\n"
        "  - HGVS transcript notation                e.g. NM_007294.4:c.5095C>T",
    ),
    "vp.out_of_range": (
        "c.{pos} はこの転写産物のコード領域（1〜{length}）の外です。",
        "c.{pos} is outside the coding region of this transcript (1–{length}).",
    ),
    "vp.ref_mismatch": (
        "参照塩基が一致しません。c.{pos} の実際の塩基は {observed} ですが、"
        "入力は {ref} となっています。転写産物の指定を確認してください。",
        "Reference base mismatch: the base at c.{pos} is {observed}, but {ref} was "
        "entered. Check the transcript.",
    ),
    "vp.codon_truncated": ("コドンが配列末端で欠けています。",
                           "The codon is truncated at the end of the sequence."),

    # --------------------------------------------------------------- app.py
    "ui.page_title": ("ミスセンス変異 統合レポート", "Missense Variant Report"),
    "ui.language": ("言語 / Language", "言語 / Language"),
    "ui.data_status": ("データの状態", "Data status"),
    "ui.step.mane": ("MANE（遺伝子・転写産物）", "MANE (gene / transcript)"),
    "ui.step.cds": ("MANE CDS（HGVS 変換）", "MANE CDS (HGVS conversion)"),
    "ui.step.alphamissense": ("AlphaMissense（座標変換の要）", "AlphaMissense (coordinate mapping)"),
    "ui.step.funcvep": ("FuncVEP スコア", "FuncVEP scores"),
    "ui.step.revel": ("REVEL", "REVEL"),
    "ui.step.clinvar": ("ClinVar", "ClinVar"),
    "ui.step.constraint": ("gnomAD 遺伝子制約", "gnomAD gene constraint"),
    "ui.missing_data": (
        "未取得の項目があります。ターミナルで\n"
        "`python scripts/01_download.py`\n"
        "`python scripts/02_build_index.py`\n"
        "を実行してください。",
        "Some data are missing. In a terminal, run\n"
        "`python scripts/01_download.py`\n"
        "`python scripts/02_build_index.py`",
    ),
    "ui.population": ("集団頻度", "Population frequency"),
    "ui.population_help": (
        "検査報告書に記載の gnomAD の値を入力すると、レポートに載ります。",
        "Enter the gnomAD values from the laboratory report to include them.",
    ),
    "ui.af": ("アレル頻度", "Allele frequency"),
    "ui.af_placeholder": ("例) 0.0000041 または 4.1e-6", "e.g. 0.0000041 or 4.1e-6"),
    "ui.hom": ("ホモ接合体数", "Homozygotes"),
    "ui.hom_placeholder": ("例) 0", "e.g. 0"),
    "ui.thr.uncalibrated": ("PP3/BP4 の判定基準が未設定です。スコアの生値のみ表示します。",
                            "PP3/BP4 thresholds are not set. Raw scores only."),
    "ui.thr.uncalibrated_help": ("`python scripts/03_calibrate_acmg.py` で算出できます。",
                                 "Run `python scripts/03_calibrate_acmg.py` to derive them."),
    "ui.thr.published": ("論文の公表値（Supplementary Table 13）",
                         "Published values (Supplementary Table 13)"),
    "ui.thr.published_help": ("著者から提供された判定基準をそのまま使用しています。",
                              "Thresholds provided by the authors are used as-is."),
    "ui.thr.local": (
        "当方で算出した判定基準（病的 {n_p} / 良性 {n_b} 件）",
        "Locally derived thresholds ({n_p} pathogenic / {n_b} benign)",
    ),
    "ui.thr.local_help": ("論文の公表値ではありません。判定は論文と一致しません。",
                          "Not the published values; calls will not match the paper."),
    "ui.title": ("ミスセンス変異 統合レポート", "Missense Variant Report"),
    "ui.caption": (
        "FuncVEP（Kayaalp ら, Nature Genetics 2026）の予測を軸に、AlphaMissense・"
        "REVEL・ClinVar・gnomAD の情報をまとめます。予測はタンパク質の働きへの"
        "影響であり、病気を起こすかどうかそのものではありません。",
        "Combines FuncVEP predictions (Kayaalp et al., Nature Genetics 2026) with "
        "AlphaMissense, REVEL, ClinVar and gnomAD. The prediction is of the effect "
        "on protein function, not clinical pathogenicity itself.",
    ),
    "ui.query": ("変異を入力", "Enter a variant"),
    "ui.query_placeholder": (
        "BRCA1 p.Arg1699Trp　/　BRCA1 R1699W　/　NM_007294.4:c.5095C>T",
        "BRCA1 p.Arg1699Trp  /  BRCA1 R1699W  /  NM_007294.4:c.5095C>T",
    ),
    "ui.formats": ("入力できる形式", "Accepted formats"),
    "ui.formats_body": (
        "- **遺伝子記号 + アミノ酸置換** — `BRCA1 p.Arg1699Trp` / `BRCA1 R1699W` / `TP53:p.R175H`\n"
        "- **HGVS 転写産物表記** — `NM_007294.4:c.5095C>T` / `NM_007294.4(BRCA1):c.5095C>T`\n\n"
        "転写産物は MANE Select を参照します。対象はミスセンス変異のみです。",
        "- **Gene symbol + amino-acid substitution** — `BRCA1 p.Arg1699Trp` / `BRCA1 R1699W` / `TP53:p.R175H`\n"
        "- **HGVS transcript notation** — `NM_007294.4:c.5095C>T` / `NM_007294.4(BRCA1):c.5095C>T`\n\n"
        "Transcripts are resolved against MANE Select. Missense variants only.",
    ),
    "ui.missing_index": ("必要な索引がありません: {items}", "Required index missing: {items}"),
    "ui.resolving": ("照合しています…", "Looking up…"),
    "ui.gene": ("遺伝子", "Gene"),
    "ui.candidate": ("　（候補 {i} / {n}）", "  (candidate {i} / {n})"),
    "ui.transcript_line": ("{genomic}（GRCh38）　転写産物 {refseq} / {enst}",
                           "{genomic} (GRCh38)  Transcript {refseq} / {enst}"),
    "ui.funcvep": ("FuncVEP（タンパク質の働きへの影響の予測）",
                   "FuncVEP (predicted effect on protein function)"),
    "ui.funcvep_caption": (
        "スコアはタンパク質の働きを損なう（damaging）と予測される確率（0〜1）。"
        "damaging と neutral の境はモデルごとに異なる（{cuts}）。",
        "Score = probability (0–1) that the variant is damaging to protein function. "
        "The damaging/neutral cutoff is model-specific ({cuts}).",
    ),
    "ui.about_funcvep": ("FuncVEP について", "About FuncVEP"),
    "ui.model_notes": ("各モデルの違い", "About each model"),
    "ui.others": ("他の予測ツール", "Other predictors"),
    "ui.clinvar": ("ClinVar", "ClinVar"),
    "ui.concordance": ("指標同士の一致", "Concordance"),
    "ui.thresholds": ("PP3/BP4 の判定基準について", "PP3/BP4 thresholds"),
    "ui.disclaimer": ("解釈上の注意", "Interpretation caveats"),
    "ui.references": ("参考文献", "References"),
    "ui.pdf_button": ("この内容を PDF で保存", "Save as PDF"),
}
