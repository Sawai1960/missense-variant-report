"""FuncVEP / ClinVEP 6 モデルの学習セットを取得して索引化する。

公開予測表にスコアが無い変異には 2 通りある。

  空欄  一部のモデルの学習に使われた変異。行はあるがそのモデルの列が空。
  不在  6 モデル全部の学習に使われた変異。全モデルの推論から除かれた結果、
        統合テーブルから行ごと消える。

後者は著者（Kayaalp ら, 2026-09-05 私信）が確認した仕様であり、生物学的・
配列的・QC 上の除外ではない。すなわち「収録が無いこと」自体は病原性についても
予測の信頼度についても何ら情報を持たない。この事実を画面で言えるようにするため、
学習セットを取得して手元に持つ。

学習セットは FuncVEP リポジトリで公開されている。
  https://github.com/OzcelikLab/FuncVEP/tree/main/models

出力: index/training_sets.parquet
  variant_id  '17-43063931-G-A' 形式。予測表・索引と同じ鍵。
  ensg        リポジトリが併記している遺伝子 ID
  models      その変異を学習に使ったモデル名をカンマで連結
  n_models    同上の個数（6 なら統合テーブルから消えている）
"""

from __future__ import annotations

import io
import sys
import urllib.error
import urllib.request
from collections import defaultdict
from pathlib import Path

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from funcvep_report.config import MODELS, load_config  # noqa: E402

RAW_URL = (
    "https://raw.githubusercontent.com/OzcelikLab/FuncVEP/main/"
    "models/{model}/training_set.txt"
)
TIMEOUT = 120


def fetch(model: str) -> bytes:
    url = RAW_URL.format(model=model)
    req = urllib.request.Request(url, headers={"User-Agent": "funcvep-report/1.0"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return r.read()


def parse(blob: bytes, model: str) -> list[tuple[str, str]]:
    """(variant_id, ensg) を返す。1 行目は見出し。"""
    out: list[tuple[str, str]] = []
    stream = io.StringIO(blob.decode("utf-8", "replace"))
    header = stream.readline().rstrip("\n").split("\t")
    if header[:1] != ["ID"]:
        raise SystemExit(f"{model}: 想定と違う見出しです: {header}")
    for line in stream:
        parts = line.rstrip("\n").split("\t")
        if len(parts) < 2 or not parts[0]:
            continue
        out.append((parts[0].strip(), parts[1].strip()))
    return out


def main() -> None:
    cfg = load_config()
    raw_dir = cfg.paths.raw / "training_sets"
    raw_dir.mkdir(parents=True, exist_ok=True)
    out_path = cfg.paths.index / "training_sets.parquet"

    members: dict[str, set[str]] = defaultdict(set)
    ensg_of: dict[str, str] = {}

    for model in MODELS:
        cached = raw_dir / f"{model}.txt"
        if cached.exists() and cached.stat().st_size > 0:
            blob = cached.read_bytes()
            note = "既取得"
        else:
            try:
                blob = fetch(model)
            except urllib.error.URLError as e:
                raise SystemExit(
                    f"{model} の取得に失敗しました: {e}\n"
                    "ネットワークに接続してから再実行してください。"
                )
            cached.write_bytes(blob)
            note = "取得"
        rows = parse(blob, model)
        for vid, ensg in rows:
            members[vid].add(model)
            ensg_of.setdefault(vid, ensg)
        print(f"  {model:14} {len(rows):>7,} 件　{note}")

    ids = sorted(members)
    table = pa.table({
        "variant_id": pa.array(ids, pa.string()),
        "ensg": pa.array([ensg_of.get(v, "") for v in ids], pa.string()),
        "models": pa.array([",".join(sorted(members[v])) for v in ids], pa.string()),
        "n_models": pa.array([len(members[v]) for v in ids], pa.int8()),
    })
    out_path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, out_path, compression="zstd")

    con = duckdb.connect()
    dist = con.execute(
        "SELECT n_models, count(*) AS n FROM read_parquet(?) GROUP BY 1 ORDER BY 1",
        [str(out_path)],
    ).fetchall()
    con.close()

    print(f"\n{out_path} に {len(ids):,} 変異を保存しました。")
    print("\n何モデルの学習に使われたか")
    for n, c in dist:
        tail = "　← 統合テーブルから行ごと消える" if n == len(MODELS) else ""
        print(f"  {n} モデル: {c:>7,} 件{tail}")


if __name__ == "__main__":
    main()
