"""ミスセンス変異 統合レポート — Streamlit 画面。

    streamlit run app.py
"""

from __future__ import annotations

from pathlib import Path

import streamlit as st

from funcvep_report import build_report, load_config
from funcvep_report.acmg import binary_cutoff, describe_thresholds
from funcvep_report.config import FUNCVEP_MODELS
from funcvep_report.lookup import Store, resolve
from funcvep_report.pdfout import render_stream
from funcvep_report.report import (
    DISCLAIMER, FUNCVEP_MISSING_LABEL,
)

st.set_page_config(page_title="ミスセンス変異 統合レポート",
                   page_icon="🧬", layout="wide")

STEP_NAME = {
    "mane": "MANE（遺伝子・転写産物）",
    "cds": "MANE CDS（HGVS 変換）",
    "alphamissense": "AlphaMissense（座標変換の要）",
    "funcvep": "FuncVEP スコア",
    "revel": "REVEL",
    "clinvar": "ClinVar",
    "constraint": "gnomAD 遺伝子制約",
}


@st.cache_resource
def get_store():
    cfg = load_config()
    return cfg, Store(cfg)


cfg, store = get_store()
avail = store.availability()

# ---------------------------------------------------------------- サイドバー
with st.sidebar:
    st.subheader("データの状態")
    for key, label in STEP_NAME.items():
        st.write(("✅ " if avail.get(key) else "⬜ ") + label)
    if not all(avail.values()):
        st.caption(
            "未取得の項目があります。ターミナルで\n"
            "`python scripts/01_download.py`\n"
            "`python scripts/02_build_index.py`\n"
            "を実行してください。"
        )

    st.divider()
    st.subheader("集団頻度")
    st.caption("検査報告書に記載の gnomAD の値を入力すると、レポートに載ります。")
    af_text = st.text_input("アレル頻度", value="",
                            placeholder="例) 0.0000041 または 4.1e-6")
    hom_text = st.text_input("ホモ接合体数", value="", placeholder="例) 0")

    st.divider()
    thresholds = cfg.load_thresholds()
    st.subheader("PP3/BP4")
    if thresholds is None:
        st.warning("未較正です。スコアの生値のみ表示します。")
        st.caption("`python scripts/03_calibrate_acmg.py` で較正できます。")
    else:
        meta = thresholds.get("meta", {})
        if meta.get("source") == "published":
            st.success("論文の公表値（Supplementary Table 13）")
            st.caption("著者から提供された較正値をそのまま使用しています。")
        else:
            st.warning(f"自前の較正（病的 {meta.get('n_pathogenic', '?'):,} / "
                       f"良性 {meta.get('n_benign', '?'):,} 件）")
            st.caption("論文の公表値ではありません。判定は論文と一致しません。")

# ------------------------------------------------------------------ 本体
st.title("ミスセンス変異 統合レポート")
st.caption(
    "FuncVEP（Kayaalp ら, Nature Genetics 2026）の予測を軸に、AlphaMissense・"
    "REVEL・ClinVar・gnomAD の情報をまとめます。予測は機能的影響であり、"
    "臨床的病原性そのものではありません。"
)

# ?q=BRCA1+R1699W で直接開けるようにしておく。記録に URL を残すときに使える。
query = st.text_input(
    "変異を入力",
    value=st.query_params.get("q", ""),
    placeholder="BRCA1 p.Arg1699Trp　/　BRCA1 R1699W　/　NM_007294.4:c.5095C>T",
)
if query and st.query_params.get("q") != query:
    st.query_params["q"] = query

with st.expander("入力できる形式"):
    st.markdown(
        "- **遺伝子記号 + アミノ酸置換** — `BRCA1 p.Arg1699Trp` / `BRCA1 R1699W` / `TP53:p.R175H`\n"
        "- **HGVS 転写産物表記** — `NM_007294.4:c.5095C>T` / `NM_007294.4(BRCA1):c.5095C>T`\n\n"
        "転写産物は MANE Select を参照します。対象はミスセンス変異のみです。"
    )

