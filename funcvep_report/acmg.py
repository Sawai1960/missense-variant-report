"""較正済み閾値を使って PP3/BP4 の証拠強度を割り当てる。

閾値そのものは scripts/03_calibrate_acmg.py が ClinVar から算出して
index/acmg_thresholds.json に書く。ここではその適用だけを行う。

強度の刻みは Tavtigian ら (2018) のベイズ枠組みに従う。
病原性側の尤度比の下限は点数 p に対して C^(p/8)（C = 350）。

段階の体系は閾値の由来で異なる。
- 論文の公表値: 1=Supporting, 2=Moderate, 3=Intermediate, 4=Strong
  （著者が 2026-09-07 に確認。doi:10.1016/j.gim.2025.101402 に従う。
  Very Strong は付かない）
- 自前の較正 (03_calibrate_acmg.py): Supporting/Moderate/Strong/Very Strong
どちらのキーが来ても扱えるよう、両方の段階を定義してある。
"""

from __future__ import annotations

from dataclasses import dataclass

C = 350.0

# 病原性側（PP3）の陽性尤度比の下限
LR_PATHOGENIC = {
    "supporting": C ** 0.125,    # 2.08
    "moderate": C ** 0.25,       # 4.33
    "intermediate": C ** 0.375,  # 9.02
    "strong": C ** 0.5,          # 18.7
    "very_strong": C,            # 350
}
# 良性側（BP4）は逆数
LR_BENIGN = {k: 1.0 / v for k, v in LR_PATHOGENIC.items()}

STRENGTH_JA = {
    "supporting": "Supporting",
    "moderate": "Moderate",
    "intermediate": "Intermediate",
    "strong": "Strong",
    "very_strong": "Very Strong",
}

# ACMG の点数（Tavtigian ら 2020 の加点方式。intermediate=3 は
# doi:10.1016/j.gim.2025.101402 の段階に合わせた）
POINTS = {"supporting": 1, "moderate": 2, "intermediate": 3, "strong": 4, "very_strong": 8}

_ORDER = ["very_strong", "strong", "intermediate", "moderate", "supporting"]


@dataclass(frozen=True)
class Assignment:
    criterion: str | None      # "PP3" / "BP4" / None
    strength: str | None       # "supporting" ...
    score: float

    @property
    def label(self) -> str:
        if self.criterion is None:
            return "該当なし（中間域）"
        return f"{self.criterion}_{STRENGTH_JA[self.strength]}"

    @property
    def points(self) -> int:
        if self.criterion is None:
            return 0
        p = POINTS[self.strength]
        return p if self.criterion == "PP3" else -p


def assign(score: float | None, model: str, thresholds: dict | None) -> Assignment | None:
    """スコアに PP3/BP4 を割り当てる。

    thresholds が None（未較正）または当該モデルの較正が無い場合は None を返し、
    呼び出し側は「未較正のため判定しない」と表示する。
    """
    if score is None or thresholds is None:
        return None
    t = (thresholds.get("models") or {}).get(model)
    if not t:
        return None

    for strength in _ORDER:
        cut = t.get("PP3", {}).get(strength)
        if cut is not None and score >= cut:
            return Assignment("PP3", strength, score)
    for strength in _ORDER:
        cut = t.get("BP4", {}).get(strength)
        if cut is not None and score <= cut:
            return Assignment("BP4", strength, score)
    return Assignment(None, None, score)


def binary_cutoff(model: str, thresholds: dict | None, default: float = 0.5) -> float:
    """damaging/neutral を分ける境。

    論文はモデルごとに異なる境を与えている（CTI 0.4196 / CTE 0.5193 / SP 0.4409）。
    公表値が無い場合だけ 0.5 に落ちる。
    """
    if thresholds is None:
        return default
    t = (thresholds.get("models") or {}).get(model) or {}
    cut = t.get("binary")
    return float(cut) if cut is not None else default


def describe_thresholds(model: str, thresholds: dict | None) -> str:
    """画面と PDF に出す、閾値の由来の説明文。"""
    if thresholds is None:
        return (
            "PP3/BP4 は未較正です。scripts/03_calibrate_acmg.py を実行すると、"
            "お手元の ClinVar から閾値を算出します。"
        )
    meta = thresholds.get("meta", {})
    t = (thresholds.get("models") or {}).get(model, {})

    if meta.get("source") == "published":
        lines = [
            f"閾値の由来: {meta.get('citation', '論文の公表値')}。",
            "著者から提供された公表値をそのまま使用しています（自前の較正ではありません）。",
        ]
    else:
        n_p, n_b = meta.get("n_pathogenic"), meta.get("n_benign")
        date = meta.get("clinvar_date", "?")
        head = (
            f"閾値の由来: ClinVar（{date} 時点、レビュー "
            f"{meta.get('min_review_stars', '?')} 星以上）の "
            f"病的 {n_p:,} 件 / 良性 {n_b:,} 件から自前で算出。"
            if isinstance(n_p, int) and isinstance(n_b, int)
            else f"閾値の由来: ClinVar（{date} 時点）から自前で算出。"
        )
        lines = [
            head,
            f"事前確率 {meta.get('prior_pathogenic', '?')}、"
            f"ブートストラップ {meta.get('bootstrap', '?')} 回の保守的な下限を採用。",
            "論文の公表値ではないため、論文の判定とは一致しません。",
        ]

    for crit in ("PP3", "BP4"):
        parts = [
            f"{STRENGTH_JA[s]} {t[crit][s]:.4f}"
            for s in _ORDER if t.get(crit, {}).get(s) is not None
        ]
        if parts:
            arrow = "以上" if crit == "PP3" else "以下"
            lines.append(f"{crit}: " + " / ".join(parts) + f" {arrow}")

    cut = t.get("binary")
    if cut is not None:
        lines.append(f"damaging/neutral の境: {cut:.4f}（モデルごとに異なる。0.5 ではない）")
    return "\n".join(lines)
