# 🌿 訪問看護ナビ

全国の訪問看護ステーションを、現在地から近い順に検索できるツールサイトです。
精神科対応・医療的ケア対応等の特化情報は、現時点では関西2府4県（大阪・京都・兵庫・奈良・滋賀・和歌山）のみ調査済みです。
## 📁 ファイル構成

```
houmonkango/
├ index.html                    ← UI本体（検索・フィルター・候補リスト等）
├ build.py                      ← CSV＋AIリサーチ結果 → 都道府県別JSON生成
├ jigyosho_130.csv              ← 厚労省「介護サービス情報公表システム」オープンデータ
├ specialty_result_kansai.json  ← Colabで実行した特化情報リサーチ結果
├ wrangler.json                 ← Cloudflare Worker設定
├ .gitignore
└ README.md                     ← このファイル
```

`dist/`フォルダは`build.py`実行時に自動生成されます（Gitでは管理しません）。

## 🔧 データの更新について

`jigyosho_130.csv`は厚労省が年2回（6月末・12月末時点）更新します。最新版は以下から取得できます。

```
https://www.mhlw.go.jp/stf/kaigo-kouhyou_opendata.html
```

「130_訪問看護」のファイルをダウンロードし、`jigyosho_130.csv`として置き換えてください。

`specialty_result_kansai.json`は、Google Colaboratory上で特化情報リサーチスクリプトを実行することで更新できます（別途お渡しした`houmonkango_kansai_specialty_research.py`を使用）。

## 🚀 手動デプロイの手順

このプロジェクトは**完全手動デプロイ**です（GitHub Actions等の自動デプロイは組み込んでいません）。

### 初回のみ

```bash
npm install -g wrangler
wrangler login
```

ブラウザが開くので、Cloudflareアカウントでログインしてください。

### 毎回のデプロイ手順

1. 必要なファイル（`jigyosho_130.csv` / `specialty_result_kansai.json` / `index.html` / `build.py`）が同じフォルダにあることを確認

2. ビルドを実行（`dist/`フォルダが生成されます）

```bash
python3 build.py
```

3. Cloudflareにデプロイ

```bash
wrangler deploy
```

4. 初回デプロイ後、Cloudflareダッシュボードでカスタムドメインを設定してください

```
Workers & Pages → houmonkango（対象Worker）→「ドメイン」タブ → 「+ ドメインを追加」
→ houmonkango.pray-power-is-god-and-cocoro.com を入力
```

## ⚠️ 公開前に必ず確認すること

- `index.html`内の`<meta name="robots" content="noindex">`を削除する
- `<link rel="canonical" ...>`のURLが実際の本番URLと一致しているか確認する
- `favicon.ico`をルート直下に設置する（現時点ではコードのみ設置済み、画像は未設置）

## 📊 データの位置づけ・免責について

「精神科対応」「医療的ケア対応」「小児対応」「リハビリ特化」の特化タグは、行政の公式データには含まれていない情報です。AIが各事業所の公式ホームページを自動調査し、キーワードから推定したものであり、正確性を保証するものではありません。ご利用の際は必ず電話や公式サイトでご確認ください（`index.html`内にも同様の免責を掲載しています）。
