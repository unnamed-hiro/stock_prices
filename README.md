# stock_prices — 株式売買シミュレーションシステム

日本株400銘柄をAIに売買させ、**実弾を使わずに**戦略の有効性を検証するための
ペーパートレード基盤です。条件を満たした戦略だけを実取引に進める運用を想定しています。

## 特徴

- **400銘柄ユニバース** — JPX日経400ベースの日本株を `data/universe_jp.csv` で管理
- **プラガブルAI** — テクニカル / 機械学習 / ファンダメンタルズ / LLM(Claude API) / マルチAI合議制 を `config.yaml` で切替
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

### Windows ユーザー向け (ワンクリックセットアップ) ★推奨

#### ステップ1: Python のインストール (未インストールの場合のみ)

1. [https://www.python.org/downloads/](https://www.python.org/downloads/) にアクセス
2. **「Download Python 3.12.x」** の黄色いボタンをクリック
3. ダウンロードした `python-3.12.x-amd64.exe` を実行
4. **⚠重要⚠** インストール画面の最下部にある
   **「Add python.exe to PATH」のチェックボックスを必ずON** にする
5. 「Install Now」をクリック → 完了したらPCを一度再起動

確認: コマンドプロンプトで `python --version` を実行し、`Python 3.12.x` と表示されれば成功

#### ステップ2: このプロジェクトをセットアップ

1. [PR画面](https://github.com/unnamed-hiro/stock_prices/pull/1) 右上の「Code」→「Download ZIP」、または
   `git clone https://github.com/unnamed-hiro/stock_prices.git`
2. ZIP の場合は展開、フォルダを開く
3. **`setup.bat` をダブルクリック** ※初回は5〜10分かかります
4. 完了後、以下のバッチファイルから操作:

| バッチファイル | 用途 |
|---|---|
| `run_dashboard.bat` | ブラウザでダッシュボードを開く |
| `run_live.bat` | AIに当日の売買判断をさせる |
| `run_backtest.bat` | 過去データでバックテストを実行 |

#### Windows トラブルシューティング

| 症状 | 対処 |
|---|---|
| `'python' は内部コマンド〜` | PATH設定漏れ。Python再インストール時にPATHにチェック |
| PowerShell で `setup.ps1` が実行できない | 管理者PowerShellで `Set-ExecutionPolicy RemoteSigned -Scope CurrentUser` を1回実行 |
| pip インストールが極端に遅い | 社内プロキシ環境の可能性。`pip install --proxy http://proxy:port -r requirements.txt` |
| Streamlit が起動しない | ポート8501が使用中。`streamlit run app\dashboard.py --server.port 8502` で別ポート |
| ウイルス対策でブロックされる | Defender 等で `.venv` フォルダを除外設定に追加 |

### macOS / Linux ユーザー向け

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python scripts/generate_demo_prices.py    # オプション: デモデータ
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

### 4b. ファンダメンタルズ戦略 (PER/PBR/ROE)

```bash
python scripts/run_backtest.py --strategy fundamental
```

yfinanceから財務指標を取得し、**割安(PER/PBR低)かつ質が高い(ROE高)**銘柄を選好します。

> ⚠️ **先読みバイアスの注意**: yfinanceの財務指標は「現在値」のみ取得可能で、
> 過去時点の財務は取れません。**バックテストでは現在のファンダを過去に適用**するため
> 厳密には先読みバイアスが入ります。ライブ運用・本日判断では問題ありません。

### 4c. マルチAI合議制 (アンサンブル) ★おすすめ

```bash
python scripts/run_backtest.py --strategy ensemble
```

**複数の戦略を「専門家」とみなし、判断を重み付きで集約**します。全員一致なら強いシグナル、
意見が割れれば見送り — **ダマシを減らしリスクを分散**する、最も実戦的な構成です。

- **メンバー**: `technical` + `ml` + `fundamental` (デフォルト、**API課金なし**)
- **合議ルール**: 加重buyスコア ≥ `buy_threshold` かつ `min_agreement` 戦略以上が一致で買い
- **設定**: `config.yaml` の `strategy.ensemble` でメンバー・重み・閾値を調整可能

```yaml
strategy:
  ensemble:
    members: ["technical", "ml", "fundamental"]
    weights: {technical: 1.0, ml: 1.0, fundamental: 0.7}
    buy_threshold: 1.0    # 加重スコアの買い閾値
    min_agreement: 2      # 最低何戦略が一致すれば動くか
```

デモ15銘柄での検証例: 71取引・勝率62.9%・損益比1.71・最大DD-2.5%。
ブラウザの各実行タブやWindowsバッチからも `ensemble` を選べます。

### 5. AIライブ・ペーパートレード (毎日AIに判断させる)

過去データの一気再生ではなく、**毎日AIに判断させて仮想口座を更新し続ける**モード。
状態は `data/state/portfolio.json` に永続化され、複数日にわたって継続します。

```bash
# 当日 (最新営業日) の判断
python scripts/run_live.py --strategy technical

# 任意日付で実行 (例: 2024-12-20の判断)
python scripts/run_live.py --strategy technical --date 2024-12-20

# 判断のみ表示、口座変更しない
python scripts/run_live.py --strategy technical --dry-run

# 仮想口座をリセット
python scripts/run_live.py --reset
```

**毎営業日18時に自動実行** (cron):
```cron
0 18 * * 1-5 cd /path/to/stock_prices && python scripts/run_live.py --strategy technical
```

**ネットワークに繋がらない環境でデモする場合**:
```bash
python scripts/generate_demo_prices.py     # 合成価格データを生成
python scripts/run_live.py --reset
python scripts/run_live.py --limit 15 --date 2024-08-06 --lookback-days 300
```

実行時の出力例:
```
==================================================================
  AIライブ判断レポート  2024-08-06  戦略:technical
==================================================================
  開始評価額   :       5,000,000 円
  終了評価額   :       4,999,288 円  (-712 / -0.01%)
  現金残       :       4,643,680 円
  保有銘柄数   : 1
------------------------------------------------------------------
  AI判断による買付 (1件)
    7203.T 100株 @ 3,556円  = 355,608円  信頼度 0.46
      根拠: golden_cross, rsi=63.5, vol×1.5
==================================================================
```

日次ログは `results/daily/YYYY-MM-DD.json` に保存され、後でダッシュボードで確認可能。

### 5b. 準リアルタイム AI 売買 (5分ポーリング)

```bash
python scripts/run_realtime.py                  # 通常実行 (営業時間中のみ)
python scripts/run_realtime.py --once --force-run  # 1ティックだけ実行
python scripts/run_realtime.py --dry-run        # 判断のみ表示
python scripts/run_realtime.py --reset          # 仮想口座リセット
```

Windowsなら **`run_realtime.bat`** をダブルクリック。

- **データソース**: yfinance 1分足 (約15分遅延)
- **監視銘柄**: 日経主要20銘柄 (`config.yaml` の `realtime.watchlist` で変更可)
- **インジケータ**: EMA(5)/EMA(20) クロス + RSI(14) + 出来高スパイク
- **営業時間判定**: 9:00〜11:30, 12:30〜15:00 (JST) 以外は自動待機
- **状態保存**: `data/state/realtime_portfolio.json` (日次モードと分離)
- **ティック履歴**: `results/realtime/YYYY-MM-DD/HHMMSS.json`

**重要な制約:**

| 項目 | 内容 |
|---|---|
| 遅延 | Yahoo Finance の仕様で 15〜20分遅延あり |
| 真のリアルタイム | 必要なら kabuステーション API 連携など別実装が必要 |
| 仮想売買 | リアルマネーは動かない |
| Rate limit | 20銘柄×5分間隔がyfinanceの実用範囲。1分間隔や全400銘柄監視は非推奨 |

### 5c. 本日トレードシミュレーション (イントラデイ・リプレイ)

その日の1分足を**寄り付きから引けまで時系列で再生**し、AIが分単位で売買したら
どうなるかを**一気に再現**します。準リアルタイム(待つ)と違い、引け後に即座に1日を検証できます。

```bash
python scripts/run_intraday.py                    # 本日を1分ごとに判断
python scripts/run_intraday.py --date 2026-05-22  # 指定日 (直近7日以内)
python scripts/run_intraday.py --step 5           # 5分ごとに判断 (高速)
python scripts/run_intraday.py --hold             # 引けで手仕舞いせず持ち越し
```

Windowsなら **`run_intraday.bat`** をダブルクリック。ブラウザの
**「📅 本日シミュレーション」タブ**からも実行・結果確認できます。

- **データソース**: yfinance 1分足 (直近約7日のみ取得可能)
- **ロジック**: 各時点で「その時点までの情報だけ」でAI判断 (先読みなし)
- **引け処理**: デフォルトで引けに全ポジション手仕舞い (デイトレ完結)
- **独立口座**: 準リアルタイム/日次の口座には一切触れない (検証専用)
- **結果保存**: `results/intraday/YYYY-MM-DD.json` (評価額推移・全約定)

実行時の出力例:
```
==================================================================
  本日トレードシミュレーション  2026-05-22
==================================================================
  対象銘柄     : 20
  時間軸(1分足): 296 本
  開始評価額   :       5,000,000 円
  終了評価額   :       5,041,200 円  (+41,200 / +0.82%)
  約定         : 買 4件 / 売 4件 (うち利益確定 3件)
  引け手仕舞い : あり
==================================================================
```

### 6. 結果をブラウザで確認

```bash
# yfinanceに繋がらない環境でも先にサンプル結果を生成できる
python scripts/generate_sample_results.py

# ダッシュボード起動
streamlit run app/dashboard.py
```

ダッシュボードは閲覧だけでなく**全機能の操作パネル**を兼ねており、以下のタブから全機能をブラウザから利用できます:

| タブ | 機能 |
|---|---|
| **📊 結果ダッシュボード** | バックテスト/AIライブ/リアルタイムの結果を閲覧 (総合サマリ、銘柄別、銘柄詳細、全取引) |
| **▶️ バックテスト実行** | 戦略・銘柄数を選んで実行ボタン → 出力ストリーミング → 結果ファイル自動更新 |
| **🤖 AI日次判断** | 戦略・日付・dry-runを選んで実行 → レポート表示 |
| **⏱️ 準リアルタイム** | 1ティック実行ボタン、30秒ごと自動実行チェック、評価額グラフ、保有ポジション |
| **📁 生ログ** | results/ 配下のJSONログを直接閲覧 |
| **⚙️ 設定編集** | config.yaml をブラウザから編集・保存 (構文チェック + 自動バックアップ) |

これで **コマンドプロンプト不要** で全機能を利用できます。バッチファイル (`run_backtest.bat` 等) も引き続き使えます。

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

### C. Streamlit Community Cloud で無料デプロイ (Webで誰でも閲覧)

URLを誰かと共有したい / 外出先のスマホからも見たい場合の最も簡単な方法です。
サーバー契約・課金は不要で、実行ボタンも全部動きます。

**手順:**

1. https://share.streamlit.io に GitHubアカウントでログイン
2. 「New app」→ 「Deploy a public app from GitHub」
3. 以下を指定:
   - **Repository**: `unnamed-hiro/stock_prices`
   - **Branch**: `claude/stock-trading-ai-sim-os7Ax` (mainにマージ後は `main`)
   - **Main file path**: `app/dashboard.py`
4. (任意) LLM戦略を使う場合は「Advanced settings」→「Secrets」に以下を貼る:
   ```toml
   ANTHROPIC_API_KEY = "sk-ant-..."
   ```
5. 「Deploy」 → 数分後に `https://<アプリ名>.streamlit.app` が発行されます

**デプロイ時の自動処理:**

- 初回アクセス時、結果や価格データが無ければ**デモデータを自動生成**します
  (`app/dashboard.py` の `bootstrap_demo_data()` が実行)
- `runtime.txt` で Python 3.11、`requirements.txt` で依存を自動インストール
- `.streamlit/config.toml` でテーマ・サーバー設定を適用

**クラウド版の制約 (重要):**

| 項目 | 内容 |
|---|---|
| 永続化 | ファイルシステムが一時的なため、**設定変更・口座状態・実行結果は再起動で消えます** |
| 用途 | デモ・共有・閲覧向き。**継続的な日次/リアルタイム運用はローカルPC版を推奨** |
| リソース | 無料枠は 1GB RAM / CPU共有。全400銘柄バックテストは重い場合あり (銘柄数を絞る) |
| 公開範囲 | Public app は誰でもURLで閲覧可能。非公開にしたい場合は要 Streamlit 有料プラン |

> ❌ **共有レンタルサーバー (通常のXserver, さくらのレンタルサーバー等) では動きません。**
> Streamlit は Python の常駐プロセスと WebSocket が必要で、PHP向け共有ホスティングでは
> 起動できないためです。VPS (Xserver VPS等) なら nginx + systemd で公開可能です。

### 動作確認用のテストデータ

`scripts/generate_sample_results.py` で複数パターンのダミー結果を生成できます。

```bash
# デフォルト: 中程度の成績 (一部基準クリア)
python scripts/generate_sample_results.py

# 全パターン生成 (好成績/不振/平均) — 比較表示の確認に
python scripts/generate_sample_results.py --all
```

ダッシュボード起動後、サイドバーから複数の結果を切り替えて比較できます。
