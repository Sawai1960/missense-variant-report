"""遺伝子ミスセンス変異 統合評価レポート — Streamlit 画面。

    streamlit run app.py

表示言語はサイドバーで切り替える（日本語 / English）。?lang=en でも指定できる。
"""

from __future__ import annotations

from pathlib import Path

import streamlit as st

from funcvep_report import build_report, load_config
from funcvep_report.acmg import binary_cutoff, describe_thresholds
from funcvep_report.config import FUNCVEP_MODELS
from funcvep_report.gnomad import lookup as gnomad_lookup
from funcvep_report.togovar import lookup as togovar_lookup
from funcvep_report import clingen, clinvar_api, litvar, mavedb, spliceai
from funcvep_report.i18n import LANG_NAMES, LANGS, set_lang, t
from funcvep_report.lookup import Store, resolve
from funcvep_report.pdfout import fonts_for, render_stream
from funcvep_report.report import acknowledgement, disclaimer, funcvep_intro, missing_label, references
from funcvep_report.variant import AA1_TO_3

# 言語は他のどの文字列より先に決める。set_page_config はスクリプト先頭でしか
# 呼べないので、タイトルだけはここで確定させる。
_query_lang = st.query_params.get("lang", "")
if "lang" not in st.session_state:
    st.session_state["lang"] = _query_lang if _query_lang in LANGS else "ja"
set_lang(st.session_state["lang"])

st.set_page_config(page_title=t("ui.page_title"), page_icon="🧬", layout="wide")

STEPS = ("mane", "cds", "alphamissense", "funcvep", "revel", "clinvar", "constraint")


@st.cache_resource
def get_store():
    cfg = load_config()
    return cfg, Store(cfg)


cfg, store = get_store()
avail = store.availability()

# ---------------------------------------------------------------- サイドバー
with st.sidebar:
    chosen = st.radio(
        t("ui.language"),
        LANGS,
        index=LANGS.index(st.session_state["lang"]),
        format_func=lambda code: LANG_NAMES[code],
        horizontal=True,
    )
    st.caption(t("ui.language_help"))
    if chosen != st.session_state["lang"]:
        st.session_state["lang"] = chosen
        st.query_params["lang"] = chosen
        st.rerun()

    st.divider()
    st.caption(t("ui.sidebar_intro"))

    st.subheader(t("ui.data_status"))
    if all(avail.values()):
        # 揃っていれば一行で済ませ、内訳は畳んでおく
        st.success(t("ui.data_ready"))
        with st.expander(t("ui.data_detail")):
            for key in STEPS:
                st.write("✅ " + t(f"ui.step.{key}"))
    else:
        for key in STEPS:
            st.write(("✅ " if avail.get(key) else "⬜ ") + t(f"ui.step.{key}"))
        st.caption(t("ui.missing_data"))

    st.divider()
    st.subheader(t("ui.online"))
    gnomad_online = st.checkbox(
        t("ui.gnomad_online"),
        value=st.session_state.get("gnomad_online", cfg.gnomad_af_mode == "api"),
    )
    st.session_state["gnomad_online"] = gnomad_online
    st.caption(t("ui.online_help"))

    st.divider()
    thresholds = cfg.load_thresholds()
    st.subheader("PP3/BP4")
    if thresholds is None:
        st.warning(t("ui.thr.uncalibrated"))
        st.caption(t("ui.thr.uncalibrated_help"))
    else:
        meta = thresholds.get("meta", {})
        if meta.get("source") == "published":
            st.success(t("ui.thr.published"))
            st.caption(t("ui.thr.published_help"))
        else:
            st.warning(t("ui.thr.local",
                         n_p=f"{meta.get('n_pathogenic', '?'):,}"
                         if isinstance(meta.get("n_pathogenic"), int) else "?",
                         n_b=f"{meta.get('n_benign', '?'):,}"
                         if isinstance(meta.get("n_benign"), int) else "?"))
            st.caption(t("ui.thr.local_help"))

# ------------------------------------------------------------------ 本体
if cfg.organization(st.session_state["lang"]):
    st.caption(cfg.organization(st.session_state["lang"]))
st.title(t("ui.title"))
st.caption(t("ui.caption"))

# ?q=BRCA1+R1699W で直接開けるようにしておく。記録に URL を残すときに使える。
if "query_input" not in st.session_state:
    st.session_state["query_input"] = st.query_params.get("q", "")


