// 要件定義・設計概要（日英）を Word で作る
const fs = require("fs");
const path = require("path");
const {
  Document, Packer, Paragraph, TextRun, HeadingLevel, Table, TableRow, TableCell,
  WidthType, ShadingType, AlignmentType, BorderStyle, LevelFormat, PageBreak,
  Header, Footer, PageNumber, TableOfContents,
} = require("docx");

const OUT_DIR = process.argv[2] || ".";
const DATE = "2026-09-10";

// ---------------------------------------------------------------- helpers
const W = 9026; // A4 本文幅 (DXA)
function h1(t) { return new Paragraph({ text: t, heading: HeadingLevel.HEADING_1, spacing: { before: 360, after: 160 } }); }
function h2(t) { return new Paragraph({ text: t, heading: HeadingLevel.HEADING_2, spacing: { before: 240, after: 120 } }); }
function p(t, opts = {}) {
  const runs = Array.isArray(t) ? t : [t];
  return new Paragraph({
    spacing: { after: 120, line: 300 },
    children: runs.map(r => typeof r === "string" ? new TextRun({ text: r }) : new TextRun(r)),
    ...opts,
  });
}
function small(t) { return new Paragraph({ spacing: { after: 100 }, children: [new TextRun({ text: t, size: 18, color: "555555" })] }); }
function bullets(items) {
  return items.map(t => new Paragraph({
    numbering: { reference: "bul", level: 0 }, spacing: { after: 80, line: 280 },
    children: (Array.isArray(t) ? t : [t]).map(r => typeof r === "string" ? new TextRun({ text: r }) : new TextRun(r)),
  }));
}
function numbered(items) {
  return items.map(t => new Paragraph({
    numbering: { reference: "num", level: 0 }, spacing: { after: 80, line: 280 },
    children: [new TextRun({ text: t })],
  }));
}
function cell(text, width, opts = {}) {
  const runs = (Array.isArray(text) ? text : [text]).map(r => typeof r === "string" ? new TextRun({ text: r, size: 18, bold: opts.bold }) : new TextRun({ size: 18, ...r }));
  return new TableCell({
    width: { size: width, type: WidthType.DXA },
    shading: opts.head ? { type: ShadingType.CLEAR, fill: "E8EEF5", color: "auto" } : undefined,
    margins: { top: 60, bottom: 60, left: 90, right: 90 },
    children: [new Paragraph({ spacing: { after: 0, line: 260 }, children: runs })],
  });
}
function table(headers, rows, widths) {
  const sum = widths.reduce((a, b) => a + b, 0);
  const scale = W / sum;
  const ws = widths.map(w => Math.round(w * scale));
  const border = { style: BorderStyle.SINGLE, size: 4, color: "BBBBBB" };
  return new Table({
    width: { size: W, type: WidthType.DXA },
    columnWidths: ws,
    borders: { top: border, bottom: border, left: border, right: border, insideHorizontal: border, insideVertical: border },
    rows: [
      new TableRow({ tableHeader: true, children: headers.map((h, i) => cell(h, ws[i], { head: true, bold: true })) }),
      ...rows.map(r => new TableRow({ children: r.map((c, i) => cell(c, ws[i])) })),
    ],
  });
}
function spacer() { return new Paragraph({ spacing: { after: 120 }, children: [] }); }

