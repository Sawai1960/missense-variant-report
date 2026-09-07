"""参照データを data_root/raw へダウンロードする。

中断しても再実行すれば途中から再開する（HTTP Range を使う）。
    python scripts/01_download.py            すべて
    python scripts/01_download.py mane clinvar   一部だけ
    python scripts/01_download.py --list     一覧と容量の確認のみ
"""

from __future__ import annotations

import os
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

import requests

# 1 本の接続あたりの速度が出ない配布元（Zenodo など）向けに、
# 範囲リクエストで分割して同時に取る。
PARALLEL_CONNECTIONS = int(os.environ.get("FUNCVEP_DL_CONNECTIONS", "6"))
PARALLEL_MIN_BYTES = 200 << 20      # これより小さいファイルは分割しない

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from funcvep_report.config import load_config  # noqa: E402

MANE_BASE = "https://ftp.ncbi.nlm.nih.gov/refseq/MANE/MANE_human/current"


@dataclass(frozen=True)
class Source:
    key: str
    filename: str
    url: str
    approx_bytes: int
    note: str
    license: str


SOURCES: list[Source] = [
    Source(
        key="mane",
        filename="MANE.summary.txt.gz",
        url=f"{MANE_BASE}/MANE.GRCh38.v1.5.summary.txt.gz",
        approx_bytes=1_100_000,
        note="遺伝子記号・RefSeq(NM)・Ensembl(ENST)・ENSG の対応表",
        license="NCBI public domain",
    ),
    Source(
        key="mane",
        filename="MANE.refseq_rna.gbff.gz",
        url=f"{MANE_BASE}/MANE.GRCh38.v1.5.refseq_rna.gbff.gz",
        approx_bytes=87_000_000,
        note="転写産物の CDS 配列。HGVS c. 表記からアミノ酸変化を求めるのに使う",
        license="NCBI public domain",
    ),
    Source(
        key="clinvar",
        filename="variant_summary.txt.gz",
        url="https://ftp.ncbi.nlm.nih.gov/pub/clinvar/tab_delimited/variant_summary.txt.gz",
        approx_bytes=442_477_016,
        note="ClinVar の臨床的意義とレビュー状態",
        license="NCBI public domain",
    ),
    Source(
        key="alphamissense",
        filename="AlphaMissense_hg38.tsv.gz",
        url=("https://zenodo.org/records/10813168/files/"
             "AlphaMissense_hg38.tsv.gz?download=1"),
        approx_bytes=643_000_000,
        note="AlphaMissense スコア。アミノ酸変化とゲノム座標を橋渡しする要のファイル",
        license="CC BY-NC-SA 4.0（非商用）",
    ),
    Source(
        key="revel",
        filename="revel-v1.3_all_chromosomes.zip",
        url="https://rothsj06.dmz.hpc.mssm.edu/revel-v1.3_all_chromosomes.zip",
        approx_bytes=526_000_000,
        note="REVEL スコア",
        license="非商用利用は無償",
    ),
    Source(
        key="constraint",
        filename="gnomad_constraint_metrics.txt",
        url=("https://raw.githubusercontent.com/OzcelikLab/FuncVEP/main/"
             "resources/gene_level_features/gnomad_constraint_metrics.txt"),
        approx_bytes=3_000_000,
        note="gnomAD の遺伝子レベル制約指標（pLI・missense z など）",
        license="gnomAD は CC0",
    ),
    Source(
        key="funcvep",
        filename="FuncVEP_and_ClinVEP_scores.zip",
        url=("https://zenodo.org/records/20595206/files/"
             "FuncVEP_and_ClinVEP_scores_all_possible_missense_variants.zip?download=1"),
        approx_bytes=4_236_523_156,
        note="本体。全 7,300 万ミスセンス変異の FuncVEP/ClinVEP スコア",
        license="PolyForm Strict 1.0.0（非商用・再配布不可）",
    ),
]


def human(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:,.1f} {unit}"
        n /= 1024
    return f"{n:.1f} GB"