def _clear_query() -> None:
    """次の変異を入力する前に、前の入力を消す。書き換え忘れの事故を防ぐ。"""
    st.session_state["query_input"] = ""
    if "q" in st.query_params:
        del st.query_params["q"]


# 「評価する」を押すと入力欄の内容が確定して再実行される。エンターキーでも同じ
col_query, col_run, col_clear = st.columns([6, 1, 1], vertical_alignment="bottom")
query = col_query.text_input(
    t("ui.query"),
    key="query_input",
    placeholder=t("ui.query_placeholder"),
)
col_run.button(t("ui.run"), type="primary", use_container_width=True)
col_clear.button(t("ui.clear"), on_click=_clear_query, use_container_width=True)
if query and st.query_params.get("q") != query:
    st.query_params["q"] = query

# 入力できる形式は、変異が未入力のあいだは開いておき、結果が出たら畳む
with st.expander(t("ui.formats"), expanded=not query):
    st.markdown(t("ui.formats_body"))

with st.expander(t("ui.population_manual")):
    st.caption(t("ui.population_help"))
    col_af, col_hom = st.columns(2)
    af_text = col_af.text_input(t("ui.af"), value="", placeholder=t("ui.af_placeholder"))
    hom_text = col_hom.text_input(t("ui.hom"), value="", placeholder=t("ui.hom_placeholder"))

if not query:
    st.stop()

missing_core = [k for k in ("mane", "cds", "alphamissense") if not avail.get(k)]
if missing_core:
    st.error(t("ui.missing_index",
               items=", ".join(t(f"ui.step.{k}") for k in missing_core)))
    st.stop()


def _num(text: str, cast):
    try:
        return cast(text.strip()) if text.strip() else None
    except ValueError:
        return None


@st.cache_data(ttl=24 * 3600, show_spinner=False)
def _gnomad(chrom: str, pos: int, ref: str, alt: str):
    """同じ変異を日に何度も照会しないよう 24 時間は結果を持つ。"""
    return gnomad_lookup(chrom, pos, ref, alt)


@st.cache_data(ttl=24 * 3600, show_spinner=False)
def _togovar(chrom: str, pos: int, ref: str, alt: str):
    return togovar_lookup(chrom, pos, ref, alt)


@st.cache_data(ttl=24 * 3600, show_spinner=False)
def _spliceai(chrom: str, pos: int, ref: str, alt: str, enst: str, gene: str):
    return spliceai.lookup(chrom, pos, ref, alt, enst=enst, gene=gene)


@st.cache_data(ttl=24 * 3600, show_spinner=False)
def _conditions(variation_id: str):
    return clinvar_api.lookup(variation_id)


@st.cache_data(ttl=24 * 3600, show_spinner=False)
def _mavedb(gene: str, hgvs_pro: str, refseq_nuc: str):
    return mavedb.lookup(gene, hgvs_pro, cfg.paths.index / "external", online=True,
                         cds=store.cds_for(refseq_nuc))


@st.cache_data(ttl=24 * 3600, show_spinner=False)
def _litvar(gene: str, pv1: str, rsids: tuple[str, ...]):
    return litvar.lookup(gene, pv1, list(rsids))


@st.cache_resource(ttl=24 * 3600)
def _clingen_table(online: bool):
    return clingen.load(cfg.paths.index / "external" / "clingen_gene_validity.csv", online=online)


with st.spinner(t("ui.resolving")):
    res = resolve(query, store)

gnomad_results = None
japan_results = None
splice_results = None
mave_result = None
condition_results = None
gene_validity = None
if not res.error:
    table = _clingen_table(gnomad_online)
    if table is not None:
        gene_validity = table.get(res.gene, [])
