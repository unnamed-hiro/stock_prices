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

### 方法A: Xcodeから直接クローン (最速・推奨)

Xcodeプロジェクトファイルを同梱しているため、クローンするだけでビルドできます。

1. **Xcode 15 以降**をインストール (Mac App Store)
2. Xcode起動画面の **「Clone Git Repository...」** をクリック
   (既にXcodeを開いている場合は メニュー Integrate → Clone...)
3. URL欄に `https://github.com/unnamed-hiro/stock_prices.git` を入力 → **Clone**
   - プライベートリポジトリの場合、先に Xcode → Settings → **Accounts** →
     「+」→ GitHub でサインインしておく (パスワード欄には Personal Access Token)
4. クローン後、Finderで保存先の `ios/StockAIViewer.xcodeproj` を**ダブルクリック**
   (クローン直後にXcodeがリポジトリ全体を開いた場合は一度閉じてよい)
5. 左上の青いプロジェクトアイコン → **Signing & Capabilities** タブ →
   **Team** に自分のApple IDを選択
   - 「Failed to register bundle identifier」エラーが出たら
     **Bundle Identifier** の `com.example.StockAIViewer` を
     `com.あなたの名前.StockAIViewer` などに変更
6. 上部のデバイス選択で **iPhoneシミュレーター** を選び **⌘R**

### 方法B: 手動でプロジェクトを作る (方法Aで問題が出た場合)

1. Xcode → **File → New → Project → iOS → App**
   - Product Name: `StockAIViewer` / Interface: **SwiftUI** / Language: **Swift**
2. テンプレートの `ContentView.swift` を**削除** (Move to Trash)
3. この `ios/StockAIViewer/` の **7つの .swift ファイル**をプロジェクトに
   ドラッグ&ドロップ (Copy items if needed にチェック)
4. General → **Minimum Deployments: iOS 17.0** に設定
5. シミュレーターまたは実機を選んで **⌘R**

### ホーム画面ウィジェット (任意)

アプリを開かずに評価額とリターンをホーム画面で確認できます:

1. Xcode → **File → New → Target... → iOS → Widget Extension**
   - Product Name: `StockWidget` / 「Include Configuration App Intent」の**チェックを外す**
2. 生成された `StockWidget.swift` の中身を、リポジトリの
   `ios/Widget/StockWidget.swift` の内容で**全て置き換える**
3. プライベートリポジトリの場合のみ: アプリとWidgetの両ターゲットの
   Signing & Capabilities に **App Groups** (`group.stockaiviewer`) を追加し、
   アプリの設定タブで「接続テスト」を一度実行 (設定がウィジェットへ共有される)
4. ⌘R 後、ホーム画面を長押し → 「+」 → StockWidget を追加

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