def _supports_range(url: str) -> bool:
    """1 バイトだけ範囲要求して 206 が返るかを確かめる。

    HEAD の accept-ranges を見るだけでは足りない。Zenodo は HEAD で
    accept-ranges を返さないのに GET では 206 を返す。
    """
    try:
        with requests.get(url, headers={"Range": "bytes=0-0"},
                          stream=True, timeout=60) as r:
            return r.status_code == 206
    except requests.RequestException:
        return False


def _download_parallel(url: str, dest: Path, total: int, connections: int,
                       start_at: int = 0) -> None:
    """未取得の範囲を等分し、範囲リクエストで同時に取得する。

    先に総サイズ分の領域を確保してから、各担当が自分の範囲だけを書く。
    start_at を与えると、そこから先だけを取る（途中まで取れているファイルの続き）。
    既に取れている前半部分は truncate で保たれる。
    """
    # 並列取得中は総サイズ分の領域を確保するので、途中で強制終了されると
    # 「サイズは正しいが穴がある」ファイルが残る。目印を置いておき、
    # 次回起動時にどこまでが連続しているかを復元できるようにする。
    marker = dest.with_suffix(dest.suffix + ".partial")
    marker.write_text(str(start_at), encoding="ascii")

    mode = "r+b" if dest.exists() else "wb"
    with dest.open(mode) as fh:
        fh.truncate(total)

    remaining = total - start_at
    span = remaining // connections
    ranges = [
        (start_at + i * span,
         (total - 1) if i == connections - 1 else start_at + (i + 1) * span - 1)
        for i in range(connections)
    ]

    done = start_at
    lock = threading.Lock()
    stop = threading.Event()

    def worker(start: int, end: int) -> None:
        nonlocal done
        headers = {"Range": f"bytes={start}-{end}"}
        with requests.get(url, headers=headers, stream=True, timeout=180) as r:
            r.raise_for_status()
            with dest.open("r+b") as fh:
                fh.seek(start)
                for block in r.iter_content(chunk_size=1 << 20):
                    if stop.is_set():
                        return
                    if not block:
                        continue
                    fh.write(block)
                    with lock:
                        done += len(block)

    def report() -> None:
        last = -1
        while not stop.wait(2.0):
            with lock:
                cur = done
            if cur != last:
                print(f"\r       {human(cur)} / {human(total)}  "
                      f"{100 * cur / total:5.1f}%  ({connections} 並列)",
                      end="", flush=True)
                last = cur

    reporter = threading.Thread(target=report, daemon=True)
    reporter.start()
    try:
        with ThreadPoolExecutor(max_workers=connections) as pool:
            futures = [pool.submit(worker, s, e) for s, e in ranges]
            for f in futures:
                f.result()
    finally:
        stop.set()
        reporter.join(timeout=3)
    marker.unlink(missing_ok=True)
    print(f"\r       {human(total)} / {human(total)}  完了            ")