// ---------------------------------------------------------------- content (JA)
function contentJA() {
  const B = [];
  B.push(new Paragraph({ spacing: { after: 60 }, children: [new TextRun({ text: "兵庫医科大学病院 遺伝子医療部", size: 20, color: "555555" })] }));
  B.push(new Paragraph({ spacing: { after: 120 }, children: [new TextRun({ text: "遺伝子ミスセンス変異 統合評価レポート", bold: true, size: 40 })] }));
  B.push(new Paragraph({ spacing: { after: 240 }, children: [new TextRun({ text: "要件定義と設計概要", bold: true, size: 30 })] }));
  B.push(small(`版 1.0　${DATE}　作成: 兵庫医科大学病院 遺伝子医療部　宛先: FuncVEP の著者（Kerem Çil、Barış Kayaalp、Tayfun Özçelik の各氏、Bilkent 大学）`));
  B.push(spacer());
  B.push(new TableOfContents("目次", { hyperlink: true, headingStyleRange: "1-2" }));
  B.push(new Paragraph({ children: [new PageBreak()] }));

  B.push(h1("1. 目的"));
  B.push(p("検査会社の報告書に記載されたミスセンス変異について、それが病的か良性かを判断する手がかりとなる情報を 1 枚の報告書に集めることが、このツールの目的です。判断そのものは行いません。ACMG/AMP の変異解釈基準に沿って証拠を整理し、臨床遺伝の専門家が解釈するための補助資料を作ります。"));
  B.push(p("中心に置く証拠は FuncVEP（Kayaalp ら, Nature Genetics 2026）の予測です。FuncVEP は機能実験の証拠で学習した予測ツールで、タンパク質の働きへの影響（damaging / neutral）を予測します。ツールはこの予測を、集団頻度、既知の臨床判定、機能実験の実測値、スプライシングへの影響、遺伝子と疾患の関係といった他の証拠と並べて示します。"));

  B.push(h1("2. 範囲と、しないこと"));
  B.push(...bullets([
    "対象は 1 塩基置換によるミスセンス変異（アミノ酸置換）のみです。フレームシフト、ナンセンス、欠失・挿入、スプライス部位の変異は扱いません。",
    "座標系は GRCh38、転写産物は MANE Select を基準にします。",
    "FuncVEP を再計算しません。著者らが公開した予測済みスコアの表（約 7,300 万変異）から該当する値を取り出すだけです。",
    "病的・良性の最終判定は行いません。報告書は補助資料であり、単独では臨床判断の根拠として使用できません。",
    "院内（兵庫医科大学病院 遺伝子医療部）での非商用利用に限ります。ツールと索引データは外部に配布しません（FuncVEP の PolyForm Strict 1.0.0 ライセンスに従います）。",
  ]));

  B.push(h1("3. 利用者と動作環境"));
  B.push(...bullets([
    "利用者: 遺伝子医療部の医師・遺伝カウンセラー。変異の表記を報告書から転記できることを前提とします。",
    "動作環境: 院内の Windows PC 1 台。Python と Streamlit によるローカルの Web アプリで、ブラウザから操作します。参照データの索引は D: ドライブに置きます。",
    "通信: 索引の照会はオフラインで完結します。集団頻度など一部の情報は公開データベースの API に問い合わせます（5 節）。送るのは変異の座標などに限られ、患者情報は送りません。切り替えでオフライン運用もできます。",
    "言語: 画面と PDF は日本語・英語を切り替えられます。",
  ]));

  B.push(h1("4. 入力"));
  B.push(p("検査会社の報告書の書き方には幅があるため、決まった形式に当てはめるのではなく、入力から「遺伝子記号」「転写産物番号」「c. 表記」「p. 表記」の部品を拾い、あるものを組み合わせて解釈します。括弧・コロン・空白・全角文字の違いは吸収します。"));
  B.push(table(["入力の例", "解釈"], [
    ["BRCA1 p.Arg1699Trp / BRCA1 R1699W / BRCA1:p.R1699W", "遺伝子記号とアミノ酸置換。MANE 転写産物上の残基番号として解決"],
    ["NM_007294.4:c.5095C>T / NM_007294.4(BRCA1):c.5095C>T", "転写産物番号と c. 表記。CDS 配列に当てて翻訳し、アミノ酸置換を求める"],
    ["SDHB c.574T>C (p.Cys192Arg) / SDHB p.Cys192Arg (c.574T>C)", "c. と p. の併記。c. を使い、翻訳結果が p. と一致するかを照合する"],
    ["SDHB c.574T>C", "転写産物番号の無い c. 表記。遺伝子の MANE Select に当てはめ、その旨を注意欄に出す"],
    ["SDHB(NM_003000.3):c.574T>C / ＳＤＨＢ　ｃ．５７４Ｔ＞Ｃ", "遺伝子と転写産物の併記、全角文字なども同様に解釈"],
  ], [40, 60]));
  B.push(spacer());
  B.push(p("解決の規則: c. 表記があればそれを優先します（塩基まで決まるため）。c. から求めたアミノ酸置換が併記の p. と食い違えば警告します。転写産物番号が無く p. の併記も無いときは、標準転写産物に当てはめた旨を注意欄に出します。読めない入力には、どこまで読めたかを添えたエラーを返します。"));

  B.push(h1("5. データ源"));
  B.push(h2("5.1 手元に置く索引（オフライン）"));
  B.push(table(["データ", "使う内容", "役割"], [
    ["FuncVEP / ClinVEP 予測表（Zenodo、73,092,279 行）", "FuncVEP-CTI / CTE / SP と ClinVEP-CTI / CTE / SP のスコア", "主たる証拠。ゲノム座標（chr-pos-ref-alt）で引く"],
    ["AlphaMissense（Cheng ら 2023）", "スコアと区分、転写産物ごとの残基番号と座標", "アミノ酸置換からゲノム座標への橋渡し、および比較用の予測"],
    ["REVEL（Ioannidis ら 2016）", "スコア", "従来型の統合予測との比較"],
    ["ClinVar variant_summary", "臨床的意義、レビュー段階、提出者数、疾患名、VariationID", "既知の臨床判定。同じアミノ酸位置の他の変異の判定にも使う"],
    ["gnomAD 遺伝子制約", "pLI、missense z、LoF z", "遺伝子が変異に耐えられるかの背景"],
    ["MANE（要約と CDS 配列）", "遺伝子と転写産物の対応、CDS 配列", "転写産物の解決、c. 表記の翻訳、参照アミノ酸の確認"],
  ], [34, 33, 33]));
  B.push(spacer());
  B.push(p("索引は Parquet 形式で 6〜8 GB、DuckDB で照会します。1 変異あたりの照会は 0.3 秒程度です。"));
  B.push(h2("5.2 公開 API への照会（オンライン、切り替え可）"));
  B.push(table(["データ源", "取得する内容", "送る情報", "キャッシュ"], [
    ["gnomAD v4（GraphQL API）", "アレル頻度、ホモ接合体数、東アジア集団の頻度、その位置の読み取り深度、rsID", "染色体・位置・塩基", "24 時間"],
    ["TogoVar（NBDC/DBCLS、REST API）", "日本人集団の頻度。ToMMo 54KJPN（健常者中心、約 54,000 人）を参照とし、NCBN・GEM-J WGA・JGA は参考", "染色体・位置", "24 時間"],
    ["Ensembl VEP（REST、SpliceAI プラグイン）", "SpliceAI の Δ スコア 4 種と位置", "染色体・位置・塩基", "24 時間"],
    ["ClinGen Gene-Disease Validity", "遺伝子と疾患の関係の確立度、遺伝形式", "なし（一覧 CSV を丸ごと取得）", "30 日"],
    ["MaveDB（API）", "大規模機能実験の実測スコアと、研究者が定めた正常／異常の区分", "遺伝子記号（検索）", "検索 30 日、データは永続"],
    ["ClinVar（NCBI E-utilities）", "疾患名ごとの判定・提出件数・レビュー段階", "VariationID", "24 時間"],
    ["LitVar2（NCBI）+ PubMed", "変異に言及した論文（画面のみ、PDF には載せない）", "遺伝子記号と置換、rsID", "24 時間"],
  ], [26, 38, 20, 16]));
  B.push(spacer());
  B.push(p("いずれも患者情報は送りません。通信できない場合は「取得できなかった」と表示し、検査報告書の値を手入力できる欄を案内します。"));

  B.push(h1("6. 処理の流れ"));
  B.push(...numbered([
    "入力の解析: 部品を拾って、遺伝子・転写産物・c. 表記・p. 表記を決める（4 節）。",
    "転写産物とアミノ酸置換の確定: MANE の転写産物を選び、c. 表記は CDS 配列で翻訳する。p. 表記は参照アミノ酸が CDS と一致するかを確認する（MANE Select と Plus Clinical で番号が違う遺伝子に対応）。",
    "ゲノム座標の確定: AlphaMissense の索引で、その転写産物・残基番号・置換に対応する chr-pos-ref-alt を求める。同じアミノ酸置換を生じる塩基置換が複数あれば全部を候補にする。転写産物 ID の世代差やアイソフォームのずれは対応表と予備経路で吸収する。",
    "証拠の収集: 座標で FuncVEP・REVEL・ClinVar を引き、遺伝子で制約指標と MANE の情報を引く。同じアミノ酸位置の他の ClinVar 変異も集める。",
    "オンライン照会: gnomAD、TogoVar、SpliceAI、ClinGen、MaveDB、ClinVar 疾患別件数を取得する（オフラインなら省く）。",
    "証拠の整理: ACMG の基準に対応づける（7 節）。予測ツールの判定をまとめる。",
    "報告書の組み立てと出力: 日本語または英語の文言で節を組み立て、画面に表示し、PDF（A4、発行元とページ番号入り）を生成する。",
  ]));

  B.push(h1("7. 証拠と ACMG 基準の対応"));
  B.push(table(["証拠", "出典", "対応する基準", "報告書での示し方"], [
    ["FuncVEP-CTI / CTE / SP のスコア", "FuncVEP 予測表", "PP3 / BP4（コンピュータ予測）", "スコア、damaging / neutral の判定、証拠の段階（Supporting / Moderate / Intermediate / Strong）。閾値は著者提供の Supplementary Table 13（付録 A）"],
    ["AlphaMissense、REVEL、ClinVEP", "各索引", "参考", "スコアと区分。予測ツールの判定のまとめで、damaging 側・neutral 側に分けて要約"],
    ["同じアミノ酸置換を起こす別の塩基変異", "ClinVar 索引", "PS1 の候補", "病的判定があれば PS1 の候補と明記。スプライシングの違いに注意を添える"],
    ["同じ位置で別のアミノ酸への置換", "ClinVar 索引", "PM5 の候補", "病的判定の件数と、良性判定があればその旨"],
    ["アレル頻度、ホモ接合体数", "gnomAD、TogoVar", "BA1（0.05 超）、BS1、BS2", "頻度とアレル数。0.05 超は BA1 該当と明記"],
    ["集団データベースに無いこと", "gnomAD", "PM2_supporting の候補", "その位置の読み取り深度が十分なときだけ根拠とする"],
    ["機能実験の実測値", "MaveDB", "PS3 / BS3 の材料", "実測スコアと、研究者が定めた正常／異常の区分"],
    ["スプライシングへの影響", "SpliceAI", "ミスセンスとしての評価の前提", "Δ 0.2 以上で注意、0.5 以上はスプライシング異常として再評価を促す"],
    ["遺伝子と疾患の関係、遺伝形式", "ClinGen", "pLI・BS2・PM2 の読み方の前提", "遺伝子単位の関連疾患を一覧し、この変異の ClinVar 主疾患と一致するものに印"],
    ["この変異の臨床判定", "ClinVar", "既知の判定", "臨床的意義、レビュー段階、疾患名を提出件数順に（疾患名は提出者の登録であり検証済みでない旨を注記）"],
  ], [24, 16, 20, 40]));
  B.push(spacer());
  B.push(p("報告書は基準の「候補」を示すにとどめ、適用の可否と強さの判断は解釈者に委ねます。"));

  B.push(h1("8. FuncVEP のスコアが無い変異の扱い"));
  B.push(p("公開された予測表では、学習に用いた変異のスコアが出ません。著者らとのやり取り（2026-09-05、09-07）で確認した内容に基づき、次のように書き分けます。"));
  B.push(...bullets([
    "表に行はあるがスコアが空欄: 一部のモデルの学習データに含まれていた変異。該当モデルのスコアは公開されない。",
    "表に行そのものが無い: 6 モデルすべての学習データに含まれていた変異。各モデルの推論から除外され、統合表に現れない。",
    "行が無く、公開されている学習データにも見当たらない: 予測表を作る工程の都合（注釈の違いによる除外、元データに無い、処理の抜け）で生じたもの。",
    "いずれの場合も「スコアが無いこと自体は病原性についても予測の確からしさについても情報を持たない」と明記し、AlphaMissense・REVEL・ClinVar で判断するよう案内する。どのモデルの学習に使われたかは、公開されている学習セットとの照合で表示する。",
  ]));
  B.push(p("手元の実測では、ClinVar で 2 星以上の病的ミスセンス変異 24,010 件のうち 11.3%（行なし 4.9%、空欄 6.7%）、良性 38,528 件のうち 7.0% でスコアが得られませんでした。行の無い 2,948 件のうち 83.3% は学習セットで説明でき、残る 487 件が上記 3 番目に当たります。"));

  B.push(h1("9. 報告書の構成"));
  B.push(...numbered([
    "表題、発行元、入力、作成日時",
    "評価対象の変異: アミノ酸置換、ゲノム座標（GRCh38）、転写産物。候補が複数なら全部",
    "注意: 入力の解釈に関わる事項（候補が複数、転写産物の当てはめ、p. の食い違い、SpliceAI の警告）。該当が無ければ出ない",
    "遺伝子: pLI、missense z、LoF z（値ごとの一言と解説）、ClinGen の評価（遺伝子単位の関連疾患）",
    "変異ごと（帯状の見出し。2 つ目以降は改ページ）: 集団頻度（gnomAD）、FuncVEP、他の予測ツール（ClinVEP、AlphaMissense、REVEL、SpliceAI）、機能実験の実測値（MaveDB、あれば）、予測ツールの判定のまとめ（色付きの箱）、ClinVar（この変異の登録）、ClinVar（同じアミノ酸位置に報告されている他の変異）",
    "PP3/BP4 の判定基準について、解釈上の注意（帯状の見出し）、謝辞、参考文献",
  ]));
  B.push(p("文章の方針: 日本語はすべてです・ます調で、専門用語は初出で意味を定義します。damaging / neutral などの英語の判定語には和訳を添えます。判定のまとめの箱の色（赤系・緑系・橙系）は予測ツールの判定が揃っているかを示すもので、病原性の判定ではないことを箱の中に明記します。"));

  B.push(h1("10. 検証"));
  B.push(...bullets([
    "単体テスト 62 件（入力解析、コドン翻訳、各 API の応答の読み取り、同じ位置の判定の振り分け）。",
    "セルフテスト: 既知の 25 変異（HGVS 表記との突き合わせ、拒否されるべき入力を含む）で OK 19 / 注意 6 / NG 0。注意 6 件は学習データによるスコア欠落で、いずれも説明が付く。",
    "座標系の確認: TP53 p.Arg175His が GRCh38 の chr17:7,675,088 に一致。転写産物 ID の世代差、アイソフォームのずれについて予備経路の安全性を実測で確認。",
    "公開予測表の網羅性の実測と、著者への照合（2026-09-06 に不一致表を共有）。",
  ]));
  B.push(table(["確認に用いた変異", "確認した点"], [
    ["BRCA1 p.Arg1699Trp", "FuncVEP 3 モデルとも PP3_Strong。ClinVar 専門家パネル 3 星。同じ位置の Arg1699Gln・Leu が病的（PM5 候補）"],
    ["BRCA1 p.Cys61Gly", "MaveDB の SGE（Findlay ら 2018）で「異常」。c. 表記しか持たない実験データを CDS で翻訳して照合"],
    ["HBB p.Glu7Val", "FuncVEP は neutral だが臨床的には病的（HbS の重合）。機能予測と病原性の乖離の例。日本人集団は ToMMo に無く NCBN のみ（参考扱い）"],
    ["FGFR3 p.Gly380Arg", "同じアミノ酸置換に塩基置換が 2 通り（G>A は 3 モデルの学習による空欄、G>C は 6 モデルによる欠落）。互いに PS1 候補。ClinVar の疾患名は件数順で achondroplasia が 38 件"],
    ["NEFL p.Pro8Leu", "予測表に行が無い例。gnomAD 収録なし（PM2_supporting 候補）。同じ位置の Pro8Arg・Gln が病的（PM5 候補）"],
    ["SDHB c.574T>C (p.Cys192Arg)", "報告書形式の入力。c. と p. の一致を確認し、注意を出さずに解決"],
  ], [30, 70]));

  B.push(h1("11. 解釈上の限界"));
  B.push(...bullets([
    "FuncVEP が予測するのはタンパク質の働きへの影響であり、臨床的病原性そのものではありません。機能獲得型・凝集型・浸透率が可変の変異では、機能予測が低くても病的でありえます。",
    "ACMG/AMP では PP3/BP4（コンピュータ予測）として扱い、PS3/BS3（機能実験）にはなりません。",
    "対象はミスセンス変異のみで、スプライシングへの影響は SpliceAI で別途示します。",
    "ClinVar の疾患名は提出者の登録であり、検証されたものではありません。ClinGen の評価は遺伝子単位です。",
    "本レポートは補助資料であり、単独では臨床判断の根拠として使用できません。",
  ]));

  B.push(h1("12. ライセンスとデータの管理"));
  B.push(...bullets([
    "FuncVEP: PolyForm Strict 1.0.0（非商用のみ、改変・再配布の禁止）。予測表と索引は院内に留め、配布しません。",
    "AlphaMissense: CC BY-NC-SA 4.0。REVEL: 非商用のみ。ClinVar・MANE: パブリックドメイン。gnomAD: CC0。",
    "コードと文書のみを、著者の閲覧用に非公開のリポジトリで共有しています。",
  ]));

  B.push(h1("13. 謝辞"));
  B.push(p("本ツールの FuncVEP に関する部分は、著者である Kerem Çil、Barış Kayaalp、Tayfun Özçelik の各氏（Bilkent 大学）から、PP3/BP4 の判定基準の公表値（Supplementary Table 13）の提供と、予測表に未収録の変異についての説明をいただいて完成しました。深く感謝申し上げます。"));

  B.push(new Paragraph({ children: [new PageBreak()] }));
  B.push(h1("付録 A. PP3/BP4 の閾値（Supplementary Table 13）"));
  B.push(p("PP3 はスコアが閾値以上、BP4 はスコアが閾値以下で該当します。段階は Supporting / Moderate / Intermediate / Strong（Bergquist ら 2025, Genet Med の体系）。damaging / neutral の境（binary）はモデルごとに異なり、0.5 ではありません。"));
  B.push(thresholdTable());
  B.push(spacer());
  B.push(h1("付録 B. 構成"));
  B.push(table(["ファイル", "役割"], moduleRows(), [35, 65]));
  return B;
}

