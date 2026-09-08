"""レポートを PDF に書き出す。日本語は Windows 同梱の Noto Sans JP を使う。

同梱の NotoSansJP-VF.ttf は可変フォントで、既定の太さが Thin（wght=100）のため
そのまま埋め込むと極端に細く印字される。初回に wght=400 と 700 の静的フォントを
切り出して data_root/index/fonts に置き、以後はそれを使う。
"""

from __future__ import annotations

from io import BytesIO
from pathlib import Path

from fpdf import FPDF

from .i18n import t, use_lang
from .report import Report, Row, disclaimer

INK = (26, 26, 26)
MUTED = (110, 110, 110)
RULE = (208, 208, 208)
ACCENT = (28, 78, 128)

_WEIGHTS = {"regular": 400, "bold": 700}


def prepare_fonts(src: Path, cache_dir: Path) -> dict[str, Path]:
    """可変フォントから静的なウェイトを切り出す。既にあれば作り直さない。"""
    cache_dir.mkdir(parents=True, exist_ok=True)
    out = {}
    for name, wght in _WEIGHTS.items():
        dest = cache_dir / f"{src.stem}-{wght}.ttf"
        out[name] = dest
        if dest.exists():
            continue
        from fontTools.ttLib import TTFont
        from fontTools.varLib import instancer

        font = TTFont(str(src))
        if "fvar" not in font:
            # 可変フォントでなければそのまま使う
            out[name] = src
            continue
        instancer.instantiateVariableFont(font, {"wght": wght}, inplace=True)
        font.save(str(dest))
    return out


class _Doc(FPDF):
    def __init__(self, fonts: dict[str, Path], title: str):
        super().__init__(orientation="P", unit="mm", format="A4")
        self.title_text = title
        self.set_auto_page_break(auto=True, margin=18)
        self.add_font("jp", "", str(fonts["regular"]))
        self.add_font("jp", "B", str(fonts["bold"]))
        self.set_margins(16, 16, 16)

    def footer(self) -> None:
        self.set_y(-14)
        self.set_font("jp", size=7.5)
        self.set_text_color(*MUTED)
        self.cell(0, 5, f"{self.title_text}{t('sep.wide')}—{t('sep.wide')}{self.page_no()} / {{nb}}",
                  align="C")


def _h1(doc: _Doc, text: str) -> None:
    doc.set_font("jp", "B", size=15)
    doc.set_text_color(*INK)
    doc.multi_cell(0, 7.5, text)
    doc.ln(1)


def _h2(doc: _Doc, text: str) -> None:
    doc.ln(2.5)
    doc.set_font("jp", "B", size=10.5)
    doc.set_text_color(*ACCENT)
    doc.cell(0, 6, text, new_x="LMARGIN", new_y="NEXT")
    doc.set_draw_color(*RULE)
    doc.set_line_width(0.25)
    y = doc.get_y()
    doc.line(doc.l_margin, y, doc.w - doc.r_margin, y)
    doc.ln(1.5)


def _rows(doc: _Doc, rows: list[Row], label_w: float = 42.0) -> None:
    avail = doc.w - doc.l_margin - doc.r_margin
    value_w = avail - label_w
    for r in rows:
        # ラベルと値は同じ高さから書き始める。ラベルの描画中に自動改ページが
        # 起きると値だけが前ページの高さに戻されて空白ページができるので、
        # 行の頭で余白が足りなければ先に改ページしておく。
        if doc.get_y() > doc.h - doc.b_margin - 14:
            doc.add_page()
        doc.set_font("jp", size=8.5)
        doc.set_text_color(*MUTED)
        top = doc.get_y()
        doc.multi_cell(label_w, 5, r.label, align="L")
        after_label = doc.get_y()

        doc.set_xy(doc.l_margin + label_w, top)
        doc.set_font("jp", size=9.5)
        doc.set_text_color(*INK)
        doc.multi_cell(value_w, 5, r.value, align="L")
        after_value = doc.get_y()

        if r.note:
            doc.set_x(doc.l_margin + label_w)
            doc.set_font("jp", size=7.5)
            doc.set_text_color(*MUTED)
            doc.multi_cell(value_w, 4, r.note, align="L")
            after_value = doc.get_y()

        doc.set_y(max(after_label, after_value) + 1.2)


