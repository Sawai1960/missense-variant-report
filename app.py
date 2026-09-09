"""ミスセンス変異 統合レポート — Streamlit 画面。

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
from funcvep_report.i18n import LANG_NAMES, LANGS, set_lang, t
from funcvep_report.lookup import Store, resolve
from funcvep_report.pdfout import render_stream
from funcvep_report.report import disclaimer, funcvep_intro, missing_label, references

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
    if chosen != st.session_state["lang"]:
        st.session_state["lang"] = chosen
        st.query_params["lang"] = chosen
        st.rerun()

    st.divider()
    st.subheader(t("ui.data_status"))
    for key in STEPS:
        st.write(("✅ " if avail.get(key) else "⬜ ") + t(f"ui.step.{key}"))
    if not all(avail.values()):
        st.caption(t("ui.missing_data"))

    st.divider()
    gnomad_online = st.checkbox(
        t("ui.gnomad_online"),
        value=st.session_state.get("gnomad_online", cfg.gnomad_af_mode == "api"),
        help=t("ui.gnomad_online_help"),
    )
    st.session_state["gnomad_online"] = gnomad_online

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
st.title(t("ui.title"))
st.caption(t("ui.caption"))

# ?q=BRCA1+R1699W で直接開けるようにしておく。記録に URL を残すときに使える。
query = st.text_input(
    t("ui.query"),
    value=st.query_params.get("q", ""),
    placeholder=t("ui.query_placeholder"),
)
if query and st.query_params.get("q") != query:
    st.query_params["q"] = query

with st.expander(t("ui.formats")):
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


with st.spinner(t("ui.resolving")):
    res = resolve(query, store)

gnomad_results = None
japan_results = None
if gnomad_online and not res.error:
    with st.spinner(t("ui.gnomad_querying")):
        gnomad_results, japan_results = {}, {}
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

rep = build_report(
    res, thresholds,
    gnomad_af=_num(af_text, float),
    gnomad_hom=_num(hom_text, int),
    threshold_note=describe_thresholds(cfg.primary_model, thresholds),
    gnomad_results=gnomad_results,
    gnomad_online=gnomad_online,
    japan_results=japan_results,
)

if rep.error:
    st.error(rep.error)
    st.stop()

for w in rep.warnings:
    st.warning(w)

# 集団頻度が取れていないときは、手入力の場所を案内する
if _num(af_text, float) is None:
    if not gnomad_online:
        st.info(t("ui.af_prompt_offline"))
    elif any(vr.gnomad is None or vr.gnomad.status == "error" for vr in rep.variants):
        st.info(t("ui.af_prompt_failed"))

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
    st.divider()
    head = f"{v.gene} {v.hgvs_p}"
    if len(rep.variants) > 1:
        head += t("ui.candidate", i=i, n=len(rep.variants))
    st.header(head)
    st.caption(t("ui.transcript_line", genomic=v.genomic,
                 refseq=v.refseq_nuc, enst=v.enst))

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

    st.subheader(t("ui.concordance"))
    for r in vr.concordance_rows:
        st.write(f"**{r.label}** {r.value}")

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

st.divider()
with st.expander(t("ui.thresholds")):
    st.text(rep.threshold_note)

st.subheader(t("ui.disclaimer"))
for d in disclaimer():
    st.markdown("- " + d)

with st.expander(t("ui.references")):
    for n, ref in enumerate(references(), 1):
        st.markdown(f"{n}. {ref}")

st.divider()
try:
    pdf = render_stream(rep, Path(cfg.pdf_font),
                        cache_dir=cfg.paths.index / "fonts")
    safe = "".join(ch if ch.isalnum() else "_" for ch in rep.query)[:60]
    st.download_button(
        t("ui.pdf_button"),
        data=pdf,
        file_name=f"variant_report_{safe}.pdf",
        mime="application/pdf",
        type="primary",
    )
except FileNotFoundError as exc:
    st.error(str(exc))