// ---------------------------------------------------------------- content (EN)
function contentEN() {
  const B = [];
  B.push(new Paragraph({ spacing: { after: 60 }, children: [new TextRun({ text: "Department of Clinical Genetics, Hyogo Medical University Hospital", size: 20, color: "555555" })] }));
  B.push(new Paragraph({ spacing: { after: 120 }, children: [new TextRun({ text: "Missense Variant Evaluation Report", bold: true, size: 40 })] }));
  B.push(new Paragraph({ spacing: { after: 240 }, children: [new TextRun({ text: "Requirements and Design Overview", bold: true, size: 30 })] }));
  B.push(small(`Version 1.0, ${DATE}. Prepared by the Department of Clinical Genetics, Hyogo Medical University Hospital, for the FuncVEP authors (Kerem Çil, Barış Kayaalp and Tayfun Özçelik, Bilkent University).`));
  B.push(spacer());
  B.push(new TableOfContents("Contents", { hyperlink: true, headingStyleRange: "1-2" }));
  B.push(new Paragraph({ children: [new PageBreak()] }));

  B.push(h1("1. Purpose"));
  B.push(p("The tool takes a missense variant as written on a laboratory report and assembles, on a single report, the evidence that helps a clinician judge whether the variant is pathogenic or benign. It does not make that judgement. It organises evidence along the ACMG/AMP variant-interpretation framework so that clinical geneticists can interpret it."));
  B.push(p("The central evidence is the FuncVEP prediction (Kayaalp et al., Nature Genetics 2026), a predictor trained on functional-assay evidence that estimates the effect of the substitution on protein function (damaging / neutral). The tool places this prediction alongside other evidence: population frequency, existing clinical classifications, measured functional-assay results, splicing effects and the gene–disease relationship."));

  B.push(h1("2. Scope and non-goals"));
  B.push(...bullets([
    "Single-nucleotide missense variants only. Frameshift, nonsense, indel and splice-site variants are out of scope.",
    "GRCh38 coordinates; MANE Select transcripts as the reference.",
    "FuncVEP is never recomputed. The tool only looks up the released precomputed table (about 73 million variants).",
    "No final pathogenic/benign call is made. The report is an aid and cannot be used on its own as the basis for a clinical decision.",
    "Non-commercial in-house use only (Department of Clinical Genetics, Hyogo Medical University Hospital). Neither the tool nor the index is redistributed, in accordance with the PolyForm Strict 1.0.0 licence of FuncVEP.",
  ]));

  B.push(h1("3. Users and operating environment"));
  B.push(...bullets([
    "Users: physicians and genetic counsellors of the department, who transcribe the variant from the laboratory report.",
    "Environment: one Windows PC in the hospital. A local web application (Python, Streamlit) used from a browser; the reference index resides on a local drive.",
    "Connectivity: index lookups are fully offline. Some information (population frequency and others, section 5) is queried from public APIs; only variant coordinates and the like are sent, never patient data. The lookups can be switched off for offline use.",
    "Languages: the screen and the PDF can be switched between Japanese and English.",
  ]));

  B.push(h1("4. Input"));
  B.push(p("Because laboratory reports vary in notation, the parser does not match fixed patterns. It extracts the components present in the input — gene symbol, transcript accession, c. notation and p. notation — and combines whatever is available. Differences in parentheses, colons, spaces and full-width characters are tolerated."));
  B.push(table(["Example input", "Interpretation"], [
    ["BRCA1 p.Arg1699Trp / BRCA1 R1699W / BRCA1:p.R1699W", "Gene symbol and amino-acid substitution, resolved as a residue on the MANE transcript"],
    ["NM_007294.4:c.5095C>T / NM_007294.4(BRCA1):c.5095C>T", "Transcript accession and c. notation; translated on the CDS to obtain the substitution"],
    ["SDHB c.574T>C (p.Cys192Arg) / SDHB p.Cys192Arg (c.574T>C)", "Both notations; the c. notation is used and its translation is checked against the p. notation"],
    ["SDHB c.574T>C", "c. notation without a transcript; applied to the gene's MANE Select, with a note in the report"],
    ["SDHB(NM_003000.3):c.574T>C / full-width characters", "Gene with transcript in parentheses, full-width text and similar variants are handled likewise"],
  ], [40, 60]));
  B.push(spacer());
  B.push(p("Resolution rules: the c. notation takes precedence when present, because it fixes the nucleotide. A disagreement between the translated c. notation and an accompanying p. notation is flagged. When neither a transcript nor a p. notation is given, the report notes that the reference transcript was assumed. Unreadable input returns an error stating what could be recognised."));

  B.push(h1("5. Data sources"));
  B.push(h2("5.1 Local index (offline)"));
  B.push(table(["Data", "Content used", "Role"], [
    ["FuncVEP / ClinVEP prediction table (Zenodo, 73,092,279 rows)", "FuncVEP-CTI / CTE / SP and ClinVEP-CTI / CTE / SP scores", "Primary evidence; looked up by genomic coordinate (chr-pos-ref-alt)"],
    ["AlphaMissense (Cheng et al. 2023)", "Score and class; residue numbering and coordinates per transcript", "Bridge from amino-acid substitution to genomic coordinate; comparison predictor"],
    ["REVEL (Ioannidis et al. 2016)", "Score", "Comparison with a conventional ensemble predictor"],
    ["ClinVar variant_summary", "Clinical significance, review status, submitter count, conditions, VariationID", "Existing classifications; also classifications of other variants at the same residue"],
    ["gnomAD gene constraint", "pLI, missense z, LoF z", "Whether the gene tolerates variation"],
    ["MANE (summary and CDS sequences)", "Gene–transcript mapping, CDS sequences", "Transcript resolution, translation of c. notation, reference-residue check"],
  ], [34, 33, 33]));
  B.push(spacer());
  B.push(p("The index is stored as Parquet (6–8 GB) and queried with DuckDB; a lookup takes about 0.3 s per variant."));
  B.push(h2("5.2 Public API lookups (online, switchable)"));
  B.push(table(["Source", "Retrieved", "Data sent", "Cache"], [
    ["gnomAD v4 (GraphQL API)", "Allele frequency, homozygote count, East Asian frequency, coverage at the position, rsID", "Chromosome, position, alleles", "24 h"],
    ["TogoVar (NBDC/DBCLS, REST API)", "Japanese population frequency: ToMMo 54KJPN (mostly healthy, about 54,000 individuals) as the reference; NCBN, GEM-J WGA and JGA as supplementary", "Chromosome, position", "24 h"],
    ["Ensembl VEP (REST, SpliceAI plugin)", "Four SpliceAI delta scores and positions", "Chromosome, position, alleles", "24 h"],
    ["ClinGen Gene-Disease Validity", "Strength of gene–disease relationships, mode of inheritance", "None (whole CSV downloaded)", "30 days"],
    ["MaveDB (API)", "Measured scores of multiplexed functional assays and investigator-defined functional classes", "Gene symbol (search)", "Search 30 days; data permanent"],
    ["ClinVar (NCBI E-utilities)", "Per-condition classification, submission count and review status", "VariationID", "24 h"],
    ["LitVar2 (NCBI) + PubMed", "Publications mentioning the variant (screen only, not in the PDF)", "Gene symbol and substitution, rsID", "24 h"],
  ], [26, 38, 20, 16]));
  B.push(spacer());
  B.push(p("No patient information is transmitted. When a lookup fails, the report says so and the screen offers a manual-entry field for values printed on the laboratory report."));

  B.push(h1("6. Processing pipeline"));
  B.push(...numbered([
    "Parse: extract the components and decide gene, transcript, c. and p. notations (section 4).",
    "Fix the transcript and substitution: choose the MANE transcript; translate c. notation on the CDS; for p. notation, check that the reference residue matches the CDS (handles genes whose MANE Select and MANE Plus Clinical differ in numbering).",
    "Fix the genomic coordinate: use the AlphaMissense index to find chr-pos-ref-alt for the transcript, residue and substitution. All nucleotide changes producing the same substitution are kept as candidates. Transcript-version differences and isoform offsets are absorbed by a mapping table and a checked fallback path.",
    "Gather evidence: FuncVEP, REVEL and ClinVar by coordinate; gene constraint and MANE data by gene; other ClinVar variants at the same residue.",
    "Online lookups: gnomAD, TogoVar, SpliceAI, ClinGen, MaveDB and ClinVar per-condition counts (skipped when offline).",
    "Organise evidence: map it to ACMG criteria (section 7) and summarise the predictor calls.",
    "Assemble and output: build the sections in Japanese or English, show them on screen and generate the PDF (A4, with the issuing department and page numbers).",
  ]));

  B.push(h1("7. Mapping of evidence to ACMG criteria"));
  B.push(table(["Evidence", "Source", "Criterion", "Presentation"], [
    ["FuncVEP-CTI / CTE / SP scores", "FuncVEP table", "PP3 / BP4 (computational)", "Score, damaging / neutral call and evidence tier (Supporting / Moderate / Intermediate / Strong) using the authors' Supplementary Table 13 thresholds (Appendix A)"],
    ["AlphaMissense, REVEL, ClinVEP", "Local indexes", "Reference", "Scores and classes; a summary box lists which predictors fall on the damaging and neutral sides"],
    ["Other nucleotide changes producing the same substitution", "ClinVar index", "PS1 candidate", "Stated as a PS1 candidate when classified pathogenic, with a caveat about splicing differences"],
    ["Substitutions to a different amino acid at the same position", "ClinVar index", "PM5 candidate", "Number of pathogenic classifications; benign classifications noted"],
    ["Allele frequency, homozygotes", "gnomAD, TogoVar", "BA1 (above 0.05), BS1, BS2", "Frequency and allele counts; BA1 flagged above 0.05"],
    ["Absence from population databases", "gnomAD", "PM2_supporting candidate", "Used as evidence only when coverage at the position is adequate"],
    ["Measured functional-assay results", "MaveDB", "Material for PS3 / BS3", "Measured score and investigator-defined normal / abnormal class"],
    ["Effect on splicing", "SpliceAI", "Premise of the missense evaluation", "Note at delta 0.2 or above; at 0.5 or above, re-evaluation as a splicing variant is advised"],
    ["Gene–disease relationship, inheritance", "ClinGen", "Context for pLI, BS2 and PM2", "Gene-level associated diseases, with the entry matching the variant's main ClinVar condition marked"],
    ["Clinical classification of this variant", "ClinVar", "Existing classification", "Significance, review stars, conditions ordered by submission count (with a note that conditions are submitter-entered and unverified)"],
  ], [24, 16, 20, 40]));
  B.push(spacer());
  B.push(p("The report only indicates candidate criteria; whether to apply a criterion and at what strength is left to the interpreter."));

  B.push(h1("8. Variants without a FuncVEP score"));
  B.push(p("Scores are withheld for training variants in the released table. Based on correspondence with the authors (5 and 7 September 2026), the report distinguishes three situations:"));
  B.push(...bullets([
    "Row present but score blank: the variant was in the training set of some models; those models' scores are withheld.",
    "No row at all: the variant was in the training sets of all six models, was excluded from every model's inference, and therefore does not appear in the merged table.",
    "No row and not in any published training set: a consequence of dataset assembly (annotation differences, absence from source data, processing gaps).",
    "In every case the report states that the absence of a score carries no information about pathogenicity or prediction confidence, and directs the reader to AlphaMissense, REVEL and ClinVar. Training-set membership per model is shown from the published training sets.",
  ]));
  B.push(p("Measured locally on ClinVar missense variants with two or more review stars: 11.3% of 24,010 pathogenic variants (4.9% no row, 6.7% blank) and 7.0% of 38,528 benign variants have no score. Of the 2,948 variants without a row, 83.3% are explained by the training sets; the remaining 487 fall under the third situation."));

  B.push(h1("9. Report structure"));
  B.push(...numbered([
    "Title, issuing department, query, creation time",
    "Variant under evaluation: substitution, genomic coordinate (GRCh38), transcript; all candidates if more than one",
    "Notes: matters affecting interpretation of the input (multiple candidates, assumed transcript, p. disagreement, SpliceAI warning); omitted when none apply",
    "Gene: pLI, missense z, LoF z (each with a one-line verdict and explanation); ClinGen gene-level associated diseases",
    "Per variant (banded heading; page break before the second candidate): population frequency (gnomAD), FuncVEP, other predictors (ClinVEP, AlphaMissense, REVEL, SpliceAI), functional-assay data (MaveDB, when available), summary of predictor calls (tinted box), ClinVar (this variant), ClinVar (other variants at the same amino-acid position)",
    "About the PP3/BP4 thresholds, interpretation notes (banded heading), acknowledgements, references",
  ]));
  B.push(p("Wording policy: Japanese text is written in the polite register throughout and technical terms are defined at first use; English call words such as damaging / neutral are glossed in Japanese. The colour of the summary box (red, green or amber) shows only whether the predictors agree, and the box itself states that it is not a pathogenicity judgement."));

  B.push(h1("10. Verification"));
  B.push(...bullets([
    "62 unit tests (input parsing, codon translation, parsing of each API response, classification of same-position variants).",
    "Self-test on 25 known inputs (including HGVS cross-checks and inputs that must be rejected): 19 OK, 6 informational, 0 failures. The 6 informational cases are missing FuncVEP scores due to training-set membership, all explained.",
    "Coordinate check: TP53 p.Arg175His maps to chr17:7,675,088 on GRCh38. Transcript-version differences and isoform offsets were measured and the fallback path verified.",
    "Coverage of the released table measured locally and reconciled with the authors (discrepancy table shared on 6 September 2026).",
  ]));
  B.push(table(["Variant used", "What was checked"], [
    ["BRCA1 p.Arg1699Trp", "PP3_Strong on all three FuncVEP models; ClinVar expert-panel 3 stars; Arg1699Gln and Arg1699Leu pathogenic at the same position (PM5 candidate)"],
    ["BRCA1 p.Cys61Gly", "\"Abnormal\" in the BRCA1 SGE dataset (Findlay et al. 2018) in MaveDB; datasets that carry only c. notation are matched by translating on the CDS"],
    ["HBB p.Glu7Val", "FuncVEP neutral but clinically pathogenic (HbS polymerisation): an example of functional impact diverging from pathogenicity. Absent from ToMMo; present only in NCBN (shown as supplementary)"],
    ["FGFR3 p.Gly380Arg", "Two nucleotide changes for one substitution (G>A blank for three models, G>C absent for all six); each is a PS1 candidate for the other. ClinVar conditions by submission count: achondroplasia 38"],
    ["NEFL p.Pro8Leu", "No row in the released table; absent from gnomAD (PM2_supporting candidate); Pro8Arg and Pro8Gln pathogenic at the same position (PM5 candidate)"],
    ["SDHB c.574T>C (p.Cys192Arg)", "Report-style input; c. and p. notations agree and the variant resolves without a note"],
  ], [30, 70]));

  B.push(h1("11. Interpretation limits"));
  B.push(...bullets([
    "FuncVEP predicts the effect on protein function, not clinical pathogenicity itself. Gain-of-function, aggregation and variable-penetrance variants can be pathogenic despite a low functional score.",
    "Under ACMG/AMP the scores count as PP3/BP4 (computational evidence), never as PS3/BS3 (functional evidence).",
    "Missense variants only; effects on splicing are shown separately through SpliceAI.",
    "ClinVar conditions are submitter-entered and unverified; ClinGen assessments are gene-level.",
    "The report is an aid and cannot be used on its own as the basis for a clinical decision.",
  ]));

  B.push(h1("12. Licensing and data governance"));
  B.push(...bullets([
    "FuncVEP: PolyForm Strict 1.0.0 (non-commercial; no modification or redistribution). The prediction table and the index stay within the institution.",
    "AlphaMissense: CC BY-NC-SA 4.0. REVEL: non-commercial. ClinVar and MANE: public domain. gnomAD: CC0.",
    "Only code and documentation are shared, in a private repository, for the authors' review.",
  ]));

  B.push(h1("13. Acknowledgements"));
  B.push(p("The FuncVEP components of this tool were completed with the generous help of the authors, Kerem Çil, Barış Kayaalp and Tayfun Özçelik (Bilkent University), who provided the published PP3/BP4 calibration values (Supplementary Table 13) and clarified variants absent from the released table. We are grateful for their support."));

  B.push(new Paragraph({ children: [new PageBreak()] }));
  B.push(h1("Appendix A. PP3/BP4 thresholds (Supplementary Table 13)"));
  B.push(p("PP3 applies when the score is at or above the threshold, BP4 when it is at or below. Tiers follow Supporting / Moderate / Intermediate / Strong (Bergquist et al. 2025, Genet Med). The damaging / neutral boundary (binary) differs by model and is not 0.5."));
  B.push(thresholdTable());
  B.push(spacer());
  B.push(h1("Appendix B. Components"));
  B.push(table(["File", "Role"], moduleRows(true), [35, 65]));
  return B;
}

