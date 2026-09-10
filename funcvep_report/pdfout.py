"""レポートを PDF に書き出す。日本語は Windows 同梱の Noto Sans JP を使う。

同梱の NotoSansJP-VF.ttf は可変フォントで、既定の太さが Thin（wght=100）のため
そのまま埋め込むと極端に細く印字される。初回に wght=400 と 700 の静的フォントを
切り出して data_root/index/fonts に置き、以後はそれを使う。
"""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

from fpdf import FPDF

from .i18n import t, use_lang
from .report import acknowledgement, Report, Row, disclaimer, funcvep_intro, references

INK = (26, 26, 26)
MUTED = (110, 110, 110)
RULE = (208, 208, 208)
ACCENT = (28, 78, 128)

_WEIGHTS = {"regular": 400, "bold": 700}


@dataclass(frozen=True)
class FontSpec:
    """PDF の本文フォント。

    regular  通常の書体。TTF（静的・可変どちらも可）または TTC
    bold     太字の書体。省略時は regular から作る（可変フォントなら太いウェイト、
             そうでなければ同じ書体）
    face     TTC の中の書体名（例 "BIZ UDPGothic"）。TTC でなければ無視
    """
    regular: Path
    bold: Path | None = None
    face: str | None = None
    # 本文フォントに無い字形を補う書体（日本語版なら英文フォント、英語版なら日本語フォント）
    fallback: "FontSpec | None" = None


def fonts_for(cfg, lang: str) -> FontSpec:
    """設定から、言語に応じた本文フォントと補助フォントの組を作る。

    日本語版は日本語フォントを本文にし、無い字形（トルコ語の ı ş など）を英文フォントで補う。
    英語版は英文フォントを本文にし、日本語が混じったときだけ日本語フォントで補う。
    """
    jp = FontSpec(cfg.pdf_font, cfg.pdf_font_bold, cfg.pdf_font_face)
    en = FontSpec(cfg.pdf_font_en, cfg.pdf_font_en_bold) if cfg.pdf_font_en else None
    if lang == "en" and en is not None and en.regular.exists():
        return FontSpec(en.regular, en.bold, None, fallback=jp)
    return FontSpec(jp.regular, jp.bold, jp.face, fallback=en)


def _extract_from_ttc(src: Path, face: str | None, dest: Path) -> Path:
    """TTC から 1 書体を取り出して TTF として保存する。既にあれば作り直さない。"""
    if dest.exists():
        return dest
    from fontTools.ttLib import TTCollection

    col = TTCollection(str(src))
    want = (face or "").replace(" ", "").lower()
    chosen = col.fonts[0]
    if want:
        for f in col.fonts:
            name = (f["name"].getDebugName(1) or "").replace(" ", "").lower()
            if name == want:
                chosen = f
                break
    chosen.save(str(dest))
    return dest


