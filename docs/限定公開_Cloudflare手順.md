# 限定公開の手順（Cloudflare 側の作業）

作成日: 2026-09-12。同日に実施し、ログインしてアプリが出ることを確認した。
以下は実際の画面（2026 年 9 月の Cloudflare One の版）に合わせて書き直したもの。

このツールを「ログインした人だけがブラウザから使える」形にするための手順です。
アプリと索引データはこの PC に置いたまま、Cloudflare を経由して外から届くようにします。
本書は **あなたがブラウザ上で行う作業** をまとめたものです。PC 側の設定（cloudflared の
常駐、アプリの自動起動）は、本書の手順が済んでから別途行います。

ドメインは Cloudflare で取得済みの **human-genetics.uk** を使います。アプリの URL は
次のとおりです。

```
https://missense.human-genetics.uk
```

---

## 0. Cloudflare とは

Cloudflare は、インターネットの「配送と門番」を請け負う米国の会社です。世界のウェブ
サイトのかなりの割合が、この会社の設備を通して配信されています。個人や小規模利用向けに
無料プランがあり、今回の用途はすべて無料の範囲に収まります。

今回使う機能は 3 つです。

| 機能 | 役割 | たとえ |
|---|---|---|
| DNS | ドメイン名（住所）の管理。Cloudflare で取得したので設定済み | 住所録 |
| Tunnel | この PC から Cloudflare へ内側から接続を張り、外からの通信を PC に届ける | PC から外へ延ばした専用の管 |
| Access | URL を開いた人にログインを求め、登録した人だけ通す | 門番 |

Tunnel を使うので、大学のネットワークに外から入る口を開ける必要はありません。PC が
自分から Cloudflare につなぎに行き、その管を通って利用者の画面が届きます。

---

## 1. 全体の流れ

```
利用者のブラウザ
   │  https://missense.human-genetics.uk を開く
   ▼
Cloudflare Access ── 登録メールアドレスに 6 桁の番号を送る ── 番号を入力
   │  通過
   ▼
Cloudflare Tunnel ── この PC が張った管
   │
   ▼
この PC の Streamlit（127.0.0.1:8501）
```

作業の順番は次のとおりです。2 から 4 はあなたの作業、5 は PC 側の作業です。

1. ドメインの状態を確認する（取得済み）
2. Cloudflare Zero Trust を有効にする
3. Tunnel を作る
4. Access でログインを必須にする
5. （PC 側）cloudflared を常駐させ、アプリを自動起動にする
6. 動作確認のうえ、UMIN のポータルにリンクを置く

---

## 2. ドメインの状態を確認する

1. https://dash.cloudflare.com/ にログインします。
2. トップに human-genetics.uk が表示され、状態が「Active」になっていることを確認します。
   Cloudflare で取得したドメインは、取得直後から Active です。
3. 確認できたら次へ進みます。DNS の記録を手で追加する必要はありません。後の手順で
   Tunnel が自動で追加します。

---

## 3. Cloudflare Zero Trust を有効にする

Tunnel と Access は「Zero Trust」（画面上の名称は Cloudflare One）という管理画面に
まとまっています。

1. https://one.dash.cloudflare.com/ を開きます。
2. 「Choose a plan」の画面で **Zero Trust Free**（50 人まで）の「Select plan」を押します。
   支払い方法の登録を求められる場合がありますが、Free プランでは請求されません。
3. チーム名は聞かれず、自動で付きます（今回は `floral-wood-5683`）。ログイン画面の
   URL に使われるだけで動作に影響はありません。変えたい場合は左メニュー下の
   「Settings」→「Team name」の Edit で変更できます。
4. 左に「Networks」「Access controls」「Integrations」「Settings」などのメニューが
   並ぶ画面になれば完了です。

---

## 4. Tunnel を作る

1. Zero Trust の左メニューで「Networks」→「Tunnels & Mesh」を開きます。
2. 「Create a tunnel」→ 種類は「Cloudflared」を選び、名前を `missense` として保存します。
3. 「Install and run a connector」の画面で OS に **Windows** を選ぶと、次のような
   インストールコマンドが表示されます（実際の文字列はもっと長く、末尾に長い英数字が
   付きます）。
   ```
   cloudflared.exe service install eyJhIjoi...
   ```
   末尾の英数字はこの Tunnel の鍵です。**他人に見せないでください。**
4. この画面はいったんそのままにして、PC 側の作業に進みます。cloudflared 本体は
   `winget install --id Cloudflare.cloudflared` で先に入れてあります
   （C:\Program Files (x86)\cloudflared\cloudflared.exe）。スタートボタンを右クリック
   →「ターミナル（管理者）」を開き、コピーしたコマンドを貼り付けて実行します。
   Windows サービス `cloudflared` が「実行中・自動」で登録され、画面下の
   「Connectors」に PC の接続が表示されれば成功です。