def _para(doc: _Doc, text: str, size: float = 8.5,
          color: tuple[int, int, int] = MUTED) -> None:
    doc.set_font("jp", size=size)
    doc.set_text_color(*color)
    doc.multi_cell(0, 4.6, text)
    doc.ln(0.8)


def render(rep: Report, font_path: Path, cache_dir: Path | None = None) -> bytes:
    """レポートを PDF にする。見出しの言語はレポート作成時の言語に合わせる。"""
    with use_lang(rep.lang):
        return _render(rep, font_path, cache_dir)


def _render(rep: Report, font_path: Path, cache_dir: Path | None) -> bytes:
    if not font_path.exists():
        raise FileNotFoundError(t("pdf.font_missing", path=font_path))
    # 既定の C:\Windows\Fonts は書き込めないので、必ず書ける場所に切り出す
    fonts = prepare_fonts(
        font_path,
        cache_dir or (Path.home() / ".cache" / "funcvep_report" / "fonts"),
    )
    bullet = "・" if rep.lang == "ja" else "- "
    wide = t("sep.wide")

    doc = _Doc(fonts, t("pdf.title"))
    doc.alias_nb_pages()
    doc.add_page()

    _h1(doc, t("pdf.title"))
    doc.set_font("jp", size=8.5)
    doc.set_text_color(*MUTED)
    doc.multi_cell(0, 4.6, t("pdf.meta", query=rep.query, created=rep.created))
    doc.ln(1)

    if rep.error:
        _h2(doc, t("pdf.unresolved"))
        _para(doc, rep.error, size=9.5, color=INK)
        return bytes(doc.output())

    if rep.warnings:
        _h2(doc, t("pdf.warnings"))
        for w in rep.warnings:
            _para(doc, bullet + w)

    _h2(doc, t("pdf.gene"))
    _rows(doc, rep.gene_rows)

    _h2(doc, t("pdf.population"))
    _rows(doc, rep.population_rows)

    for i, vr in enumerate(rep.variants, 1):
        v = vr.variant
        head = (t("pdf.variant_n", i=i, n=len(rep.variants))
                if len(rep.variants) > 1 else t("pdf.variant"))
        _h2(doc, f"{head}{wide}{v.gene} {v.hgvs_p}")
        _rows(doc, [
            Row(t("row.genomic"), str(v.genomic), "GRCh38"),
            Row(t("row.transcript"), f"{v.refseq_nuc}{wide}{v.enst}", ""),
        ])

        _h2(doc, t("pdf.funcvep"))
        _rows(doc, vr.predictions)
        if vr.funcvep_note:
            _para(doc, vr.funcvep_note)

        _h2(doc, t("pdf.others"))
        _rows(doc, vr.others)

        _h2(doc, t("pdf.clinvar"))
        _rows(doc, vr.clinvar_rows)

        _h2(doc, t("pdf.concordance"))
        _rows(doc, [Row(t("row.summary"), vr.concordance, vr.concordance_detail)])

    if rep.threshold_note:
        _h2(doc, t("pdf.thresholds"))
        _para(doc, rep.threshold_note)

    _h2(doc, t("pdf.disclaimer"))
    for d in disclaimer():
        _para(doc, bullet + d)

    return bytes(doc.output())


def render_to(rep: Report, font_path: Path, dest: Path,
              cache_dir: Path | None = None) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(render(rep, font_path, cache_dir))
    return dest


def render_stream(rep: Report, font_path: Path,
                  cache_dir: Path | None = None) -> BytesIO:
    return BytesIO(render(rep, font_path, cache_dir))
