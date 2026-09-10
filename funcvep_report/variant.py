"""入力文字列の解析とアミノ酸表記の正規化。

検査会社の報告書の書き方は幅があるので、決まった形式に当てはめるのではなく、
入力の中から「遺伝子記号」「転写産物番号」「c. 表記」「p. 表記」の部品を拾い、
あるものを組み合わせて解釈する。

  BRCA1 p.Arg1699Trp / BRCA1 R1699W / BRCA1:p.R1699W / BRCA1 Arg1699Trp
  NM_007294.4:c.5095C>T / NM_007294.4(BRCA1):c.5095C>T / BRCA1(NM_007294.4):c.5095C>T
  SDHB c.574T>C / SDHB c.574T>C (p.Cys192Arg) / SDHB p.Cys192Arg (c.574T>C)
  全角文字、余分な空白、区切り記号の違い（: や 空白）、小文字も吸収する。

c. 表記があればそれを優先し（塩基まで決まるので正確）、p. 表記は照合に使う。
c. 表記だけで転写産物番号が無いときは、遺伝子の MANE Select に当てはめる。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .i18n import t

AA3_TO_1 = {
    "Ala": "A", "Arg": "R", "Asn": "N", "Asp": "D", "Cys": "C",
    "Gln": "Q", "Glu": "E", "Gly": "G", "His": "H", "Ile": "I",
    "Leu": "L", "Lys": "K", "Met": "M", "Phe": "F", "Pro": "P",
    "Ser": "S", "Thr": "T", "Trp": "W", "Tyr": "Y", "Val": "V",
    "Ter": "*", "Sec": "U", "Xaa": "X",
}
AA1 = set(AA3_TO_1.values())
AA1_TO_3 = {v: k for k, v in AA3_TO_1.items()}

CODON_TABLE = {
    "TTT": "F", "TTC": "F", "TTA": "L", "TTG": "L",
    "CTT": "L", "CTC": "L", "CTA": "L", "CTG": "L",
    "ATT": "I", "ATC": "I", "ATA": "I", "ATG": "M",
    "GTT": "V", "GTC": "V", "GTA": "V", "GTG": "V",
    "TCT": "S", "TCC": "S", "TCA": "S", "TCG": "S",
    "CCT": "P", "CCC": "P", "CCA": "P", "CCG": "P",
    "ACT": "T", "ACC": "T", "ACA": "T", "ACG": "T",
    "GCT": "A", "GCC": "A", "GCA": "A", "GCG": "A",
    "TAT": "Y", "TAC": "Y", "TAA": "*", "TAG": "*",
    "CAT": "H", "CAC": "H", "CAA": "Q", "CAG": "Q",
    "AAT": "N", "AAC": "N", "AAA": "K", "AAG": "K",
    "GAT": "D", "GAC": "D", "GAA": "E", "GAG": "E",
    "TGT": "C", "TGC": "C", "TGA": "*", "TGG": "W",
    "CGT": "R", "CGC": "R", "CGA": "R", "CGG": "R",
    "AGT": "S", "AGC": "S", "AGA": "R", "AGG": "R",
    "GGT": "G", "GGC": "G", "GGA": "G", "GGG": "G",
}


class ParseError(ValueError):
    """入力を解釈できなかった。利用者にそのまま見せる日本語メッセージを持つ。"""


def _aa_to_one(token: str) -> str:
    """Arg / R / ARG のいずれでも 1 文字表記に正規化する。"""
    t = token.strip()
    if len(t) == 1 and t.upper() in AA1:
        return t.upper()
    key = t.capitalize()
    if key in AA3_TO_1:
        return AA3_TO_1[key]
    raise ParseError(t("vp.bad_aa", token=token))


@dataclass(frozen=True)
class ProteinInput:
    """遺伝子記号 + アミノ酸置換。"""

    gene: str
    aa_ref: str      # 1 文字
    position: int    # 1 始まり
    aa_alt: str      # 1 文字
    transcript: str | None = None   # 併記されていれば（照合用）

    @property
    def protein_variant(self) -> str:
        """AlphaMissense の protein_variant 列と同じ書式（例 R1699W）。"""
        return f"{self.aa_ref}{self.position}{self.aa_alt}"

    def __str__(self) -> str:
        return f"{self.gene} p.{self.aa_ref}{self.position}{self.aa_alt}"


@dataclass(frozen=True)
class CodingInput:
    """HGVS 転写産物表記。"""

    transcript: str | None  # バージョン付き（例 NM_007294.4）。遺伝子だけの入力では None
    gene: str | None
    cds_position: int      # c. の座標（コード領域内、1 始まり）
    ref_base: str
    alt_base: str
    # 併記された p. 表記（1 文字の参照 aa, 残基番号, 1 文字の変異 aa）。照合に使う
    protein: tuple[str, int, str] | None = None

    @property
    def transcript_base(self) -> str | None:
        return self.transcript.split(".")[0] if self.transcript else None

    def __str__(self) -> str:
        head = self.transcript or self.gene or "?"
        return f"{head}:c.{self.cds_position}{self.ref_base}>{self.alt_base}"


_TX_RE = re.compile(r"^(?:NM_|XM_|NR_|ENST)\d+(?:\.\d+)?$", re.I)
_CDS_RE = re.compile(r"^c\.(\d+)([ACGT])>([ACGT])$", re.I)
# p. 表記。p. は省略可。Arg1699Trp / R1699W / Arg1699* / Arg1699=
_PROT_RE = re.compile(r"^(?:p\.)?([A-Za-z]{1,3})(\d+)([A-Za-z]{1,3}|\*|=)$")
_GENE_RE = re.compile(r"^[A-Za-z][A-Za-z0-9._\-]*$")


def _normalize(text: str) -> str:
    """全角を半角に、区切りを空白に揃え、c. / p. の内側の空白を詰める。"""
    import unicodedata

    s = unicodedata.normalize("NFKC", text).strip()
    s = s.replace("＞", ">").replace("→", ">")
    # c.574 T>C / c. 574T > C のような空白を詰める
    s = re.sub(r"([cp])\.\s+", r"\1.", s, flags=re.I)
    s = re.sub(r"(\d)\s*([ACGTacgt])\s*>\s*([ACGTacgt])", r"\1\2>\3", s)
    # 括弧・コロン・カンマ・セミコロンは区切りとして扱う
    s = re.sub(r"[()\[\]{}:;,、（）／/]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _is_protein_token(tok: str) -> tuple[str, int, str] | None:
    """アミノ酸置換に見えるか。見えれば (参照 aa, 残基番号, 変異 aa) を返す。"""
    m = _PROT_RE.match(tok)
    if not m:
        return None
    ref, pos, alt = m.group(1), int(m.group(2)), m.group(3)
    try:
        aa_ref = _aa_to_one(ref)
        aa_alt = alt if alt in ("*", "=") else _aa_to_one(alt)
    except ParseError:
        return None
    return aa_ref, pos, aa_alt


def _check_protein(aa_ref: str, aa_alt: str) -> None:
    if aa_alt == "=":
        raise ParseError(t("vp.synonymous"))
    if aa_alt == "*":
        raise ParseError(t("vp.nonsense"))
    if aa_ref == aa_alt:
        raise ParseError(t("vp.same_aa"))


def parse(text: str) -> ProteinInput | CodingInput:
    """1 行の入力を解析する。

    入力を部品（転写産物番号、c. 表記、p. 表記、遺伝子記号）に分けて拾い、
    c. 表記があれば CodingInput、無ければ ProteinInput を返す。
    どちらにもならなければ、どこまで読めたかを添えて ParseError。
    """
    if not text or not text.strip():
        raise ParseError(t("vp.empty"))
    tokens = _normalize(text).split(" ")

    transcript: str | None = None
    cds: tuple[int, str, str] | None = None
    prot: tuple[str, int, str] | None = None
    gene: str | None = None
    protein_like: list[tuple[str, tuple[str, int, str]]] = []
    others: list[str] = []

    for tok in tokens:
        if not tok:
            continue
        if transcript is None and _TX_RE.match(tok):
            transcript = tok
            continue
        m = _CDS_RE.match(tok)
        if m and cds is None:
            cds = (int(m.group(1)), m.group(2).upper(), m.group(3).upper())
            continue
        if tok.lower().startswith("p."):
            pt = _is_protein_token(tok)
            if pt:
                prot = pt
                continue
        pt = _is_protein_token(tok)
        if pt:
            protein_like.append((tok, pt))
            continue
        if re.match(r"^[cpgnr]\.", tok, re.I) or ">" in tok:
            # c. / p. で始まるのに読めない: 欠失・挿入・重複など対象外の表記
            raise ParseError(t("vp.unsupported_change", token=tok))
        others.append(tok)

    # 遺伝子記号: 明らかな部品以外の最初の語。無ければ、アミノ酸置換に見える語が
    # 2 つ以上あるときの最初の語（C1R のような遺伝子名は置換にも見えるため）
    gene_candidates = [o for o in others if _GENE_RE.match(o)]
    if gene_candidates:
        gene = gene_candidates[0]
    if prot is None and protein_like:
        if gene is None and len(protein_like) >= 2:
            gene = protein_like[0][0]
            prot = protein_like[1][1]
        else:
            prot = protein_like[0][1]
    elif prot is not None and gene is None and protein_like:
        gene = protein_like[0][0]

    if cds is not None:
        if transcript is None and gene is None:
            raise ParseError(t("vp.no_gene_for_cds", cds=f"c.{cds[0]}{cds[1]}>{cds[2]}"))
        if prot is not None:
            _check_protein(prot[0], prot[2])
        return CodingInput(
            transcript=transcript, gene=gene.upper() if gene else None,
            cds_position=cds[0], ref_base=cds[1], alt_base=cds[2], protein=prot,
        )

    if prot is not None:
        _check_protein(prot[0], prot[2])
        if gene is None:
            raise ParseError(t("vp.no_gene_for_protein",
                               prot=f"p.{AA1_TO_3.get(prot[0], prot[0])}{prot[1]}{AA1_TO_3.get(prot[2], prot[2])}"))
        return ProteinInput(gene=gene.upper(), aa_ref=prot[0], position=prot[1], aa_alt=prot[2],
                            transcript=transcript)

    recognized = []
    if gene:
        recognized.append(t("vp.recognized_gene", gene=gene))
    if transcript:
        recognized.append(t("vp.recognized_tx", tx=transcript))
    if recognized:
        raise ParseError(t("vp.no_change", recognized="、".join(recognized)))
    raise ParseError(t("vp.unrecognized"))


def translate_codon(codon: str) -> str:
    return CODON_TABLE.get(codon.upper(), "X")


def apply_cds_substitution(cds: str, cds_pos: int, ref: str, alt: str) -> tuple[str, int, str]:
    """CDS 配列に c. 置換を当て、(参照 aa, コドン番号, 変異 aa) を返す。

    cds は開始コドンから終止コドンまでの塩基配列（1 始まりで cds_pos が対応する）。
    参照塩基が一致しない場合は ParseError。
    """
    if cds_pos < 1 or cds_pos > len(cds):
        raise ParseError(t("vp.out_of_range", pos=cds_pos, length=len(cds)))
    observed = cds[cds_pos - 1].upper()
    if observed != ref.upper():
        raise ParseError(t("vp.ref_mismatch", pos=cds_pos, observed=observed, ref=ref))

    codon_index = (cds_pos - 1) // 3          # 0 始まり
    offset = (cds_pos - 1) % 3
    start = codon_index * 3
    ref_codon = cds[start:start + 3].upper()
    if len(ref_codon) < 3:
        raise ParseError(t("vp.codon_truncated"))
    alt_codon = ref_codon[:offset] + alt.upper() + ref_codon[offset + 1:]

    aa_ref = translate_codon(ref_codon)
    aa_alt = translate_codon(alt_codon)
    return aa_ref, codon_index + 1, aa_alt