def download(src: Source, dest_dir: Path, chunk: int = 1 << 20) -> Path:
    """1 ファイルを取得する。既に完全なら何もしない。途中まであれば続きから。"""
    dest = dest_dir / src.filename
    dest_dir.mkdir(parents=True, exist_ok=True)

    have = dest.stat().st_size if dest.exists() else 0

    # 前回の並列取得が中断されていたら、連続していると分かっている位置まで戻す。
    marker = dest.with_suffix(dest.suffix + ".partial")
    if marker.exists() and dest.exists():
        try:
            safe = int(marker.read_text(encoding="ascii").strip())
        except ValueError:
            safe = 0
        print(f"  前回の取得が中断されています。{src.filename} を "
              f"{human(safe)} まで戻します。")
        with dest.open("r+b") as fh:
            fh.truncate(safe)
        marker.unlink(missing_ok=True)
        have = safe

    with requests.head(src.url, allow_redirects=True, timeout=60) as h:
        declared = int(h.headers.get("content-length", 0))
        # 転送時に圧縮するサーバー（GitHub raw など）では content-length が
        # 圧縮後の長さで、保存されるのは展開後なので必ず大きくなる。
        recompressed = bool(h.headers.get("content-encoding"))

    total = declared or src.approx_bytes

    # 完了の判定。照合できないことを「完了」と読み替えてはならない。
    # 途中で切れたファイルをそのまま使うと、索引が静かに欠けたものになる。
    if have:
        if declared and not recompressed:
            complete = have == declared
        elif declared and recompressed:
            complete = have >= declared        # 展開後は必ず圧縮後以上になる
        else:
            complete = have >= src.approx_bytes * 0.98
        if complete:
            print(f"  済  {src.filename} ({human(have)})")
            return dest
        print(f"  未完 {src.filename} — {human(have)} / {human(total)}")

    # 範囲リクエストが使えるかは HEAD の accept-ranges では当てにならない
    # （Zenodo は HEAD で返さないが GET では 206 を返す）。実際に試して確かめる。
    resumable = _supports_range(src.url)

    # 残りが大きければ分割して同時に取る。途中まで取れている場合も、
    # 未取得の範囲だけを並列で埋めるので取り直しにはならない。
    if (resumable and (total - have) >= PARALLEL_MIN_BYTES
            and PARALLEL_CONNECTIONS > 1):
        label = "取得" if not have else f"再開（{human(have)} 済）"
        print(f"  {label} {src.filename} ({human(total)}) "
              f"— {PARALLEL_CONNECTIONS} 並列")
        try:
            _download_parallel(src.url, dest, total, PARALLEL_CONNECTIONS,
                               start_at=have)
            return dest
        except Exception as exc:  # noqa: BLE001
            # 並列取得は総サイズ分の領域を先に確保するため、失敗すると
            # 「サイズは正しいが中身に穴がある」状態になる。それを完了と
            # 誤認しないよう、確実に連続している位置まで切り詰めて戻す。
            with dest.open("r+b") as fh:
                fh.truncate(have)
            print(f"\n       並列取得に失敗しました: {exc}")
            print(f"       {human(have)} まで切り詰めて 1 本で取り直します。")

    headers = {}
    mode = "wb"
    if have and resumable and have < total:
        headers["Range"] = f"bytes={have}-"
        mode = "ab"
        print(f"  再開 {src.filename} ({human(have)} / {human(total)})")
    else:
        have = 0
        print(f"  取得 {src.filename} ({human(total)})")

    done = have
    next_report = 0
    with requests.get(src.url, headers=headers, stream=True, timeout=120) as r:
        r.raise_for_status()
        with dest.open(mode) as fh:
            for block in r.iter_content(chunk_size=chunk):
                if not block:
                    continue
                fh.write(block)
                done += len(block)
                if done >= next_report:
                    pct = 100 * done / total if total else 0
                    print(f"\r       {human(done)} / {human(total)}  {pct:5.1f}%",
                          end="", flush=True)
                    next_report = done + (16 << 20)   # 16 MB ごと
    print(f"\r       {human(done)} / {human(total)}  完了            ")

    size = dest.stat().st_size
    if declared and not recompressed and size != declared:
        print(f"       注意: 期待 {human(declared)} に対し {human(size)} で"
              "終了しました。再実行すると続きから取得します。")
    return dest


def main(argv: list[str]) -> int:
    cfg = load_config()
    raw_dir = cfg.paths.raw

    if "--list" in argv:
        print(f"保存先: {raw_dir}\n")
        total = 0
        for s in SOURCES:
            total += s.approx_bytes
            print(f"  [{s.key:14s}] {s.filename:36s} {human(s.approx_bytes):>10s}"
                  f"  {s.license}")
            print(f"  {'':16s} {s.note}")
        print(f"\n  合計 約 {human(total)}")
        return 0

    keys = [a for a in argv if not a.startswith("-")]
    targets = [s for s in SOURCES if not keys or s.key in keys]
    if not targets:
        print(f"該当なし。指定できるのは: {sorted({s.key for s in SOURCES})}")
        return 1

    print(f"保存先: {raw_dir}")
    failed = []
    for s in targets:
        try:
            download(s, raw_dir)
        except Exception as exc:  # noqa: BLE001
            print(f"  失敗 {s.filename}: {exc}")
            failed.append(s.filename)

    if failed:
        print(f"\n{len(failed)} 件が未完了です: {', '.join(failed)}")
        print("同じコマンドを再実行すると続きから取得します。")
        return 1
    print("\nすべて取得しました。次は scripts/02_build_index.py を実行してください。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
