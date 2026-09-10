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
let _numSeq = 0;
function numbered(items) {
  const ref = `num${++_numSeq}`;
  return items.map(t => new Paragraph({
    numbering: { reference: ref, level: 0 }, spacing: { after: 80, line: 280 },
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
  B.push(small(`版 1.1　${DATE}　作成: 兵庫医科大学病院 遺伝子医療部　宛先: FuncVEP の著者（Kerem Çil、Barış Kayaalp、Tayfun Özçelik の各氏、Bilkent 大学）`));
  B.push(small("版 1.1 は、版 1.0（2026-09-10）に対する設計文書レビューの 10 項目を反映したものです。変更点は付録 D にまとめました。"));
  B.push(spacer());
  B.push(new TableOfContents("目次", { hyperlink: true, headingStyleRange: "1-2" }));
  B.push(new Paragraph({ children: [new PageBreak()] }));

  B.push(h1("1. 目的"));
  B.push(p("検査会社の報告書に記載されたミスセンス変異について、それが病的か良性かを判断する手がかりとなる情報を 1 通の報告書に集めることが、このツールの目的です。判断そのものは行いません。ACMG/AMP の変異解釈基準に沿って証拠を整理し、臨床遺伝の専門家が解釈するための補助資料を作ります。"));
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
    ["SDHB c.574T>C (p.Cys192Arg) / SDHB p.Cys192Arg (c.574T>C)", "c. と p. の併記。c. を使い、翻訳結果が p. と一致するかを照合する。食い違えば評価を行わずに止める"],
    ["SDHB c.574T>C", "転写産物番号の無い c. 表記。遺伝子の MANE Select に当てはめ、その旨を「評価対象の変異」の欄に添える"],
    ["SDHB(NM_003000.3):c.574T>C / ＳＤＨＢ　ｃ．５７４Ｔ＞Ｃ", "遺伝子と転写産物の併記、全角文字なども同様に解釈"],
  ], [40, 60]));
  B.push(spacer());
  B.push(p("解決の規則: c. 表記があればそれを優先します（塩基まで決まるため）。c. 表記で入力されたときは、入力の塩基置換をゲノムの塩基に読み替え、それと一致する候補だけを評価します。同じアミノ酸置換を生じる塩基置換をすべて候補に並べるのは、p. 表記だけの入力に限ります。読めない入力には、どこまで読めたかを添えたエラーを返します。"));
  B.push(p("次の状況では、転記ミスの可能性があるため評価を行わずに止め、確認を促します。"));
  B.push(table(["状況", "扱い"], [
    ["c. から求めたアミノ酸置換が、併記の p. と食い違う", "止める。両方の表記を示し、転写産物番号の確認を促す"],
    ["入力の遺伝子名と、転写産物番号の遺伝子が違う", "止める"],
    ["c. の参照塩基が CDS 配列と合わない", "止める"],
    ["c. の塩基置換が、その位置で同じアミノ酸置換を生じる塩基置換と一致しない", "止める"],
    ["指定の転写産物番号が MANE に無い", "止める。RefSeq の版だけが違う場合は解決し、版の違いを「評価対象の変異」の欄に添える"],
    ["転写産物番号の無い c. 表記", "遺伝子の MANE Select に当てはめ、「入力に転写産物番号なし。MANE Select を適用」と添える"],
  ], [50, 50]));
  B.push(spacer());
  B.push(p("転写産物の選び方: 遺伝子に MANE Select と MANE Plus Clinical の両方があるときは、入力の参照アミノ酸が一致する転写産物を選びます。Plus Clinical は Select では表現できない臨床的に重要な変異を補うための転写産物であり、残基番号の補正ではありません。AlphaMissense の対応表に無い遺伝子では、MANE の遺伝子領域内で同じアミノ酸置換を持つ行を探す予備経路に回りますが、転写産物全体の残基一致率が 0.95 以上で、比較できた残基数が 20 以上のときだけ採用します。この条件を満たさなければ理由を示して止めます。"));

  B.push(h1("5. データ源"));
  B.push(h2("5.1 手元に置く索引（オフライン）"));
  B.push(table(["データ", "使う内容", "役割"], [
    ["FuncVEP / ClinVEP 予測表（Zenodo、73,092,279 行）", "FuncVEP-CTI / CTE / SP と ClinVEP-CTI / CTE / SP のスコア", "主たる証拠。ゲノム座標（chr-pos-ref-alt）で引く"],
    ["AlphaMissense（Cheng ら 2023）", "スコアと区分、転写産物ごとの残基番号と座標", "アミノ酸置換からゲノム座標への橋渡し、および比較用の予測"],
    ["REVEL（Ioannidis ら 2016）", "スコア", "従来型の統合予測との比較"],
    ["ClinVar variant_summary", "臨床的意義（生殖細胞系列の分類のみ）、レビュー段階、提出者数、疾患名、VariationID", "既知の臨床判定。同じアミノ酸位置の他の変異の判定にも使う。体細胞の臨床的意義と発がん性は扱わない"],
    ["gnomAD 遺伝子制約", "pLI、missense z、LoF z", "遺伝子が変異に耐えられるかの背景"],
    ["MANE（要約と CDS 配列）", "遺伝子と転写産物の対応、CDS 配列", "転写産物の解決、c. 表記の翻訳、参照アミノ酸の確認"],
  ], [34, 33, 33]));
  B.push(spacer());
  B.push(p("索引は Parquet 形式で 6〜8 GB、DuckDB で照会します。1 変異あたりの照会は 0.3 秒程度です。"));
  B.push(h2("5.2 公開 API への照会（オンライン、切り替え可）"));
  B.push(table(["データ源", "取得する内容", "送る情報", "キャッシュ"], [
    ["gnomAD v4（GraphQL API）", "アレル頻度、集団別の最大頻度、ホモ接合体数、東アジア集団の頻度、その位置の読み取り深度、rsID", "染色体・位置・塩基", "24 時間"],
    ["TogoVar（NBDC/DBCLS、REST API）", "日本人集団の頻度。ToMMo 54KJPN（健常者中心、約 54,000 人）を参照とし、NCBN・GEM-J WGA・JGA は参考。区間検索の結果から染色体・位置・参照塩基・変異塩基がすべて一致する 1 件だけを採る", "染色体・位置", "24 時間"],
    ["Ensembl VEP（REST、SpliceAI プラグイン）", "SpliceAI の Δ スコア 4 種と位置", "染色体・位置・塩基", "24 時間"],
    ["ClinGen Gene-Disease Validity", "遺伝子と疾患の関係の確立度、遺伝形式", "なし（一覧 CSV を丸ごと取得）", "30 日"],
    ["MaveDB（API）", "大規模機能実験の実測スコアと、研究者が定めた正常／異常の区分", "遺伝子記号（検索）", "検索 30 日、データは永続"],
    ["ClinVar（NCBI E-utilities）", "疾患名ごとの判定・提出件数・レビュー段階。提出者が任意で記入した遺伝形式の件数（AD／AR などの略号で集計、参考）", "VariationID", "24 時間"],
    ["LitVar2（NCBI）+ PubMed", "変異に言及した論文（画面のみ、PDF には載せない）", "遺伝子記号と置換、rsID", "24 時間"],
  ], [26, 38, 20, 16]));
  B.push(spacer());
  B.push(p("いずれも患者情報は送りません。通信できない場合は「取得できなかった」と表示し、検査報告書の値を手入力できる欄を案内します。"));

  B.push(h1("6. 処理の流れ"));
  B.push(...numbered([
    "入力の解析: 部品を拾って、遺伝子・転写産物・c. 表記・p. 表記を決める（4 節）。",
    "転写産物とアミノ酸置換の確定: 参照アミノ酸が一致する MANE の転写産物（Select、または Plus Clinical）を選び、c. 表記は CDS 配列で翻訳する。併記の p. と食い違えば止める。",
    "ゲノム座標の確定: AlphaMissense の索引で、その転写産物・残基番号・置換に対応する chr-pos-ref-alt を求める。c. 表記があれば入力の塩基置換と一致する候補だけを残し、p. 表記だけなら同じアミノ酸置換を生じる塩基置換をすべて候補にする。転写産物 ID の世代差やアイソフォームのずれは対応表と、採用条件付きの予備経路（4 節）で吸収する。",
    "証拠の収集: 座標で FuncVEP・REVEL・ClinVar を引き、遺伝子で制約指標と MANE の情報を引く。同じアミノ酸位置の他の ClinVar 変異も集める。",
    "オンライン照会: gnomAD、TogoVar、SpliceAI、ClinGen、MaveDB、ClinVar 疾患別件数を取得する（オフラインなら省く）。",
    "証拠の整理: ACMG の基準に対応づける（7 節）。予測ツールの判定をまとめる。",
    "報告書の組み立てと出力: 日本語または英語の文言で節を組み立て、画面に表示し、PDF（A4、発行元とページ番号入り）を生成する。末尾に、参照データの版・閾値の版・コードの版・取得日時・転写産物の解決経路・PP3/BP4 の採用モデルを記録する。",
  ]));

  B.push(h1("7. 証拠と ACMG 基準の対応"));
  B.push(table(["証拠", "出典", "対応する基準", "報告書での示し方"], [
    ["FuncVEP-CTI / CTE / SP のスコア", "FuncVEP 予測表", "PP3 / BP4（コンピュータ予測）", "スコア、damaging / neutral の判定、証拠の段階（Supporting / Moderate / Intermediate / Strong）。閾値は著者提供の Supplementary Table 13（付録 A）。PP3/BP4 は事前に固定した採用モデル（7.1 節）で判定し、他のモデルは参考"],
    ["AlphaMissense、REVEL、ClinVEP", "各索引", "参考", "スコアと区分。予測ツールの判定のまとめで、damaging 側・neutral 側に分けて要約"],
    ["同じアミノ酸置換を起こす別の塩基変異", "ClinVar 索引", "PS1 の候補", "病的判定があれば PS1 の候補と明記し、各変異に評価日と疾患名を添える。判定が 1 星以下だけなら弱い候補と注記。スプライシングの違いに注意を添える"],
    ["同じ位置で別のアミノ酸への置換", "ClinVar 索引", "PM5 の候補", "病的判定の件数と、良性判定があればその旨。評価日と疾患名、1 星以下だけなら弱い候補と注記"],
    ["アレル頻度、集団別の最大頻度、ホモ接合体数", "gnomAD、TogoVar", "BA1 の候補、BS1、BS2", "頻度とアレル数。集団別の最大頻度が 0.05 を超えれば BA1 の候補と示す。疾患・遺伝子ごとの例外、対象集団、アレル数の十分さ、BS2 の前提（遺伝形式、発症年齢、浸透率、健康状態）は本レポートでは確認していないと明記"],
    ["集団データベースに無いこと", "gnomAD", "PM2_supporting の候補", "その位置の読み取り深度が十分なときだけ候補とする。深度が不十分・未取得、通信失敗、オフラインでは候補にしない（7.2 節）"],
    ["機能実験の実測値", "MaveDB", "PS3 / BS3 の材料", "実測スコアと、研究者が定めた正常／異常の区分。塩基が一致した実測値と、アミノ酸置換で照合した実測値（塩基は不明）を区別する。対象転写産物・測定変異数・区分の名称・出典を示し、PS3/BS3 の適用には実験内容の確認が必要と明記"],
    ["スプライシングへの影響", "SpliceAI", "ミスセンスとしての評価の前提", "Δ 0.5 以上は BP4 を保留し、判定のまとめの箱を橙にする。0.2 以上 0.5 未満は BP4 に要確認と添える。未取得なら未評価と明記（7.1 節）"],
    ["遺伝子と疾患の関係、遺伝形式", "ClinGen", "pLI・BS2・PM2 の読み方の前提", "遺伝子単位の関連疾患を一覧し、ClinVar で提出件数が最多の疾患名と名称が一致するものに印（参考）"],
    ["この変異の臨床判定", "ClinVar", "既知の判定", "臨床的意義（生殖細胞系列）、レビュー段階、疾患名を提出件数順に。3 星以上は専門家パネルの判定と強調。疾患名は提出者の登録で検証済みでなく、件数は提出数で症例数ではない旨を注記。提出者が記入した遺伝形式は AD／AR などの略号で件数のみ一行に集計（参考。根拠は ClinGen の欄）"],
  ], [24, 16, 20, 40]));
  B.push(spacer());
  B.push(p("報告書は基準の「候補」を示すにとどめ、適用の可否と強さの判断は解釈者に委ねます。"));
  B.push(h2("7.1 PP3/BP4 に採用するモデルと、SpliceAI との整合"));
  B.push(...bullets([
    "PP3/BP4 に用いるモデルは 1 つに事前固定します。当面は FuncVEP-CTI（設定 primary_model で変更可）。報告書に「PP3/BP4 の採用モデル」を明記し、採用モデルの欄に（採用）、他の欄に（参考）を付けます。",
    "CTE と SP は段階を表示しますが証拠として数えず、モデル間の一致で強さを上げません。判定のまとめの箱の色は予測が揃っているかの表示であり、証拠の強さではありません。",
    "採用モデルにスコアが無いときは CTE → SP の順に代替し、その旨を明記します。3 つとも無ければ PP3/BP4 は判定できません。AlphaMissense は代替にしません。",
    "どのモデルを臨床の PP3/BP4 に用いるべきか、また ClinVar に判定がある変異に CTI を用いることの是非は、著者に確認します（付録 C）。",
  ]));
  B.push(table(["SpliceAI の Δ", "PP3/BP4", "判定のまとめの箱"], [
    ["0.5 以上", "BP4 を保留（適用しない旨を表示）。PP3 は影響しない", "橙にし、スプライシングへの影響が示唆される旨を一行添える"],
    ["0.2 以上 0.5 未満", "BP4 は出すが「要確認」と添える", "一行添える（色は変えない）"],
    ["0.2 未満", "変更なし", "変更なし"],
    ["未取得（オフライン、失敗、スコアなし）", "BP4 に「スプライシングへの影響は未評価」と添える。保留にはしない", "一行添える"],
  ], [24, 40, 36]));
  B.push(spacer());
  B.push(h2("7.2 集団頻度の取得状態と、PM2 の扱い"));
  B.push(table(["状態", "表示", "PM2_supporting"], [
    ["記録あり", "頻度、アレル数、集団別の最大頻度、ホモ接合体数", "対象外"],
    ["記録なし、読み取り深度が十分", "収録なし（深度の値を添える）", "候補"],
    ["記録なし、読み取り深度が不十分", "収録なし（深度不足のため根拠としない）", "候補にしない"],
    ["記録なし、読み取り深度が未取得", "収録なし（深度未確認のため根拠の可否は判断できない）", "候補にしない"],
    ["記録あり、品質フィルタに該当", "頻度とフィルタ名", "対象外"],
    ["通信失敗・部分応答", "取得できず（理由）", "候補にしない"],
    ["未照会（オフライン）", "未取得（オンライン照会が無効）", "候補にしない"],
    ["手入力", "入力された値（手入力である旨）", "候補にしない"],
  ], [34, 42, 24]));
  B.push(spacer());

  B.push(h1("8. FuncVEP のスコアが無い変異の扱い"));
  B.push(p("公開された予測表では、学習に用いた変異のスコアが出ません。報告書は、行の有無、モデル別のスコアの有無、公開されている学習セットとの一致、原因の確認状態を分けて書きます。"));
  B.push(...bullets([
    "表に行はあるがスコアが空欄: 公開されている学習セットとの照合で、一部のモデルの学習データに含まれていたことが確認できた変異。該当モデルのスコアは公開されない（著者確認済み、2026-09-05）。",
    "表に行そのものが無く、6 モデルすべての学習セットに含まれる: 各モデルの推論から除外され、統合表に現れない（著者確認済み、2026-09-05）。",
    "行が無く、公開されている学習セットにも見当たらない: 原因は手元では確認できない。著者の照合（2026-09-07）では、この種の未収録に元データに無い・注釈の違いによる除外・処理の抜けが原因のものがあると説明されたが、個々の変異について確定したものではない。報告書もそのように書く。",
    "いずれの場合も「スコアが無いこと自体は病原性についても予測の確からしさについても情報を持たない」と明記し、AlphaMissense・REVEL・ClinVar で判断するよう案内する。どのモデルの学習に使われたかは、公開されている学習セットとの照合で表示する。",
  ]));
  B.push(p("著者の説明を引用する箇所の対象範囲: 手元の照合は、ClinVar variant_summary（2026-08-27 取得）でレビュー段階が 2 星以上、MANE Select 転写産物上の 1 塩基置換によるミスセンス変異に限って行いました。著者に送付した不一致表（2026-09-06）もこの範囲のものです。"));
  B.push(p("手元の実測（scripts/06_missing_scores_audit.py、2026-09-10 再実行）: 対象は上記の範囲の ClinVar の行 63,329 件（変異としては 63,275 件。複数の遺伝子に登録された変異は行ごとに数えています）。病的（P/LP）24,716 件のうち、行なし 1,232 件（5.0%）、空欄 1,545 件（6.3%）、合わせて 2,777 件（11.2%）でスコアが得られません。良性（B/LB）38,613 件では、行なし 1,716 件（4.4%）、空欄 866 件（2.2%）、合わせて 2,582 件（6.7%）です。行の無い 2,948 件のうち 2,457 件（83.3%）は 6 モデルすべての学習セットに含まれ、4 件は一部のモデルの学習セットに含まれ、残る 487 件はどの学習セットにも見当たりません（上記 3 番目）。版 1.0 の数値（24,010 件、11.3% など）は、終止コドン喪失などの除外条件が異なる以前の集計によるもので、本版の数値に置き換えます。"));

  B.push(h1("9. 報告書の構成"));
  B.push(...numbered([
    "表題、発行元、入力、作成日時",
    "評価対象の変異: アミノ酸置換、ゲノム座標（GRCh38）、転写産物。候補が複数なら全部",
    "注意: 入力の解釈に関わる事項（候補が複数、SpliceAI の警告）。該当が無ければ出ない。転写産物の当てはめは「評価対象の変異」の欄に添え、p. の食い違いは評価を止める",
    "遺伝子: pLI、missense z、LoF z（値ごとの一言と解説）、ClinGen の評価（遺伝子単位の関連疾患）",
    "変異ごと（帯状の見出し。2 つ目以降は改ページ）: 集団頻度（gnomAD）、FuncVEP、他の予測ツール（ClinVEP、AlphaMissense、REVEL、SpliceAI）、機能実験の実測値（MaveDB、あれば）、予測ツールの判定のまとめ（色付きの箱）、ClinVar（この変異の登録）、ClinVar（同じアミノ酸位置に報告されている他の変異）",
    "PP3/BP4 の判定基準について、解釈上の注意（帯状の見出し）",
    "データの版と解決経路: 参照データの版と索引の作成日、閾値の版、コードの版（git のコミット識別子）、オンライン照会の取得日時、転写産物と座標の解決経路、PP3/BP4 の採用モデル（代替を使ったか）",
    "謝辞、参考文献",
  ]));
  B.push(p("文章の方針: 日本語はすべてです・ます調で、専門用語は初出で意味を定義します。damaging / neutral などの英語の判定語には和訳を添えます。判定のまとめの箱の色（赤系・緑系・橙系）は予測ツールの判定が揃っているかを示すもので、病原性の判定ではないことを箱の中に明記します。"));

  B.push(h1("10. 検証"));
  B.push(...bullets([
    "単体テスト 70 件（入力解析、コドン翻訳、各 API の応答の読み取り、同じ位置の判定の振り分け、PP3/BP4 の閾値の境界、SpliceAI と BP4 の連動、集団頻度の取得状態、版と解決経路の節）と、索引を使う統合テスト 4 件（下表）。",
    "セルフテスト: 既知の 25 変異（HGVS 表記との突き合わせ、拒否されるべき入力を含む）で OK 19 / 注意 6 / NG 0。注意 6 件は学習データによるスコア欠落で、いずれも説明が付く。",
    "座標系の確認: TP53 p.Arg175His が GRCh38 の chr17:7,675,088 に一致。転写産物 ID の世代差、アイソフォームのずれについて予備経路の安全性を実測で確認。",
    "公開予測表の網羅性の実測と、著者への照合（2026-09-06 に不一致表を共有）。",
  ]));
  B.push(table(["レビューの確認項目", "テストでの期待"], [
    ["同じ p. を生む 2 種類の塩基置換を c. で入力", "入力した塩基置換だけを評価する（FGFR3 c.1138G>A → 1 候補、p.Gly380Arg → 2 候補）"],
    ["遺伝子・転写産物・c.・p. の矛盾", "未解決として止める（c. と p. の食い違い、遺伝子と転写産物の食い違い、参照塩基の不一致）"],
    ["通信失敗・部分応答・オフライン", "「収録なし」や PM2 の候補に変換しない"],
    ["FuncVEP neutral ＋ SpliceAI 高値", "BP4 を保留し、まとめの箱を橙にする"],
    ["閾値の直前・一致・直後、欠測", "境界どおりの段階（付録 A の CTI の値で確認）"],
    ["別の変異を続けて照会", "前の変異のデータや手入力の頻度が混入しない（画面のテスト）"],
  ], [40, 60]));
  B.push(spacer());
  B.push(table(["確認に用いた変異", "確認した点"], [
    ["BRCA1 p.Arg1699Trp", "FuncVEP 3 モデルとも PP3_Strong。ClinVar 専門家パネル 3 星。同じ位置の Arg1699Gln・Leu が病的（PM5 候補）"],
    ["BRCA1 p.Cys61Gly", "MaveDB の SGE（Findlay ら 2018）で「異常」。c. 表記しか持たない実験データを、評価対象の c.181T>G と塩基で照合（実験側は NM_007294.3、版違い）"],
    ["HBB p.Glu7Val", "FuncVEP は neutral だが臨床的には病的（HbS の重合）。機能予測と病原性の乖離の例。日本人集団は ToMMo に無く NCBN のみ（参考扱い）"],
    ["FGFR3 p.Gly380Arg / c.1138G>A", "同じアミノ酸置換に塩基置換が 2 通り（G>A は 3 モデルの学習による空欄、G>C は 6 モデルによる欠落）。p. 入力では両方、c. 入力では G>A だけを評価。互いに PS1 候補。ClinVar の疾患名は件数順で achondroplasia が 38 件"],
    ["NEFL p.Pro8Leu", "予測表に行が無い例。gnomAD 収録なし（PM2_supporting 候補）。同じ位置の Pro8Arg・Gln が病的（PM5 候補）"],
    ["SDHB c.574T>C (p.Cys192Arg)", "報告書形式の入力。c. と p. の一致を確認し、注意を出さずに解決"],
  ], [30, 70]));

  B.push(h1("11. 解釈上の限界"));
  B.push(...bullets([
    "FuncVEP が予測するのはタンパク質の働きへの影響であり、臨床的病原性そのものではありません。機能獲得型・凝集型・浸透率が可変の変異では、機能予測が低くても病的でありえます。",
    "ACMG/AMP では PP3/BP4（コンピュータ予測）として扱い、PS3/BS3（機能実験）にはなりません。",
    "対象はミスセンス変異のみで、スプライシングへの影響は SpliceAI で別途示します。",
    "ClinVar の疾患名は提出者の登録であり、検証されたものではありません。件数は提出数で、独立した症例数ではありません。ClinGen の評価は遺伝子単位で、ClinVar の疾患名との照合は名称によるもの（参考）です。疾患 ID（MedGen、MONDO）による照合は将来の課題です。",
    "ClinVar は生殖細胞系列の分類のみを扱い、体細胞の臨床的意義と発がん性は扱いません。",
    "BA1・BS2・PM2・PS1・PM5・PS3/BS3 はいずれも「候補」の提示で、疾患別の例外や実験内容の確認は解釈者が行います。",
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
  B.push(spacer());
  B.push(h1("付録 C. 著者への質問"));
  B.push(...numbered([
    "臨床の PP3/BP4 には、FuncVEP-CTI、CTE、SP のどのモデルを採用するのが適切でしょうか。本ツールは当面 CTI を採用モデルとし、他の 2 つは参考としています。",
    "ClinVar に判定がある変異について、ClinVar 由来の情報を材料に含む CTI を PP3/BP4 に用いることに問題はないでしょうか。独立性を優先して CTE を採用モデルにすべき場合があれば教えてください。",
    "付録 A の閾値が、Supplementary Table 13 の原本と一致しているかをご確認ください。",
  ]));
  B.push(h1("付録 D. 版 1.0 からの変更点（設計文書レビューへの対応）"));
  B.push(...bullets([
    "c. 表記の入力では、入力した塩基置換と一致する候補だけを評価する（4 節）。",
    "c. と p. の食い違い、遺伝子と転写産物の食い違いは評価を止める。版だけが違う転写産物は解決して注記する（4 節）。",
    "BA1 は「候補」に留め、集団別の最大頻度を示す。BS2 の前提を注記する（7 節）。",
    "PP3/BP4 の採用モデルを固定し、代替の順序を明記する（7.1 節）。",
    "SpliceAI の Δ 0.5 以上で BP4 を保留し、まとめの箱を橙にする。未取得は未評価と明記する（7.1 節）。",
    "MaveDB は塩基で照合し、アミノ酸置換だけの照合と区別する。PS3/BS3 の適用に確認が必要と明記する（7 節）。",
    "ClinVar の疾患名と提出件数の性質、生殖細胞系列の分類であること、3 星以上の強調、PS1/PM5 の評価日と疾患名、1 星以下の弱い候補（7 節、11 節）。",
    "未収録の原因を断定せず、確認状態を分けて書く。実測の数値を再集計し、分母と重複の扱いを明記する（8 節）。",
    "読み取り深度が未取得の「収録なし」を PM2 の候補にしない。取得状態の一覧（7.2 節）。",
    "報告書末尾に「データの版と解決経路」の節を設け、参照データの版を索引フォルダーに記録する（9 節）。レビューの 6 ケースをテストに追加した（10 節）。",
  ]));
  return B;
}

// ---------------------------------------------------------------- content (EN)
function contentEN() {
  const B = [];
  B.push(new Paragraph({ spacing: { after: 60 }, children: [new TextRun({ text: "Department of Clinical Genetics, Hyogo Medical University Hospital", size: 20, color: "555555" })] }));
  B.push(new Paragraph({ spacing: { after: 120 }, children: [new TextRun({ text: "Missense Variant Evaluation Report", bold: true, size: 40 })] }));
  B.push(new Paragraph({ spacing: { after: 240 }, children: [new TextRun({ text: "Requirements and Design Overview", bold: true, size: 30 })] }));
  B.push(small(`Version 1.1, ${DATE}. Prepared by the Department of Clinical Genetics, Hyogo Medical University Hospital, for the FuncVEP authors (Kerem Çil, Barış Kayaalp and Tayfun Özçelik, Bilkent University).`));
  B.push(small("Version 1.1 incorporates the ten items of the design review of version 1.0 (10 September 2026); the changes are summarised in Appendix D."));
  B.push(spacer());
  B.push(new TableOfContents("Contents", { hyperlink: true, headingStyleRange: "1-2" }));
  B.push(new Paragraph({ children: [new PageBreak()] }));

  B.push(h1("1. Purpose"));
  B.push(p("The tool takes a missense variant as written on a laboratory report and assembles, in a single report, the evidence that helps a clinician judge whether the variant is pathogenic or benign. It does not make that judgement. It organises evidence along the ACMG/AMP variant-interpretation framework so that clinical geneticists can interpret it."));
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
    ["SDHB c.574T>C (p.Cys192Arg) / SDHB p.Cys192Arg (c.574T>C)", "Both notations; the c. notation is used and its translation is checked against the p. notation. A disagreement stops the evaluation"],
    ["SDHB c.574T>C", "c. notation without a transcript; applied to the gene's MANE Select, noted in the \"variant under evaluation\" entry"],
    ["SDHB(NM_003000.3):c.574T>C / full-width characters", "Gene with transcript in parentheses, full-width text and similar variants are handled likewise"],
  ], [40, 60]));
  B.push(spacer());
  B.push(p("Resolution rules: the c. notation takes precedence when present, because it fixes the nucleotide. For c. input the entered nucleotide change is converted to genomic bases and only the matching candidate is evaluated; all nucleotide changes producing the same substitution are listed only for p.-only input. Unreadable input returns an error stating what could be recognised."));
  B.push(p("The following situations stop the evaluation, because a transcription error is possible, and ask for confirmation."));
  B.push(table(["Situation", "Handling"], [
    ["Substitution derived from c. disagrees with the accompanying p.", "Stop; show both notations and ask for the transcript to be checked"],
    ["Gene symbol in the input differs from the gene of the transcript", "Stop"],
    ["Reference base of the c. notation does not match the CDS", "Stop"],
    ["The entered nucleotide change matches none of the changes producing this substitution", "Stop"],
    ["Transcript accession not in MANE", "Stop; a RefSeq version difference alone is resolved and noted in the variant entry"],
    ["c. notation without a transcript", "Applied to the gene's MANE Select, noted as \"no transcript given; MANE Select applied\""],
  ], [50, 50]));
  B.push(spacer());
  B.push(p("Transcript choice: when a gene has both a MANE Select and a MANE Plus Clinical transcript, the one whose reference residue matches the input is chosen. Plus Clinical exists to represent clinically important variants that Select cannot; it is not a numbering correction. Genes absent from the AlphaMissense mapping table go to a fallback path that searches the MANE gene region for the same substitution; a hit is accepted only when whole-transcript residue agreement is 0.95 or higher over at least 20 compared residues, otherwise the tool stops with the reason."));

  B.push(h1("5. Data sources"));
  B.push(h2("5.1 Local index (offline)"));
  B.push(table(["Data", "Content used", "Role"], [
    ["FuncVEP / ClinVEP prediction table (Zenodo, 73,092,279 rows)", "FuncVEP-CTI / CTE / SP and ClinVEP-CTI / CTE / SP scores", "Primary evidence; looked up by genomic coordinate (chr-pos-ref-alt)"],
    ["AlphaMissense (Cheng et al. 2023)", "Score and class; residue numbering and coordinates per transcript", "Bridge from amino-acid substitution to genomic coordinate; comparison predictor"],
    ["REVEL (Ioannidis et al. 2016)", "Score", "Comparison with a conventional ensemble predictor"],
    ["ClinVar variant_summary", "Clinical significance (germline classification only), review status, submitter count, conditions, VariationID", "Existing classifications; also classifications of other variants at the same residue. Somatic clinical impact and oncogenicity are not handled"],
    ["gnomAD gene constraint", "pLI, missense z, LoF z", "Whether the gene tolerates variation"],
    ["MANE (summary and CDS sequences)", "Gene–transcript mapping, CDS sequences", "Transcript resolution, translation of c. notation, reference-residue check"],
  ], [34, 33, 33]));
  B.push(spacer());
  B.push(p("The index is stored as Parquet (6–8 GB) and queried with DuckDB; a lookup takes about 0.3 s per variant."));
  B.push(h2("5.2 Public API lookups (online, switchable)"));
  B.push(table(["Source", "Retrieved", "Data sent", "Cache"], [
    ["gnomAD v4 (GraphQL API)", "Allele frequency, maximum population frequency, homozygote count, East Asian frequency, coverage at the position, rsID", "Chromosome, position, alleles", "24 h"],
    ["TogoVar (NBDC/DBCLS, REST API)", "Japanese population frequency: ToMMo 54KJPN (mostly healthy, about 54,000 individuals) as the reference; NCBN, GEM-J WGA and JGA as supplementary. From the region search, only the single record whose chromosome, position, reference and alternate alleles all match is used", "Chromosome, position", "24 h"],
    ["Ensembl VEP (REST, SpliceAI plugin)", "Four SpliceAI delta scores and positions", "Chromosome, position, alleles", "24 h"],
    ["ClinGen Gene-Disease Validity", "Strength of gene–disease relationships, mode of inheritance", "None (whole CSV downloaded)", "30 days"],
    ["MaveDB (API)", "Measured scores of multiplexed functional assays and investigator-defined functional classes", "Gene symbol (search)", "Search 30 days; data permanent"],
    ["ClinVar (NCBI E-utilities)", "Per-condition classification, submission count and review status; counts of the mode of inheritance optionally entered by submitters (AD/AR abbreviations, for reference)", "VariationID", "24 h"],
    ["LitVar2 (NCBI) + PubMed", "Publications mentioning the variant (screen only, not in the PDF)", "Gene symbol and substitution, rsID", "24 h"],
  ], [26, 38, 20, 16]));
  B.push(spacer());
  B.push(p("No patient information is transmitted. When a lookup fails, the report says so and the screen offers a manual-entry field for values printed on the laboratory report."));

  B.push(h1("6. Processing pipeline"));
  B.push(...numbered([
    "Parse: extract the components and decide gene, transcript, c. and p. notations (section 4).",
    "Fix the transcript and substitution: choose the MANE transcript (Select or Plus Clinical) whose reference residue matches; translate c. notation on the CDS; stop if it disagrees with an accompanying p. notation.",
    "Fix the genomic coordinate: use the AlphaMissense index to find chr-pos-ref-alt for the transcript, residue and substitution. With c. input only the candidate matching the entered nucleotide change is kept; with p.-only input all nucleotide changes producing the substitution are candidates. Transcript-version differences and isoform offsets are absorbed by a mapping table and a fallback path with acceptance conditions (section 4).",
    "Gather evidence: FuncVEP, REVEL and ClinVar by coordinate; gene constraint and MANE data by gene; other ClinVar variants at the same residue.",
    "Online lookups: gnomAD, TogoVar, SpliceAI, ClinGen, MaveDB and ClinVar per-condition counts (skipped when offline).",
    "Organise evidence: map it to ACMG criteria (section 7) and summarise the predictor calls.",
    "Assemble and output: build the sections in Japanese or English, show them on screen and generate the PDF (A4, with the issuing department and page numbers). The report ends with the reference-data versions, threshold version, code version, retrieval times, transcript resolution path and the model adopted for PP3/BP4.",
  ]));

  B.push(h1("7. Mapping of evidence to ACMG criteria"));
  B.push(table(["Evidence", "Source", "Criterion", "Presentation"], [
    ["FuncVEP-CTI / CTE / SP scores", "FuncVEP table", "PP3 / BP4 (computational)", "Score, damaging / neutral call and evidence tier (Supporting / Moderate / Intermediate / Strong) using the authors' Supplementary Table 13 thresholds (Appendix A). PP3/BP4 is assigned from a single pre-fixed adopted model (section 7.1); the other models are for reference"],
    ["AlphaMissense, REVEL, ClinVEP", "Local indexes", "Reference", "Scores and classes; a summary box lists which predictors fall on the damaging and neutral sides"],
    ["Other nucleotide changes producing the same substitution", "ClinVar index", "PS1 candidate", "Stated as a PS1 candidate when classified pathogenic; each variant carries its evaluation date and condition; classifications of one star or less are marked as a weak candidate; caveat about splicing differences"],
    ["Substitutions to a different amino acid at the same position", "ClinVar index", "PM5 candidate", "Number of pathogenic classifications; benign classifications noted; evaluation date and condition; weak candidate when only one-star classifications"],
    ["Allele frequency, maximum population frequency, homozygotes", "gnomAD, TogoVar", "BA1 candidate, BS1, BS2", "Frequency and allele counts; BA1 candidate when the maximum population frequency exceeds 0.05. The report states that disease- and gene-specific exceptions, the population, allele counts and the premises of BS2 (inheritance, age of onset, penetrance, health status) are not verified"],
    ["Absence from population databases", "gnomAD", "PM2_supporting candidate", "Candidate only when coverage at the position is adequate; not a candidate when coverage is inadequate or unavailable, on lookup failure, or offline (section 7.2)"],
    ["Measured functional-assay results", "MaveDB", "Material for PS3 / BS3", "Measured score and investigator-defined class. Nucleotide-matched measurements are distinguished from measurements matched by amino-acid substitution only. Target transcript, number of variants, class names and citation are shown; applying PS3/BS3 requires checking the assay"],
    ["Effect on splicing", "SpliceAI", "Premise of the missense evaluation", "Delta 0.5 or above: BP4 withheld and the summary box turns amber. 0.2 to 0.5: BP4 marked for review. Not retrieved: stated as not assessed (section 7.1)"],
    ["Gene–disease relationship, inheritance", "ClinGen", "Context for pLI, BS2 and PM2", "Gene-level associated diseases; the entry whose name matches the ClinVar condition with the most submissions is marked (for reference)"],
    ["Clinical classification of this variant", "ClinVar", "Existing classification", "Germline significance, review stars (three stars or more emphasised as an expert-panel classification), conditions ordered by submission count, with a note that conditions are submitter-entered and unverified and that counts are submissions, not cases. The mode of inheritance entered by submitters is summarised in one line as AD/AR counts (for reference; ClinGen remains the basis)"],
  ], [24, 16, 20, 40]));
  B.push(spacer());
  B.push(p("The report only indicates candidate criteria; whether to apply a criterion and at what strength is left to the interpreter."));
  B.push(h2("7.1 Model adopted for PP3/BP4, and consistency with SpliceAI"));
  B.push(...bullets([
    "A single model is fixed in advance for PP3/BP4: FuncVEP-CTI for now (configurable, primary_model). The report states the adopted model and marks its entry (adopted) and the others (reference).",
    "CTE and SP show their tiers but are not counted as evidence, and agreement between models does not raise the strength. The colour of the summary box shows whether the predictors agree, not the strength of evidence.",
    "When the adopted model has no score, CTE and then SP are used instead and the substitution is stated. With no score in any of the three, PP3/BP4 cannot be assigned. AlphaMissense is never used as a substitute.",
    "Which model should be used for clinical PP3/BP4, and whether CTI is appropriate for variants that already have a ClinVar classification, are questions for the authors (Appendix C).",
  ]));
  B.push(table(["SpliceAI delta", "PP3/BP4", "Summary box"], [
    ["0.5 or above", "BP4 withheld (stated as not applied); PP3 unaffected", "Amber, with a line that a splicing effect is suggested"],
    ["0.2 to below 0.5", "BP4 shown, marked for review", "One line added; colour unchanged"],
    ["Below 0.2", "Unchanged", "Unchanged"],
    ["Not retrieved (offline, failure, no score)", "BP4 annotated as splicing effect not assessed; not withheld", "One line added"],
  ], [24, 40, 36]));
  B.push(spacer());
  B.push(h2("7.2 Population-frequency retrieval states and PM2"));
  B.push(table(["State", "Shown as", "PM2_supporting"], [
    ["Record present", "Frequency, allele counts, maximum population frequency, homozygotes", "Not applicable"],
    ["Absent, coverage adequate", "Absent (with coverage figures)", "Candidate"],
    ["Absent, coverage inadequate", "Absent (not used as evidence because of low coverage)", "Not a candidate"],
    ["Absent, coverage unavailable", "Absent (cannot be judged because coverage is unknown)", "Not a candidate"],
    ["Record present, quality filter", "Frequency with the filter name", "Not applicable"],
    ["Lookup failed or partial", "Not retrieved (reason)", "Not a candidate"],
    ["Not queried (offline)", "Not retrieved (online lookups disabled)", "Not a candidate"],
    ["Manual entry", "Entered value, marked as manual", "Not a candidate"],
  ], [34, 42, 24]));
  B.push(spacer());

  B.push(h1("8. Variants without a FuncVEP score"));
  B.push(p("Scores are withheld for training variants in the released table. The report separates four facts: whether a row exists, which model scores are present, whether the variant is in a published training set, and whether the cause has been confirmed."));
  B.push(...bullets([
    "Row present but score blank, and the variant is found in the training set of some models: those models' scores are withheld (confirmed by the authors, 5 September 2026).",
    "No row, and the variant is in the training sets of all six models: excluded from every model's inference, hence absent from the merged table (confirmed by the authors, 5 September 2026).",
    "No row and not in any published training set: the cause cannot be determined locally. The authors' reconciliation (7 September 2026) attributed such omissions to absence from the source data, annotation-dependent filtering or processing gaps, but this has not been established for individual variants, and the report says so.",
    "In every case the report states that the absence of a score carries no information about pathogenicity or prediction confidence, and directs the reader to AlphaMissense, REVEL and ClinVar. Training-set membership per model is shown from the published training sets.",
  ]));
  B.push(p("Scope of the reconciliation quoted above: ClinVar variant_summary (downloaded 27 August 2026), review status of two stars or better, single-nucleotide missense variants on MANE Select transcripts. The discrepancy table sent to the authors (6 September 2026) covers the same scope."));
  B.push(p("Local measurement (scripts/06_missing_scores_audit.py, rerun 10 September 2026): 63,329 ClinVar rows in that scope (63,275 distinct variants; a variant listed under more than one gene is counted per row). Of 24,716 pathogenic (P/LP) rows, 1,232 (5.0%) have no row in the released table and 1,545 (6.3%) are blank, so 2,777 (11.2%) have no score. Of 38,613 benign (B/LB) rows, 1,716 (4.4%) have no row and 866 (2.2%) are blank, 2,582 (6.7%) in total. Of the 2,948 rows without a released row, 2,457 (83.3%) are in the training sets of all six models, 4 are in some training sets, and 487 are in none (the third situation above). The figures in version 1.0 (24,010 variants, 11.3% and so on) came from an earlier count with different exclusion rules (stop-loss and similar) and are superseded."));

  B.push(h1("9. Report structure"));
  B.push(...numbered([
    "Title, issuing department, query, creation time",
    "Variant under evaluation: substitution, genomic coordinate (GRCh38), transcript; all candidates if more than one",
    "Notes: matters affecting interpretation of the input (multiple candidates, SpliceAI warning); omitted when none apply. An assumed transcript is noted in the variant entry; a p. disagreement stops the evaluation",
    "Gene: pLI, missense z, LoF z (each with a one-line verdict and explanation); ClinGen gene-level associated diseases",
    "Per variant (banded heading; page break before the second candidate): population frequency (gnomAD), FuncVEP, other predictors (ClinVEP, AlphaMissense, REVEL, SpliceAI), functional-assay data (MaveDB, when available), summary of predictor calls (tinted box), ClinVar (this variant), ClinVar (other variants at the same amino-acid position)",
    "About the PP3/BP4 thresholds; interpretation notes (banded heading)",
    "Data versions and resolution path: reference-data versions and index build date, threshold version, code version (git commit), retrieval times of online lookups, transcript and coordinate resolution path, model adopted for PP3/BP4 (and whether a substitute was used)",
    "Acknowledgements, references",
  ]));
  B.push(p("Wording policy: Japanese text is written in the polite register throughout and technical terms are defined at first use; English call words such as damaging / neutral are glossed in Japanese. The colour of the summary box (red, green or amber) shows only whether the predictors agree, and the box itself states that it is not a pathogenicity judgement."));

  B.push(h1("10. Verification"));
  B.push(...bullets([
    "70 unit tests (input parsing, codon translation, parsing of each API response, classification of same-position variants, PP3/BP4 threshold boundaries, SpliceAI and BP4 interaction, population-frequency states, the provenance section) and 4 index-based integration tests (table below).",
    "Self-test on 25 known inputs (including HGVS cross-checks and inputs that must be rejected): 19 OK, 6 informational, 0 failures. The 6 informational cases are missing FuncVEP scores due to training-set membership, all explained.",
    "Coordinate check: TP53 p.Arg175His maps to chr17:7,675,088 on GRCh38. Transcript-version differences and isoform offsets were measured and the fallback path verified.",
    "Coverage of the released table measured locally and reconciled with the authors (discrepancy table shared on 6 September 2026).",
  ]));
  B.push(table(["Review case", "Expected behaviour in the tests"], [
    ["Two nucleotide changes for one substitution entered as c.", "Only the entered change is evaluated (FGFR3 c.1138G>A gives one candidate; p.Gly380Arg gives two)"],
    ["Contradiction between gene, transcript, c. and p.", "Evaluation stops (c./p. disagreement, gene/transcript disagreement, reference-base mismatch)"],
    ["Lookup failure, partial response, offline", "Never converted into absence or a PM2 candidate"],
    ["FuncVEP neutral with high SpliceAI", "BP4 withheld and the summary box turns amber"],
    ["Scores just below, at and just above thresholds; missing score", "Tier follows the boundary exactly (checked with the CTI values in Appendix A)"],
    ["Consecutive queries of different variants", "No data or manually entered frequency from the previous variant carries over (screen test)"],
  ], [40, 60]));
  B.push(spacer());
  B.push(table(["Variant used", "What was checked"], [
    ["BRCA1 p.Arg1699Trp", "PP3_Strong on all three FuncVEP models; ClinVar expert-panel 3 stars; Arg1699Gln and Arg1699Leu pathogenic at the same position (PM5 candidate)"],
    ["BRCA1 p.Cys61Gly", "\"Abnormal\" in the BRCA1 SGE dataset (Findlay et al. 2018) in MaveDB; the dataset carries only c. notation and is matched by nucleotide against c.181T>G (assay transcript NM_007294.3, version difference only)"],
    ["HBB p.Glu7Val", "FuncVEP neutral but clinically pathogenic (HbS polymerisation): an example of functional impact diverging from pathogenicity. Absent from ToMMo; present only in NCBN (shown as supplementary)"],
    ["FGFR3 p.Gly380Arg / c.1138G>A", "Two nucleotide changes for one substitution (G>A blank for three models, G>C absent for all six); p. input evaluates both, c. input only G>A. Each is a PS1 candidate for the other. ClinVar conditions by submission count: achondroplasia 38"],
    ["NEFL p.Pro8Leu", "No row in the released table; absent from gnomAD (PM2_supporting candidate); Pro8Arg and Pro8Gln pathogenic at the same position (PM5 candidate)"],
    ["SDHB c.574T>C (p.Cys192Arg)", "Report-style input; c. and p. notations agree and the variant resolves without a note"],
  ], [30, 70]));

  B.push(h1("11. Interpretation limits"));
  B.push(...bullets([
    "FuncVEP predicts the effect on protein function, not clinical pathogenicity itself. Gain-of-function, aggregation and variable-penetrance variants can be pathogenic despite a low functional score.",
    "Under ACMG/AMP the scores count as PP3/BP4 (computational evidence), never as PS3/BS3 (functional evidence).",
    "Missense variants only; effects on splicing are shown separately through SpliceAI.",
    "ClinVar conditions are submitter-entered and unverified, and submission counts are not case counts. ClinGen assessments are gene-level, and their matching to ClinVar conditions is by name only (for reference); matching by disease identifiers (MedGen, MONDO) is future work.",
    "Only germline ClinVar classifications are handled; somatic clinical impact and oncogenicity are not.",
    "BA1, BS2, PM2, PS1, PM5 and PS3/BS3 are all presented as candidates; disease-specific exceptions and assay details are for the interpreter to check.",
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
  B.push(spacer());
  B.push(h1("Appendix C. Questions for the authors"));
  B.push(...numbered([
    "Which of FuncVEP-CTI, CTE and SP should be adopted for clinical PP3/BP4? The tool currently adopts CTI and shows the other two for reference.",
    "For variants that already have a ClinVar classification, is it acceptable to use CTI, which incorporates ClinVar-derived information, for PP3/BP4? Please advise if CTE should be adopted in such cases for independence.",
    "Please confirm that the thresholds in Appendix A match the original Supplementary Table 13.",
  ]));
  B.push(h1("Appendix D. Changes from version 1.0 (response to the design review)"));
  B.push(...bullets([
    "c. input evaluates only the candidate matching the entered nucleotide change (section 4).",
    "c./p. and gene/transcript disagreements stop the evaluation; a version-only transcript difference is resolved and noted (section 4).",
    "BA1 is presented as a candidate with the maximum population frequency; BS2 premises are noted (section 7).",
    "The model adopted for PP3/BP4 is fixed and the fallback order stated (section 7.1).",
    "SpliceAI delta 0.5 or above withholds BP4 and turns the summary box amber; unassessed splicing is stated (section 7.1).",
    "MaveDB is matched by nucleotide and distinguished from amino-acid-only matches; PS3/BS3 caveat added (section 7).",
    "ClinVar: nature of conditions and submission counts, germline only, expert-panel emphasis, dates and conditions for PS1/PM5, weak candidates (sections 7 and 11).",
    "Missing scores are described without asserting a cause; figures recounted with the denominator and duplicate handling stated (section 8).",
    "Absence with unknown coverage is no longer a PM2 candidate; retrieval states tabulated (section 7.2).",
    "A data-versions-and-resolution-path section closes the report and reference-data versions are recorded in the index folder (section 9); the six review cases were added as tests (section 10).",
  ]));
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
    ["scripts/01–07", en ? "Download references, build the index, local calibration (comparison only), self-test, fetch training sets, audit absent scores, record reference-data versions" : "参照データの取得、索引の構築、自前較正（比較用）、セルフテスト、学習セットの取得、未収録の監査、参照データの版の記録"],
    ["data/acmg_thresholds_published.json", en ? "Supplementary Table 13 values as provided by the authors" : "著者提供の Supplementary Table 13 の値"],
    ["tests/", en ? "Unit tests (70) and index-based integration tests (4)" : "単体テスト（70 件）と索引を使う統合テスト（4 件）"],
  ];
  return r;
}

// ---------------------------------------------------------------- build
function build(lang) {
  const isJa = lang === "ja";
  _numSeq = 0;
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
        ...Array.from({ length: 12 }, (_, i) => ({ reference: `num${i + 1}`, levels: [{ level: 0, format: LevelFormat.DECIMAL, text: "%1.", alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 540, hanging: 360 } } } }] })),
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
