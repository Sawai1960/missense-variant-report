"""入力文字列の解析とアミノ酸表記の正規化。

対応する入力は 2 形式:
  1. 遺伝子記号 + アミノ酸置換   例) BRCA1 p.Arg1699Trp / BRCA1 R1699W / BRCA1:p.R1699W
  2. HGVS 転写産物表記           例) NM_007294.4:c.5095C>T / NM_007294.4(BRCA1):c.5095C>T
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

    @property
    def protein_variant(self) -> str:
        """AlphaMissense の protein_variant 列と同じ書式（例 R1699W）。"""
        return f"{self.aa_ref}{self.position}{self.aa_alt}"

    def __str__(self) -> str:
        return f"{self.gene} p.{self.aa_ref}{self.position}{self.aa_alt}"


@dataclass(frozen=True)
class CodingInput:
    """HGVS 転写産物表記。"""

    transcript: str        # バージョン付き（例 NM_007294.4）。無い場合もある
    gene: str | None
    cds_position: int      # c. の座標（コード領域内、1 始まり）
    ref_base: str
    alt_base: str

    @property
    def transcript_base(self) -> str:
        return self.transcript.split(".")[0]

    def __str__(self) -> str:
        return f"{self.transcript}:c.{self.cds_position}{self.ref_base}>{self.alt_base}"


# 例) BRCA1 p.Arg1699Trp / BRCA1 R1699W / BRCA1:p.R1699W / BRCA1 Arg1699Trp
_PROTEIN_RE = re.compile(
    r"""^\s*
    (?P<gene>[A-Za-z0-9][A-Za-z0-9._\-]*?)      # 遺伝子記号
    \s*[:\s]\s*
    (?:p\.)?
    (?P<ref>[A-Za-z]{1,3})
    (?P<pos>\d+)
    (?P<alt>[A-Za-z]{1,3}|\*|=)
    \s*$""",
    re.VERBOSE,
)

# 例) NM_007294.4:c.5095C>T / NM_007294.4(BRCA1):c.5095C>T / ENST00000357654:c.5095C>T
_CODING_RE = re.compile(
    r"""^\s*
    (?P<tx>(?:NM_|XM_|ENST)[0-9]+(?:\.\d+)?)
    (?:\s*\(\s*(?P<gene>[A-Za-z0-9._\-]+)\s*\))?
    \s*:\s*c\.
    (?P<pos>\d+)
    (?P<ref>[ACGTacgt])
    \s*>\s*
    (?P<alt>[ACGTacgt])
    \s*$""",
    re.VERBOSE,
)


def parse(text: str) -> ProteinInput | CodingInput:
    """1 行の入力を解析する。どちらの形式にも当てはまらなければ ParseError。"""
    if not text or not text.strip():
        raise ParseError(t("vp.empty"))
    s = text.strip()

    m = _CODING_RE.match(s)
    if m:
        return CodingInput(
            transcript=m.group("tx"),
            gene=m.group("gene"),
            cds_position=int(m.group("pos")),
            ref_base=m.group("ref").upper(),
            alt_base=m.group("alt").upper(),
        )

    m = _PROTEIN_RE.match(s)
    if m:
        alt_tok = m.group("alt")
        if alt_tok == "=":
            raise ParseError(t("vp.synonymous"))
        aa_ref = _aa_to_one(m.group("ref"))
        aa_alt = "*" if alt_tok == "*" else _aa_to_one(alt_tok)
        if aa_alt == "*":
            raise ParseError(t("vp.nonsense"))
        if aa_ref == aa_alt:
            raise ParseError(t("vp.same_aa"))
        return ProteinInput(
            gene=m.group("gene").upper(),
            aa_ref=aa_ref,
            position=int(m.group("pos")),
            aa_alt=aa_alt,
        )

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