5. 「Next」で「Public Hostname」の設定に進み、次のとおり入力して保存します。

   | 項目 | 値 |
   |---|---|
   | Subdomain | missense |
   | Domain | human-genetics.uk |
   | Path | 空欄 |
   | Type | HTTP |
   | URL | 127.0.0.1:8501 |

   これで「https://missense.human-genetics.uk への通信を、この PC の 8501 番に届ける」
   設定ができます。DNS の記録は自動で追加されます。

   URL は「localhost:8501」ではなく「127.0.0.1:8501」にします。Windows では localhost が
   まず IPv6 の ::1 に解決されるため、他のアプリが同じポートをすべてのアドレスで
   待ち受けていると、トンネルがそちらに届いてしまいます（8 の事例を参照）。

---

## 5. Access でログインを必須にする

### 5-1. One-time PIN を追加する（先に行う）

初期状態のログイン方法は「Cloudflare」（Cloudflare のアカウントでログイン）だけで、
メールに番号を送る方式は入っていません。先に追加します。

1. 左メニューの「Integrations」→「Identity providers」を開きます。
2. 「Add new」を押し、一覧から **One-time PIN** を選んで保存します。設定項目はありません。

### 5-2. ポリシーを作る

1. 左メニューの「Access controls」→「Policies」を開き、「Create new policy」を押します
   （アプリ作成の画面からも同じボタンで作れます）。
2. 次のとおり入力します。

   | 項目 | 値 |
   |---|---|
   | Policy name | allowed-users |
   | Action | Allow |
   | Policy session duration | Same as application session duration |
   | Include | Selector を「Emails」にし、許可する人のメールアドレスを 1 件ずつ追加 |

   「Additional settings」「Connection settings」は触りません。
3. 「Save policy」を押します。

ここに学内の利用者と著者のメールアドレスを登録します。後から追加・削除できます。
まずは自分のアドレスだけ登録し、動作確認後に増やすのが安全です。

### 5-3. アプリを登録する

1. 左メニューの「Access controls」→「Applications」を開きます。
2. 「Add an application」→「Self-hosted」を選びます。
3. 「Destinations」の Public hostnames に、Subdomain `missense`、Domain
   `human-genetics.uk`、Path は空欄で入れます。
4. 「Access policies」の欄で「Add current policies」から `allowed-users` を選びます。
5. 「Authentication」の欄で次のとおりにします。

   | 項目 | 値 |
   |---|---|
   | Accept all available identity providers | オフ |
   | Choose available identity providers | One-time PIN だけ |
   | Apply instant authentication | オン（選択画面を飛ばし、すぐメールアドレス入力になる） |

   「Accept all」がオンのままだと「Apply instant authentication」は選べず、また
   ログイン画面に「Cloudflare」のボタンが出て Cloudflare アカウントのログインを
   求められます。
6. 「Details」の Name を `Missense variant report`、Session Duration を `24 hours` にします。
7. 一番下の「Save」を押します。

---

## 6. 動作確認

PC 側の作業（cloudflared の常駐とアプリの起動）が済んだ状態で確認します。

1. 別の端末（スマートフォンの回線など、大学のネットワーク外）で
   https://missense.human-genetics.uk を開きます。
2. Cloudflare のログイン画面が出て、メールアドレスを求められます。
3. 登録したアドレスを入れると 6 桁の番号がメールで届くので、入力します。
4. アプリの画面が出れば完了です。
5. 登録していないアドレスで試し、拒否されることも確認します。

---

## 7. UMIN のポータルにリンクを置く

square.umin.ac.jp/genetics/ の該当ページに、次のようなリンクを 1 行加えます。

```html
<a href="https://missense.human-genetics.uk">ミスセンス変異レポートツール（要ログイン）</a>
```

UMIN 側には URL を書くだけで、追加の設定は要りません。

---

## 8. 運用上の注意

- **PC が止まっていると使えません。** 停止中に開くと Cloudflare のエラー画面が出ます。
- **利用者の追加・削除** は手順 5-2 のポリシー（Access controls → Policies → allowed-users）で行います。
- **取り決めとの関係**: README と設計書の「院内・研究室内での利用に留める」方針の範囲で、
  ログインで学内と著者に限った運用です。著者への問い合わせに、この運用の可否を確認する
  項目を加えます。
- **費用**: Cloudflare の機能は無料プランの範囲です。ドメイン human-genetics.uk の
  更新費用だけがかかります。
- **他の Streamlit と同じポートにしない。** 2026-09-13 に別プロジェクト（がんゲノム報告書
  治験探索）の Streamlit がポート 8501 でアドレス指定なしに起動され、公開 URL がそちらの
  アプリを表示する事故が起きました。このプロジェクトのサーバーは 127.0.0.1 だけで
  待ち受けますが、トンネルの転送先が「localhost:8501」だったため、::1 で待ち受けていた
  別アプリに届いていました。対処は、別アプリの停止と、転送先を「127.0.0.1:8501」に
  変更すること。他のプロジェクトの Streamlit は 8501 以外のポートで起動します。