if gnomad_online and not res.error:
    with st.spinner(t("ui.gnomad_querying")):
        gnomad_results, japan_results, splice_results, condition_results = {}, {}, {}, {}
        for rv in res.variants:
            g = rv.genomic
            r = _gnomad(g.chrom, g.pos, g.ref, g.alt)
            if r.status == "error":
                # 失敗をキャッシュに残さない。次の照会で再試行できるようにする
                _gnomad.clear(g.chrom, g.pos, g.ref, g.alt)
            gnomad_results[g.funcvep_id] = r
            j = _togovar(g.chrom, g.pos, g.ref, g.alt)
            if j.status == "error":
                _togovar.clear(g.chrom, g.pos, g.ref, g.alt)
            japan_results[g.funcvep_id] = j
            s = _spliceai(g.chrom, g.pos, g.ref, g.alt, rv.enst, rv.gene)
            if s.status == "error":
                _spliceai.clear(g.chrom, g.pos, g.ref, g.alt, rv.enst, rv.gene)
            splice_results[g.funcvep_id] = s
            vid = str((rv.evidence.clinvar or {}).get("variation_id") or "")
            if vid:
                c = _conditions(vid)
                if c.status == "error":
                    _conditions.clear(vid)
                condition_results[g.funcvep_id] = c
        first = res.variants[0]
        hgvs_pro = "p." + AA1_TO_3[first.aa_ref] + str(first.position) + AA1_TO_3[first.aa_alt]
        mave_result = _mavedb(first.gene, hgvs_pro, first.refseq_nuc)
        if mave_result.status == "error":
            _mavedb.clear(first.gene, hgvs_pro, first.refseq_nuc)

rep = build_report(
    res, thresholds,
    gnomad_af=_num(af_text, float),
    gnomad_hom=_num(hom_text, int),
    threshold_note=describe_thresholds(cfg.primary_model, thresholds),
    gnomad_results=gnomad_results,
    gnomad_online=gnomad_online,
    japan_results=japan_results,
    gene_validity=gene_validity,
    splice_results=splice_results,
    mave_result=mave_result,
    organization=cfg.organization(st.session_state["lang"]),
    condition_results=condition_results,
)

if rep.error:
    st.error(rep.error)
    st.stop()

if rep.warnings:
    st.warning("\n\n".join("・" + w for w in rep.warnings))

# 集団頻度が取れていないときは、手入力の場所を案内する
if _num(af_text, float) is None:
    if not gnomad_online:
        st.info(t("ui.af_prompt_offline"))
    elif any(vr.gnomad is None or vr.gnomad.status == "error" for vr in rep.variants):
        st.info(t("ui.af_prompt_failed"))

st.subheader(t("ui.target"))
for r in rep.target_rows:
    st.write(f"**{r.label}** {r.value}")
    st.caption(r.note)

st.subheader(t("ui.gene"))
for r in rep.gene_rows:
    st.write(f"**{r.label}** {r.value}")
    if r.note:
        st.caption(r.note)
if rep.population_rows:
    st.subheader(t("ui.population"))
    for r in rep.population_rows:
        st.write(f"**{r.label}** {r.value}")
        if r.note:
            st.caption(r.note)

