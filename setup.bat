@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

echo ===========================================================
echo   株式売買シミュレーション - Windows セットアップ
echo ===========================================================
echo.

REM === Python 確認 ===
where python >nul 2>nul
if errorlevel 1 (
    echo [エラー] Python が見つかりません
    echo.
    echo インストール手順:
    echo   1. https://www.python.org/downloads/ から Python 3.12 をダウンロード
    echo   2. インストーラ起動後、最下部の
    echo      "Add python.exe to PATH" に必ずチェックを入れる
    echo   3. インストール完了後、PCを一度再起動
    echo   4. このウィンドウを閉じて setup.bat を再実行
    echo.
    echo 詳しいインストール方法: README.md を参照
    pause
    exit /b 1
)

for /f "tokens=2" %%i in ('python --version 2^>^&1') do set PYVER=%%i
echo Python バージョン: !PYVER!
echo.

REM === Python バージョン確認 (3.10以上が必要) ===
python -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>nul
if errorlevel 1 (
    echo [エラー] Python 3.10 以上が必要です (現在: !PYVER!)
    echo https://www.python.org/downloads/ から最新版をインストールしてください
    pause
    exit /b 1
)

REM === 仮想環境作成 ===
if not exist .venv (
    echo [1/4] 仮想環境を作成中...
    python -m venv .venv
    if errorlevel 1 (
        echo [エラー] 仮想環境の作成に失敗
        pause
        exit /b 1
    )
) else (
    echo [1/4] 仮想環境は既に存在します (.venv)
)

REM === 仮想環境有効化 ===
echo [2/4] 仮想環境を有効化...
call .venv\Scripts\activate.bat

REM === パッケージインストール ===
echo [3/4] パッケージをインストール中... (初回は5〜10分かかります)
python -m pip install --upgrade pip --quiet
pip install -r requirements.txt
if errorlevel 1 (
    echo [エラー] パッケージインストールに失敗しました
    echo ネットワーク接続を確認してから再実行してください
    pause
    exit /b 1
)

REM === デモデータ生成 ===
echo [4/4] デモ用データを生成中...
python scripts\generate_demo_prices.py
if errorlevel 1 goto :skip_sample
python scripts\generate_sample_results.py --all
:skip_sample

echo.
echo ===========================================================
echo   セットアップ完了
echo ===========================================================
echo.
echo 次のステップ:
echo.
echo   [A] ダッシュボードを起動してサンプル結果を見る
echo       run_dashboard.bat  をダブルクリック
echo.
echo   [B] AIに当日の売買判断をさせる (ライブモード)
echo       run_live.bat       をダブルクリック
echo.
echo   [C] バックテスト (過去データで自動売買検証)
echo       run_backtest.bat   をダブルクリック
echo.
pause