def prepare_fonts(src: Path | FontSpec, cache_dir: Path) -> dict[str, Path]:
    """使うフォントファイルを整える。

    TTC なら書体を取り出し、可変フォントなら静的なウェイトを切り出す。
    既定の C:/Windows/Fonts は書き込めないので、結果は cache_dir に置く。
    """
    cache_dir.mkdir(parents=True, exist_ok=True)
    spec = src if isinstance(src, FontSpec) else FontSpec(regular=src)
    if spec.regular.suffix.lower() == ".ttc":
        tag = (spec.face or "0").replace(" ", "")
        regular = _extract_from_ttc(spec.regular, spec.face, cache_dir / f"{spec.regular.stem}-{tag}.ttf")
        bold = regular
        if spec.bold and spec.bold.exists():
            bold = _extract_from_ttc(spec.bold, spec.face, cache_dir / f"{spec.bold.stem}-{tag}.ttf")
        return {"regular": regular, "bold": bold}
    if spec.bold and spec.bold.exists() and "fvar" not in _tables(spec.regular):
        return {"regular": spec.regular, "bold": spec.bold}
    src = spec.regular
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
    def __init__(self, fonts: dict[str, Path], title: str, wrap: str = "CHAR",
                 organization: str = "", fallback: dict[str, Path] | None = None):
        super().__init__(orientation="P", unit="mm", format="A4")
        self.title_text = title
        self.organization = organization
        # 日本語は単語間に空白が無いので、fpdf 既定の「空白で折り返す」だと
        # 途中の半角空白（数字や英単語の前後）で不自然に改行される。文字単位で
        # 折り返す。英語は単語単位のまま。両端揃えは日本語で間延びするので使わない。
        self.wrap = wrap
        self.set_auto_page_break(auto=True, margin=18)
        # 家族名 "jp" は歴史的な名残で、実際には言語に応じた本文フォントが入る
        self.add_font("jp", "", str(fonts["regular"]))
        self.add_font("jp", "B", str(fonts["bold"]))
        if fallback:
            self.add_font("fb", "", str(fallback["regular"]))
            self.add_font("fb", "B", str(fallback["bold"]))
            self.set_fallback_fonts(["fb"])
        self.set_margins(16, 16, 16)

    def mc(self, w: float, h: float, text: str, align: str = "L",
           wrap: str | None = None) -> None:
        self.multi_cell(w, h, text, align=align, wrapmode=wrap or self.wrap)

    def footer(self) -> None:
        # 本文と見分けられるよう、フッターの上に細い横線を引く
        self.set_y(-16)
        self.set_draw_color(*RULE)
        self.set_line_width(0.25)
        self.line(self.l_margin, self.get_y(), self.w - self.r_margin, self.get_y())
        self.set_y(-14)
        self.set_font("jp", size=7.5)
        self.set_text_color(*MUTED)
        wide = t("sep.wide")
        left = f"{self.organization}{wide}{self.title_text}" if self.organization else self.title_text
        self.cell(0, 5, f"{left}{wide}—{wide}{self.page_no()} / {{nb}}", align="C")


def _h1(doc: _Doc, text: str) -> None:
    doc.set_font("jp", "B", size=15)
    doc.set_text_color(*INK)
    doc.mc(0, 7.5, text)
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


def _band(doc: _Doc, text: str) -> None:
    """変異ごとの区切り。青地に白文字の帯にして、他の節見出しと見分けられるようにする。"""
    doc.ln(3)
    doc.set_font("jp", "B", size=12)
    doc.set_fill_color(*ACCENT)
    doc.set_text_color(255, 255, 255)
    doc.cell(0, 9, "  " + text, fill=True, new_x="LMARGIN", new_y="NEXT")
    doc.set_text_color(*INK)
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
        doc.mc(label_w, 5, r.label)
        after_label = doc.get_y()

        doc.set_xy(doc.l_margin + label_w, top)
        doc.set_font("jp", size=9.5)
        doc.set_text_color(*INK)
        doc.mc(value_w, 5, r.value)
        after_value = doc.get_y()

        if r.note:
            doc.set_x(doc.l_margin + label_w)
            doc.set_font("jp", size=7.5)
            doc.set_text_color(*MUTED)
            doc.mc(value_w, 4, r.note)
            after_value = doc.get_y()

        doc.set_y(max(after_label, after_value) + 1.2)


def _para(doc: _Doc, text: str, size: float = 8.5,
          color: tuple[int, int, int] = MUTED, wrap: str | None = None) -> None:
    doc.set_font("jp", size=size)
    doc.set_text_color(*color)
    doc.mc(0, 4.6, text, wrap=wrap)
    doc.ln(0.8)


def _tables(path: Path) -> set[str]:
    from fontTools.ttLib import TTFont
    return set(TTFont(str(path), lazy=True).keys())


def render(rep: Report, font_path: Path | FontSpec, cache_dir: Path | None = None) -> bytes:
    """レポートを PDF にする。見出しの言語はレポート作成時の言語に合わせる。"""
    with use_lang(rep.lang):
        return _render(rep, font_path, cache_dir)


