# arXiv New Paper Discord Digest Bot

arXiv API (Atom/XML) から論文メタデータを取得し、Discord Webhook に日次ダイジェスト投稿する Python Bot です。

- デフォルト監視トピック: LLM / Diffusion / PINN
- submittedDate ソートで新着を取得
- ルールベースで教育的キーワードを検出し `✔︎` を付与
- トピックごとに `Latest` と `Educational / Beginner-friendly ✔︎` を分けて投稿
- 送信済み arXiv ID (`v1`, `v2` 付き) を `state/state.json` に保存して重複投稿を防止
- GitHub Actions で毎日自動実行し、`state/` 更新を自動 commit/push

LLM や有料 API は使っていません。

## Repository Layout

```text
.
├─ src/
│  ├─ main.py
│  ├─ arxiv_client.py
│  ├─ parser.py
│  ├─ filter_rank.py
│  ├─ state.py
│  ├─ discord_webhook.py
│  └─ util.py
├─ config.yaml
├─ requirements.txt
├─ README.md
├─ state/
│  └─ state.json
└─ .github/workflows/daily.yml
```

## Discord Webhook 作成手順

1. Discord の対象サーバーでチャンネル設定を開く
2. `連携サービス` -> `ウェブフック` -> `新しいウェブフック`
3. Webhook URL をコピー

## GitHub Secrets 設定

1. リポジトリの `Settings` -> `Secrets and variables` -> `Actions`
2. `New repository secret`
3. Name: `DISCORD_WEBHOOK_URL`
4. Value: 作成した Discord Webhook URL

## ローカル実行

```bash
python -m pip install -r requirements.txt
export DISCORD_WEBHOOK_URL="https://discord.com/api/webhooks/..."
python -m src.main
```

## config.yaml カスタマイズ

`config.yaml` で次を変更できます。

- `lookback_hours`: 取りこぼし対策の再探索時間
- `max_latest_items_per_topic`: トピックごとの最新論文の上限件数
- `max_educational_items_per_topic`: トピックごとの教育的論文の抽出件数
- `arxiv.max_results_per_topic`: API 取得件数
- `topics[].query_terms` / `topics[].categories`: キーワードとカテゴリ
- `discord.title_max_length`: 1行タイトルのトリム長
- `discord.header_template`: 見出しテンプレート (`{date_jst}`, `{datetime_jst}` を利用可能)

例: LLM にキーワードを追加

```yaml
topics:
  - name: LLM
    query_terms:
      - large language model
      - LLM
      - instruction tuning
      - RLHF
      - language model
      - alignment
```

## 実装上のポイント

- arXiv API endpoint: `http://export.arxiv.org/api/query`
- sort: `sortBy=submittedDate`, `sortOrder=descending`
- デフォルト3トピックを順番に問い合わせ、各クエリ間で `sleep(3.1)` して arXiv のレート制約に配慮
- Discord は `allowed_mentions: {"parse": []}` を指定し、メンション事故を防止
- Webhook `content` の 2000 文字制限を超えないように自動分割投稿
- `last_success_utc` と `lookback_hours` を組み合わせた安全側 cutoff で遅延実行時の取りこぼしを減らす

## GitHub Actions

`/.github/workflows/daily.yml` で毎日 1 回実行します。

- cron: `0 1 * * *` (UTC) = 毎日 10:00 JST
- 実行後に `state/` が更新されていれば自動で commit & push
- 失敗時はジョブが non-zero で終了

## 教育的✔︎判定ルール

タイトルまたは要約に次の語が含まれると `✔︎` を付与します (大文字小文字無視)。

- survey
- tutorial
- review
- primer
- introduction
- lecture notes
- notes
- pedagogical
- overview
- a guide
- beginner / for beginners
- fundamentals / foundations
- from scratch
- step by step
- how to
- explainer
- roadmap