function thresholdTable() {
  const rows = [
    ["FuncVEP-CTI", "0.6903", "0.8023", "0.8583", "0.9109", "0.1352", "0.0643", "0.0262", "0.0174", "0.4196"],
    ["FuncVEP-CTE", "0.7976", "0.8803", "0.9370", "0.9758", "0.1407", "0.0278", "0.0171", "0.0106", "0.5193"],
    ["FuncVEP-SP", "0.7646", "0.8933", "0.9351", "0.9943", "0.1654", "0.0803", "0.0276", "0.0159", "0.4409"],
    ["AlphaMissense", "0.5479", "0.8071", "0.8794", "0.9798", "0.1703", "0.1130", "0.0973", "0.0836", "0.3984"],
  ];
  return table(["Model", "PP3 Sup", "PP3 Mod", "PP3 Int", "PP3 Str", "BP4 Sup", "BP4 Mod", "BP4 Int", "BP4 Str", "binary"], rows,
    [16, 9, 9, 9, 9, 9, 9, 9, 9, 12]);
}

function moduleRows(en = false) {
  const r = [
    ["app.py", en ? "Streamlit screen (Japanese / English)" : "Streamlit の画面（日本語・英語）"],
    ["funcvep_report/variant.py", en ? "Input parsing, amino-acid codes, codon translation" : "入力の解析、アミノ酸表記、コドン翻訳"],
    ["funcvep_report/lookup.py", en ? "Index queries (DuckDB), transcript and coordinate resolution, evidence gathering" : "索引の照会（DuckDB）、転写産物と座標の解決、証拠の収集"],
    ["funcvep_report/acmg.py", en ? "PP3/BP4 tiers from the published thresholds" : "公表閾値による PP3/BP4 の段階"],
    ["funcvep_report/report.py", en ? "Report assembly (sections, notes, ACMG candidates)" : "報告書の組み立て（節、注記、ACMG の候補）"],
    ["funcvep_report/pdfout.py", en ? "PDF output (fpdf2; BIZ UDP Gothic / Arial)" : "PDF 出力（fpdf2。BIZ UDP ゴシック／Arial）"],
    ["funcvep_report/i18n.py", en ? "All Japanese / English strings" : "日本語・英語の全文字列"],
    ["gnomad.py, togovar.py, spliceai.py, clingen.py, mavedb.py, clinvar_api.py, litvar.py", en ? "Clients for the public APIs (section 5.2)" : "公開 API への照会（5.2 節）"],
    ["scripts/01–06", en ? "Download references, build the index, local calibration (comparison only), self-test, fetch training sets, audit absent scores" : "参照データの取得、索引の構築、自前較正（比較用）、セルフテスト、学習セットの取得、未収録の監査"],
    ["data/acmg_thresholds_published.json", en ? "Supplementary Table 13 values as provided by the authors" : "著者提供の Supplementary Table 13 の値"],
    ["tests/", en ? "Unit tests (62)" : "単体テスト（62 件）"],
  ];
  return r;
}