def _render(rep: Report, font_path: Path | FontSpec, cache_dir: Path | None) -> bytes:
    regular = font_path.regular if isinstance(font_path, FontSpec) else font_path
    if not regular.exists():
        raise FileNotFoundError(t("pdf.font_missing", path=regular))
    cache = cache_dir or (Path.home() / ".cache" / "funcvep_report" / "fonts")
    fonts = prepare_fonts(font_path, cache)
    fallback = None
    if isinstance(font_path, FontSpec) and font_path.fallback and font_path.fallback.regular.exists():
        fallback = prepare_fonts(font_path.fallback, cache)
    bullet = "・" if rep.lang == "ja" else "- "
    wide = t("sep.wide")

    doc = _Doc(fonts, t("pdf.title"), wrap="CHAR" if rep.lang == "ja" else "WORD",
               organization=rep.organization, fallback=fallback)
    doc.alias_nb_pages()
    doc.add_page()

    if rep.organization:
        # 発行元は表題の上に小さく置く
        doc.set_font("jp", size=9)
        doc.set_text_color(*MUTED)
        doc.cell(0, 5, rep.organization, new_x="LMARGIN", new_y="NEXT")
        doc.ln(0.5)
    _h1(doc, t("pdf.title"))
    # 評価対象の変異は見出しに準じて大きく黒で。作成日時は控えめに
    doc.set_font("jp", "B", size=13)
    doc.set_text_color(0, 0, 0)
    doc.mc(0, 7, t("pdf.query", query=rep.query))
    doc.ln(0.5)   # 全幅 multi_cell の直後は x が右端に残り、次の幅が 0 になって無限ループする
    doc.set_font("jp", size=8.5)
    doc.set_text_color(*MUTED)
    doc.mc(0, 4.6, t("pdf.created", created=rep.created))
    doc.ln(1)

    if rep.error:
        _h2(doc, t("pdf.unresolved"))
        _para(doc, rep.error, size=9.5, color=INK)
        return bytes(doc.output())

    _h2(doc, t("pdf.target"))
    _rows(doc, rep.target_rows)

    if rep.warnings:
        _h2(doc, t("pdf.warnings"))
        for w in rep.warnings:
            _para(doc, bullet + w)

    _h2(doc, t("pdf.gene"))
    _rows(doc, rep.gene_rows)

    if rep.population_rows:
        _h2(doc, t("pdf.population"))
        _rows(doc, rep.population_rows)

    for i, vr in enumerate(rep.variants, 1):
        v = vr.variant
        head = (t("pdf.variant_n", i=i, n=len(rep.variants))
                if len(rep.variants) > 1 else t("pdf.variant"))
        if i > 1:
            doc.add_page()   # 候補が複数あるときは 2 つ目以降を改ページして始める
        _band(doc, f"{head}{wide}{v.gene} {v.hgvs_p3}{wide}{v.genomic}")

        _h2(doc, t("pdf.population_gnomad"))
        _rows(doc, vr.population_rows)

        _h2(doc, t("pdf.funcvep"))
        if i == 1:
            _para(doc, funcvep_intro())
        _rows(doc, vr.predictions)
        if vr.funcvep_note:
            _para(doc, vr.funcvep_note)

        _h2(doc, t("pdf.others"))
        _rows(doc, vr.others)
        if vr.mave_rows:
            _h2(doc, t("pdf.mave"))
            _rows(doc, vr.mave_rows)

        _h2(doc, t("pdf.concordance"))
        _rows(doc, vr.concordance_rows)

        _h2(doc, t("pdf.clinvar"))
        _rows(doc, vr.clinvar_rows)
        if vr.residue_rows:
            _h2(doc, t("pdf.residue"))
            _rows(doc, vr.residue_rows)

    if rep.threshold_note:
        _h2(doc, t("pdf.thresholds"))
        _para(doc, rep.threshold_note)

    _h2(doc, t("pdf.disclaimer"))
    for d in disclaimer():
        _para(doc, bullet + d)

    _h2(doc, t("pdf.acknowledgement"))
    _para(doc, acknowledgement())

    _h2(doc, t("pdf.references"))
    for n, ref in enumerate(references(), 1):
        # 書誌は英文が主なので、日本語版でも単語単位で折り返す
        _para(doc, f"{n}. {ref}", size=7.5, wrap="WORD")

    return bytes(doc.output())


def render_to(rep: Report, font_path: Path | FontSpec, dest: Path,
              cache_dir: Path | None = None) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(render(rep, font_path, cache_dir))
    return dest


def render_stream(rep: Report, font_path: Path | FontSpec,
                  cache_dir: Path | None = None) -> BytesIO:
    return BytesIO(render(rep, font_path, cache_dir))
