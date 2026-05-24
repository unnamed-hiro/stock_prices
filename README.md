# stock_prices — 株式売買シミュレーションシステム

日本株400銘柄をAIに売買させ、**実弾を使わずに**戦略の有効性を検証するための
ペーパートレード基盤です。条件を満たした戦略だけを実取引に進める運用を想定しています。

## 特徴

- **400銘柄ユニバース** — JPX日経400ベースの日本株を `data/universe_jp.csv` で管理
- **プラガブルAI** — テクニカル / 機械学習 / LLM (Claude API) を `config.yaml` で切替
- **ペーパートレード専用** — 実発注ロジックは持たず、誤発注の事故が起きない設計
- **明文化された成功条件** — 勝率・損益比・シャープ・最大DD・年率リターンを自動判定
- **キャッシュ** — yfinanceで一度取得した価格は `data/cache/` に再利用

## ディレクトリ構成

```
stock_prices/
├── config.yaml              # ★ ここを編集して条件を変える
├── data/
│   ├── universe_jp.csv      # 銘柄リスト (約400)
│   └── cache/               # 価格キャッシュ (自動生成)
├── src/
│   ├── config.py            # 設定ローダ
│   ├── universe.py          # 銘柄リスト読込
│   ├── data_fetcher.py      # yfinance ラッパー
│   ├── portfolio.py         # 資金・保有・取引記録
│   ├── backtester.py        # 日次ループ実行
│   ├── metrics.py           # 成績集計と成功判定
│   └── strategies/
│       ├── base.py          # 戦略インターフェース
│       ├── technical.py     # MA + RSI + 出来高
│       ├── ml.py            # LightGBM / ロジスティック回帰
│       └── llm.py           # Claude API
├── app/
│   └── dashboard.py         # 結果ビューア (Streamlit)
├── scripts/
│   ├── fetch_prices.py      # 価格事前ダウンロード
│   ├── run_backtest.py      # バックテスト実行 (メイン)
│   └── generate_sample_results.py  # ダッシュボード動作確認用ダミーデータ
├── tests/
│   └── test_portfolio.py    # 資金管理ユニットテスト
└── results/                 # 実行結果 JSON (自動生成)
```

## セットアップ

```bash
pip install -r requirements.txt
```

LLM戦略を使う場合のみ:
```bash
export ANTHROPIC_API_KEY=sk-ant-...
```

## クイックスタート

### 1. まず動作確認 (10銘柄で1分)

```bash
python scripts/run_backtest.py --limit 10
```

### 2. テクニカル戦略で400銘柄フル実行

```bash
python scripts/run_backtest.py --strategy technical
```

### 3. 機械学習戦略に切替

```bash
python scripts/run_backtest.py --strategy ml
```

### 4. LLM戦略 (API課金あり)

```bash
python scripts/run_backtest.py --strategy llm --limit 30
```

### 5. 結果をブラウザで確認

```bash
# yfinanceに繋がらない環境でも先にサンプル結果を生成できる
python scripts/generate_sample_results.py

# ダッシュボード起動
streamlit run app/dashboard.py
```

ダッシュボードでは以下を確認できます:

- **総合サマリ** — 累積/年率リターン、シャープ、最大DD、エクイティカーブ、採用判定
- **銘柄別** — 全銘柄の損益ランキング、勝率、平均保有日数
- **銘柄詳細** — 銘柄を選択して取引履歴と売却タイミング別損益を可視化
- **全取引** — buy/sellでフィルタ、CSVダウンロード

## 設定変更 (`config.yaml`)

| 項目 | 説明 | デフォルト |
|---|---|---|
| `simulation.initial_capital` | 初期資金 (円) | 1,000,000 |
| `simulation.commission_rate` | 手数料率 | 0.1% |
| `simulation.start_date / end_date` | 期間 | 2023-01-01 〜 2024-12-31 |
| `risk.position_size_pct` | 1銘柄あたり資産配分 | 5% |
| `risk.stop_loss_pct` | 損切ライン | -5% |
| `risk.take_profit_pct` | 利確ライン | +15% |
| `universe.max_positions` | 同時保有上限 | 20銘柄 |
| `strategy.name` | 使う戦略 | `technical` |

## 成功条件 (採用判定)

`config.yaml > success_criteria` の全項目を満たした戦略だけを「採用候補」とします。

| 指標 | デフォルト基準 | 意味 |
|---|---|---|
| 勝率 | ≥ 55% | 取引の半分以上が利益で終わる |
| 損益比 | ≥ 1.5 | 総利益が総損失の1.5倍以上 |
| シャープレシオ | ≥ 1.0 | 安定したリターン |
| 最大ドローダウン | ≤ 20% | 一時的な落ち込みが2割以内 |
| 年率リターン | ≥ 10% | 銀行預金より有意に高い |
| 最低取引数 | ≥ 20 | 統計的に十分なサンプル |

## 実取引へ進む際の運用フロー

1. **複数戦略をバックテスト** — `technical` / `ml` / `llm` をそれぞれ実行
2. **成功条件を全て満たす戦略を特定** — `results/last_run.json` を比較
3. **out-of-sample検証** — 別期間 (例: 2025年データ) で再現性を確認
4. **少額の実弾運用** — 別途実発注モジュールを追加 (本リポジトリには含めない)
5. **継続モニタリング** — 月次で成績と成功条件を再評価

## 注意事項

- このシステムは**投資判断の参考用**であり、利益を保証しません
- 価格データは過去のものであり、将来の値動きを予測するものではありません
- 実取引機能は意図的に含めていません。誤発注を防ぐためです
- LLM戦略はAPI課金が発生します。`--limit` で銘柄数を絞ってください

## テスト

```bash
pytest tests/
```

## 動作確認 (このリポジトリを試したい方へ)

ダッシュボードを実際にブラウザで確認する手順です。

### A. ローカルPCで動かす (推奨)

```bash
# 1. ブランチを取得
git clone https://github.com/unnamed-hiro/stock_prices.git
cd stock_prices
git checkout claude/stock-trading-ai-sim-os7Ax

# 2. 依存をインストール
pip install -r requirements.txt

# 3a. ネットワーク不要のサンプル結果で動作確認
python scripts/generate_sample_results.py

# 3b. または実データでバックテスト (yfinanceで取得)
python scripts/run_backtest.py --limit 20

# 4. ダッシュボード起動 → ブラウザで自動的に開く
streamlit run app/dashboard.py
```

`http://localhost:8501` でダッシュボードが見えます。サイドバーから `results/` 配下の
複数の結果ファイルを切り替えられます。

### B. コードだけGitHub上で確認

- PR: https://github.com/unnamed-hiro/stock_prices/pull/1
- "Files changed" タブで全変更を確認できます

### C. Streamlit Community Cloud で無料デプロイ

URLを誰かと共有したい場合の選択肢です。

1. https://share.streamlit.io にGitHubアカウントでログイン
2. リポジトリ `unnamed-hiro/stock_prices` を選択
3. メインファイルに `app/dashboard.py` を指定
4. 公開URLが発行されます

### 動作確認用のテストデータ

`scripts/generate_sample_results.py` で複数パターンのダミー結果を生成できます。

```bash
# デフォルト: 中程度の成績 (一部基準クリア)
python scripts/generate_sample_results.py

# 全パターン生成 (好成績/不振/平均) — 比較表示の確認に
python scripts/generate_sample_results.py --all
```

ダッシュボード起動後、サイドバーから複数の結果を切り替えて比較できます。