// ---------------------------------------------------------------- build
function build(lang) {
  const isJa = lang === "ja";
  const body = isJa ? contentJA() : contentEN();
  const footerText = isJa ? "兵庫医科大学病院 遺伝子医療部　遺伝子ミスセンス変異 統合評価レポート 要件定義と設計概要" : "Department of Clinical Genetics, Hyogo Medical University Hospital — Missense Variant Evaluation Report: Requirements and Design Overview";
  const doc = new Document({
    creator: "Department of Clinical Genetics, Hyogo Medical University Hospital",
    title: isJa ? "遺伝子ミスセンス変異 統合評価レポート 要件定義と設計概要" : "Missense Variant Evaluation Report — Requirements and Design Overview",
    styles: {
      default: { document: { run: { font: { ascii: "Arial", hAnsi: "Arial", eastAsia: isJa ? "BIZ UDPGothic" : "BIZ UDPGothic", cs: "Arial" }, size: 20 } } },
      paragraphStyles: [
        { id: "Heading1", name: "Heading 1", basedOn: "Normal", next: "Normal", quickFormat: true, run: { size: 30, bold: true, color: "1C4E80" }, paragraph: { spacing: { before: 360, after: 160 }, outlineLevel: 0 } },
        { id: "Heading2", name: "Heading 2", basedOn: "Normal", next: "Normal", quickFormat: true, run: { size: 24, bold: true, color: "1C4E80" }, paragraph: { spacing: { before: 240, after: 120 }, outlineLevel: 1 } },
      ],
    },
    numbering: {
      config: [
        { reference: "bul", levels: [{ level: 0, format: LevelFormat.BULLET, text: "•", alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 540, hanging: 300 } } } }] },
        { reference: "num", levels: [{ level: 0, format: LevelFormat.DECIMAL, text: "%1.", alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 540, hanging: 360 } } } }] },
      ],
    },
    sections: [{
      properties: { page: { margin: { top: 1300, bottom: 1300, left: 1300, right: 1300 } } },
      footers: {
        default: new Footer({ children: [new Paragraph({ alignment: AlignmentType.CENTER, children: [
          new TextRun({ text: footerText + "  —  ", size: 16, color: "666666" }),
          new TextRun({ children: [PageNumber.CURRENT], size: 16, color: "666666" }),
        ] })] }),
      },
      children: body,
    }],
  });
  return Packer.toBuffer(doc);
}

(async () => {
  const jaName = "遺伝子ミスセンス変異_統合評価レポート_要件定義と設計概要.docx";
  const enName = "Missense_Variant_Evaluation_Report_Requirements_and_Design.docx";
  fs.writeFileSync(path.join(OUT_DIR, jaName), await build("ja"));
  fs.writeFileSync(path.join(OUT_DIR, enName), await build("en"));
  console.log("written:", jaName, "|", enName);
})();
