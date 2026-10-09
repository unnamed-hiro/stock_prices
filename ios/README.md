# StockAIViewer — iPhone で運用状況を確認するアプリ (SwiftUI)

AI株取引シミュレーターの運用状況を iPhone のネイティブアプリで確認します。

## 設計 — このアプリは「閲覧専用」です

```
GitHub Actions (毎営業日16:00 JST)          iPhone アプリ
  └─ AI判断 → JSON をリポジトリにコミット ──→ GitHub API で読んで表示するだけ
```

売買判断の頭脳は従来どおり GitHub Actions 上で動きます (月0円)。アプリは
リポジトリに蓄積された JSON (`data/state/portfolio.json`、`results/daily/`、
`results/monthly/`) を読み取って表示するだけで、**発注・変更機能は一切ありません**。
読み取り専用トークンしか持たないため、スマホを落としても資産は動かせません。

## 画面

| タブ | 内容 |
|---|---|
| 口座 | 評価額・リターン (積立入金補正済み)・資産推移グラフ・保有銘柄 |
| 日次 | 毎営業日のAI判断レポート (約定・翌日注文・見送り・レジーム) |
| 月次 | 月次成績表 (α・勝率・損益レシオ・リスク管理の発動実績) |
| 設定 | リポジトリ接続とトークン |

## ビルド手順 (Mac + Xcode が必要)

1. **Xcode 15 以降**をインストール (Mac App Store)
2. Xcode → **File → New → Project → iOS → App**
   - Product Name: `StockAIViewer` / Interface: **SwiftUI** / Language: **Swift**
3. プロジェクト生成後、テンプレートの `ContentView.swift` を**削除**
4. この `ios/StockAIViewer/` の **6つの .swift ファイル**をプロジェクトに
   ドラッグ&ドロップ (Copy items if needed にチェック)
5. プロジェクト設定 → General → **Minimum Deployments: iOS 17.0**
6. シミュレーターまたは実機を選んで **⌘R**

### 実機で使う場合の注意

- **無料の Apple ID**: 実機インストール可能だが**7日ごとに再ビルド**が必要
- **Apple Developer Program** (年間約15,000円): 期限なし + TestFlight 配布可
- 自分だけが使う閲覧アプリなら、無料IDで7日ごとに⌘Rするか、
  後述のPWA方式で十分です

### プライベートリポジトリの場合

アプリの設定タブでトークンを登録してください:
GitHub → Settings → Developer settings → **Fine-grained personal access tokens**
→ 対象リポジトリを `stock_prices` のみに限定 → 権限は **Contents: Read-only** のみ。

## ビルドなしの代替手段 (今日から使える)

Mac や Xcode がない場合は、**Streamlit ダッシュボードを iPhone の Safari で開き
「ホーム画面に追加」**してください。アイコンから起動するアプリとして使えます。
機能はこちらの方が多く (バックテスト実行等)、費用も0円です。
ネイティブアプリの利点は起動の速さと将来のプッシュ通知対応です。

## 既知の制約

- このコードは Linux 環境で作成したため **Xcode での実ビルド検証は未実施**です。
  コンパイルエラーが出た場合はエラーメッセージを共有してください (修正します)
- 株価は前営業日の終値ベース (リポジトリの更新は1日1回のため)
- GitHub API の無認証アクセスは 60回/時 の制限あり (トークン設定で5,000回/時)
