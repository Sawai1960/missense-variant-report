"""PDF 出力のテスト。

予測ツールの判定のまとめ（色付きの箱）は、一度見えない状態で描いて高さを測り、
背景を塗ってから本番を描く。箱がページ下端近くから始まると、測定の途中で改ページが
起きて高さが負になり、背景が上向きに塗られて前の本文を覆い隠した（2026-11-05、
APOB c.12809G>C の PDF の 2 ページ目）。その再発を防ぐ。

フォント（config.yaml の pdf_font）が無い環境では飛ばす。
"""

from __future__ import annotations

import sys
import tempfile
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from funcvep_report import load_config  # noqa: E402
from funcvep_report.i18n import t, use_lang  # noqa: E402
from funcvep_report.report import Row  # noqa: E402

try:
    _CFG = load_config()
    HAVE_FONT = Path(_CFG.pdf_font).exists()
except Exception:      # 設定が読めない環境
    _CFG = None
    HAVE_FONT = False


@unittest.skipUnless(HAVE_FONT, "PDF のフォントが無いので飛ばす")
class TestSummaryBox(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from funcvep_report.pdfout import fonts_for, prepare_fonts
        cls._tmp = tempfile.TemporaryDirectory()
        cache = _CFG.paths.index / "fonts"
        if not cache.exists():
            cache = Path(cls._tmp.name)
        spec = fonts_for(_CFG, "ja")
        cls.fonts = prepare_fonts(spec, cache)

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def _box(self, start_y_from_bottom: float, heading: str | None = None):
        """ページ下端から start_y_from_bottom mm 上で箱を描き、塗った四角を返す。"""
        from funcvep_report.pdfout import _Doc, _summary_box
        with use_lang("ja"):
            doc = _Doc(self.fonts, "test")
            doc.add_page()
            doc.set_y(doc.h - doc.b_margin - start_y_from_bottom)
            rects = []
            original = doc.rect

            def record(x, y, w, h, style=None, *args, **kwargs):
                rects.append((doc.page, y, h))
                return original(x, y, w, h, style, *args, **kwargs)

            doc.rect = record
            self.headings = []
            original_cell = doc.cell

            def record_cell(w=None, h=None, text="", *args, **kwargs):
                # 高さを測るための見えない描画（_disable_writing 中）は数えない
                writing = isinstance(doc._out, types.MethodType)
                if heading and text == heading and writing:
                    self.headings.append(doc.page)
                return original_cell(w, h, text, *args, **kwargs)

            doc.cell = record_cell
            rows = [
                Row("damaging（機能を損なう）側", "なし"),
                Row("neutral（影響なし）側", "FuncVEP-CTI、FuncVEP-CTE、FuncVEP-SP、AlphaMissense、REVEL"),
                Row(t("row.summary"), "5 ツールすべてが neutral（影響なし）側"),
            ]
            _summary_box(doc, rows, "neutral", heading=heading)
            return doc, rects

    def test_box_near_page_bottom_moves_whole_to_next_page(self):
        doc, rects = self._box(12)
        self.assertEqual(len(rects), 1)
        page, y, h = rects[0]
        self.assertGreater(h, 0, "背景の高さが負: 上向きに塗られて前の本文を隠す")
        self.assertEqual(page, 2, "収まらない箱は次のページへ送る")
        self.assertLessEqual(y + h, doc.h - doc.b_margin + 0.01, "箱がページの下余白にはみ出す")
        self.assertEqual(doc.page, 2, "箱の注意書きがさらに次のページへ押し出された")

    def test_heading_moves_with_box(self):
        # 見出しは入るが箱は入らない位置: 見出しだけがページ末に残ってはいけない
        doc, rects = self._box(20, heading="予測ツールの判定のまとめ")
        page, y, h = rects[0]
        self.assertEqual(page, 2)
        self.assertEqual(self.headings, [2], "見出しが箱と別のページに書かれた")

    def test_box_mid_page_stays(self):
        doc, rects = self._box(150)
        self.assertEqual(len(rects), 1)
        page, y, h = rects[0]
        self.assertGreater(h, 0)
        self.assertEqual(page, 1)
        self.assertEqual(doc.page, 1)


if __name__ == "__main__":
    unittest.main()