if not query:
    st.stop()

missing_core = [k for k in ("mane", "cds", "alphamissense") if not avail.get(k)]
if missing_core:
    st.error("必要な索引がありません: "
             + "、".join(STEP_NAME[k] for k in missing_core))
    st.stop()


def _num(text: str, cast):
    try:
        return cast(text.strip()) if text.strip() else None
    except ValueError:
        return None


with st.spinner("照合しています…"):
    res = resolve(query, store)
    rep = build_report(
        res, thresholds,
        gnomad_af=_num(af_text, float),
        gnomad_hom=_num(hom_text, int),
        threshold_note=describe_thresholds(cfg.primary_model, thresholds),
    )

if rep.error:
    st.error(rep.error)
    st.stop()

for w in rep.warnings:
    st.warning(w)

col_gene, col_pop = st.columns(2)
with col_gene:
    st.subheader("遺伝子")
    for r in rep.gene_rows:
        st.write(f"**{r.label}** {r.value}")
        if r.note:
            st.caption(r.note)
with col_pop:
    st.subheader("集団頻度")
    for r in rep.population_rows:
        st.write(f"**{r.label}** {r.value}")
        if r.note:
            st.caption(r.note)

for i, vr in enumerate(rep.variants, 1):
    v = vr.variant
    st.divider()
    head = f"{v.gene} {v.hgvs_p}"
    if len(rep.variants) > 1:
        head += f"　（候補 {i} / {len(rep.variants)}）"
    st.header(head)
    st.caption(f"{v.genomic}（GRCh38）　転写産物 {v.refseq_nuc} / {v.enst}")

    st.subheader("FuncVEP（機能的影響の予測）")
    _cuts = "／".join(
        f"{m.split('_')[1]} {binary_cutoff(m, thresholds):.4f}" for m in FUNCVEP_MODELS
    )
    st.caption(f"スコアは damaging である確率。境はモデルごとに異なる（{_cuts}）。")
    cols = st.columns(len(FUNCVEP_MODELS))
    for c, model in zip(cols, FUNCVEP_MODELS):
        score = vr.variant.evidence.funcvep.get(model)
        a = vr.acmg.get(model)
        with c:
            st.markdown(f"**{model.replace('_', '-')}**")
            if score is None:
                st.markdown("### —")
                st.caption(FUNCVEP_MISSING_LABEL.get(
                    vr.funcvep_status, "スコアなし"))
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
            st.caption(a.label if a else "PP3/BP4 未較正")

    if vr.funcvep_note:
        st.info(vr.funcvep_note)

    with st.expander("各モデルの性格"):
        for r in vr.predictions:
            st.write(f"**{r.label}** {r.value}")
            st.caption(r.note)

    st.subheader("他の予測ツール")
    for r in vr.others:
        st.write(f"**{r.label}** {r.value}")
        st.caption(r.note)

    st.subheader("ClinVar")
    for r in vr.clinvar_rows:
        st.write(f"**{r.label}** {r.value}")
        if r.note:
            st.caption(r.note)

    st.subheader("指標同士の一致")
    st.info(f"{vr.concordance}　　{vr.concordance_detail}")

st.divider()
with st.expander("PP3/BP4 の閾値について"):
    st.text(rep.threshold_note)

st.subheader("解釈上の注意")
for d in DISCLAIMER:
    st.markdown("- " + d)

st.divider()
try:
    pdf = render_stream(rep, Path(cfg.pdf_font),
                        cache_dir=cfg.paths.index / "fonts")
    safe = "".join(ch if ch.isalnum() else "_" for ch in rep.query)[:60]
    st.download_button(
        "この内容を PDF で保存",
        data=pdf,
        file_name=f"variant_report_{safe}.pdf",
        mime="application/pdf",
        type="primary",
    )
except FileNotFoundError as exc:
    st.error(str(exc))
