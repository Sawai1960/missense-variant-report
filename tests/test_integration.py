"""索引を使う統合テスト。設計レビュー（2026-09-10）の確認項目のうち、索引が要るもの。

索引（config.yaml の data_root/index）が無い環境では飛ばす。オンライン照会は行わない
（画面のテストでは外部データベースへの照会をオフにする）。

  1  同じ p. を生む 2 種類の塩基置換を c. で入力 → 入力した塩基置換だけを評価
  2  遺伝子・転写産物・c.・p. の矛盾 → 未解決として止める
  6  別の変異を続けて照会 → 前の変異のデータや手入力が混入しない
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from funcvep_report import load_config  # noqa: E402
from funcvep_report.i18n import use_lang  # noqa: E402

try:
    _CFG = load_config()
    HAVE_INDEX = _CFG.paths.funcvep.exists() and _CFG.paths.mane.exists()
except Exception:      # 設定が読めない環境
    _CFG = None
    HAVE_INDEX = False


@unittest.skipUnless(HAVE_INDEX, "索引が無いので飛ばす")
class TestResolveWithIndex(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from funcvep_report.lookup import Store
        cls.store = Store(_CFG)

    def _resolve(self, text):
        from funcvep_report.lookup import resolve
        with use_lang("ja"):
            return resolve(text, self.store)

    def test_c_notation_keeps_only_the_entered_base_change(self):
        # FGFR3 p.Gly380Arg は c.1138G>A と c.1138G>C の 2 通り。c. で入力すれば 1 つに絞る
        res = self._resolve("FGFR3 p.Gly380Arg")
        self.assertIsNone(res.error)
        self.assertEqual(len(res.variants), 2)
        res = self._resolve("NM_000142.5:c.1138G>A")
        self.assertIsNone(res.error, res.error)
        self.assertEqual(len(res.variants), 1)
        self.assertEqual((res.variants[0].genomic.ref, res.variants[0].genomic.alt), ("G", "A"))
        self.assertEqual(res.variants[0].hgvs_c, "c.1138G>A")
        self.assertTrue(res.resolution_path)

    def test_contradictions_stop_the_evaluation(self):
        res = self._resolve("NM_000142.5:c.1138G>A (p.Gly380Val)")     # c. と p. の食い違い
        self.assertTrue(res.error and "一致しません" in res.error, res.error)
        self.assertEqual(res.variants, [])
        res = self._resolve("BRCA1 NM_000142.5:c.1138G>A")             # 遺伝子と転写産物の食い違い
        self.assertTrue(res.error and "一致しません" in res.error, res.error)
        res = self._resolve("NM_000142.5:c.1138T>A")                    # 参照塩基が CDS と合わない
        self.assertTrue(res.error, res.error)

    def test_version_only_difference_resolves_with_note(self):
        res = self._resolve("NM_000142.4:c.1138G>A")
        self.assertIsNone(res.error, res.error)
        self.assertIn("NM_000142.4", res.transcript_note)


@unittest.skipUnless(HAVE_INDEX, "索引が無いので飛ばす")
class TestAppNoCarryOver(unittest.TestCase):
    """別の変異を続けて照会したとき、前の変異の結果や手入力が混入しないこと（画面）。"""

    def test_second_query_does_not_carry_first(self):
        from streamlit.testing.v1 import AppTest
        at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=300)
        at.run()
        at.sidebar.checkbox[0].set_value(False).run()   # 外部データベースへの照会をオフ
        at.text_input("query_input").set_value("BRCA1 p.Arg1699Trp").run()
        # 1 つ目の変異に手入力の頻度を入れる
        af_keys = [w.key for w in at.text_input if w.key and w.key.startswith("af_manual::")]
        self.assertEqual(len(af_keys), 1)
        at.text_input(af_keys[0]).set_value("0.001").run()
        page1 = "\n".join(m.value for m in at.markdown)
        self.assertIn("BRCA1", page1)
        self.assertIn("1.000e-03", page1)
        # 2 つ目の変異
        at.text_input("query_input").set_value("HBB p.Glu7Val").run()
        self.assertEqual([e.value for e in at.exception], [])
        page2 = "\n".join(m.value for m in at.markdown)
        self.assertIn("HBB", page2)
        self.assertNotIn("**変異** BRCA1", page2)
        self.assertNotIn("1.000e-03", page2)           # 前の変異の手入力が残らない
        af_keys2 = [w.key for w in at.text_input if w.key and w.key.startswith("af_manual::")]
        self.assertEqual(at.text_input(af_keys2[0]).value, "")


if __name__ == "__main__":
    unittest.main()