for i, vr in enumerate(rep.variants, 1):
    v = vr.variant
    head = f"{v.gene} {v.hgvs_p3}"
    if len(rep.variants) > 1:
        head += t("ui.candidate", i=i, n=len(rep.variants))
    genomic = f"{v.genomic}（GRCh38）" if st.session_state["lang"] == "ja" else f"{v.genomic} (GRCh38)"
    # 変異ごとの区切りは青い帯にして、節の見出しと見分けられるようにする
    st.markdown(
        f"<div style='background:#1c4e80;color:#fff;padding:0.6rem 1rem;margin:1.5rem 0 0.8rem;"
        f"border-radius:4px;font-size:1.4rem;font-weight:700'>{head}"
        f"<span style='font-size:0.95rem;font-weight:400;margin-left:1rem'>{genomic}</span></div>",
        unsafe_allow_html=True,
    )

    st.subheader(t("ui.population_gnomad"))
    for r in vr.population_rows:
        st.write(f"**{r.label}** {r.value}")
        if r.note:
            st.caption(r.note)

    st.subheader(t("ui.funcvep"))
    if i == 1:
        with st.expander(t("ui.about_funcvep"), expanded=True):
            st.write(funcvep_intro())
    _cuts = " / ".join(
        f"{m.split('_')[1]} {binary_cutoff(m, thresholds):.4f}" for m in FUNCVEP_MODELS
    )
    st.caption(t("ui.funcvep_caption", cuts=_cuts))
    cols = st.columns(len(FUNCVEP_MODELS))
    for c, model in zip(cols, FUNCVEP_MODELS):
        score = vr.variant.evidence.funcvep.get(model)
        a = vr.acmg.get(model)
        with c:
            st.markdown(f"**{model.replace('_', '-')}**")
            if score is None:
                st.markdown("### —")
                st.caption(missing_label(vr.funcvep_status))
                continue
            damaging = score >= binary_cutoff(model, thresholds)
            colour = "#b3261e" if damaging else "#1e6b34"
            st.markdown(
                f"<div style='font-size:2rem;line-height:1.1;color:{colour}'>"
                f"{score:.3f}</div>"
                f"<div style='color:{colour};font-weight:600'>"
                f"{'Damaging' if damaging else 'Neutral'}</div>",
                unsafe_allow_html=True,
            )
            st.caption(a.label if a else t("uncalibrated"))

    if vr.funcvep_note:
        st.info(vr.funcvep_note)

    with st.expander(t("ui.model_notes")):
        for r in vr.predictions:
            st.write(f"**{r.label}** {r.value}")
            st.caption(r.note)

    st.subheader(t("ui.others"))
    for r in vr.others:
        st.write(f"**{r.label}** {r.value}")
        st.caption(r.note)

    if vr.mave_rows:
        st.subheader(t("ui.mave"))
        for r in vr.mave_rows:
            st.write(f"**{r.label}** {r.value}")
            if r.note:
                st.caption(r.note)

    st.subheader(t("ui.concordance"))
    # 判定が揃っているかを色で示す（病原性の判定ではないので文言はそのまま）
    _box = {"damaging": st.error, "neutral": st.success, "mixed": st.warning}.get(vr.concordance_kind, st.info)
    _lines = []
    for r in vr.concordance_rows:
        if r.label == t("row.summary"):
            _lines.append(f"### {r.value}")
        else:
            _lines.append(f"**{r.label}** {r.value}")
    _lines.append(t('conc.caveat'))
    _box("\n\n".join(_lines))

    st.subheader(t("ui.clinvar"))
    for r in vr.clinvar_rows:
        st.write(f"**{r.label}** {r.value}")
        if r.note:
            st.caption(r.note)
    if vr.residue_rows:
        st.subheader(t("ui.residue"))
        for r in vr.residue_rows:
            st.write(f"**{r.label}** {r.value}")
            if r.note:
                st.caption(r.note)

    # 文献は画面だけ。報告書には載せない
    if gnomad_online and i == 1:
        with st.expander(t("ui.litvar")):
            rsids = tuple(vr.gnomad.rsids) if vr.gnomad and vr.gnomad.rsids else ()
            lit = _litvar(v.gene, v.protein_variant, rsids)
            if lit.status == "error":
                _litvar.clear(v.gene, v.protein_variant, rsids)
                st.caption(t("ui.litvar_failed", reason=lit.reason))
            elif lit.status == "none":
                st.caption(t("ui.litvar_none"))
            else:
                st.write(t("ui.litvar_count", n=f"{lit.count:,}", rsid=lit.rsid or t("dash")))
                for p in lit.papers:
                    st.markdown(f"- [{p.title}]({p.url}) — {p.first_author} ら, *{p.journal}* {p.year}, PMID {p.pmid}")
                if lit.url:
                    st.markdown(f"[{t('ui.litvar_more')}]({lit.url})")

st.divider()
with st.expander(t("ui.thresholds")):
    st.text(rep.threshold_note)

st.subheader(t("ui.disclaimer"))
# 報告書全体に掛かる注意なので枠で囲んで目立たせる
st.warning("・" + "\n\n・".join(disclaimer()))

with st.expander(t("ui.acknowledgement")):
    st.write(acknowledgement())

with st.expander(t("ui.references")):
    for n, ref in enumerate(references(), 1):
        st.markdown(f"{n}. {ref}")

st.divider()
try:
    pdf = render_stream(rep, fonts_for(cfg, rep.lang),
                        cache_dir=cfg.paths.index / "fonts")
    safe = "".join(ch if ch.isalnum() else "_" for ch in rep.query)[:60]
    st.download_button(
        t("ui.pdf_button"),
        data=pdf,
        file_name=f"variant_report_{safe}.pdf",
        mime="application/pdf",
        type="primary",
    )
    st.caption(t("ui.pdf_hint"))
except FileNotFoundError as exc:
    st.error(str(exc))
