#!/usr/bin/env pwsh
# PowerShell版セットアップスクリプト (setup.bat の代替)
# 実行方法: 右クリック → PowerShellで実行
# 実行ポリシーで弾かれた場合:
#   PowerShellを管理者で開き、以下を1回実行:
#   Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser

$ErrorActionPreference = "Stop"
$OutputEncoding = [Console]::OutputEncoding = [System.Text.Encoding]::UTF8

Write-Host "===========================================================" -ForegroundColor Cyan
Write-Host "  株式売買シミュレーション - Windows セットアップ" -ForegroundColor Cyan
Write-Host "===========================================================" -ForegroundColor Cyan
Write-Host ""

# Python 確認
$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) {
    Write-Host "[エラー] Python が見つかりません" -ForegroundColor Red
    Write-Host ""
    Write-Host "インストール手順:"
    Write-Host "  1. https://www.python.org/downloads/ から Python 3.12 をダウンロード"
    Write-Host "  2. インストール時に 'Add python.exe to PATH' にチェック"
    Write-Host "  3. PC再起動後に再実行"
    Read-Host "Enterで終了"
    exit 1
}

$pyver = (python --version) -replace "Python "
Write-Host "Python バージョン: $pyver"

$verCheck = python -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)"
if ($LASTEXITCODE -ne 0) {
    Write-Host "[エラー] Python 3.10 以上が必要です" -ForegroundColor Red
    Read-Host "Enterで終了"
    exit 1
}

# 仮想環境作成
if (-not (Test-Path ".venv")) {
    Write-Host "[1/4] 仮想環境を作成中..." -ForegroundColor Yellow
    python -m venv .venv
} else {
    Write-Host "[1/4] 仮想環境は既に存在します"
}

# 有効化
Write-Host "[2/4] 仮想環境を有効化..."
& ".venv\Scripts\Activate.ps1"

# パッケージインストール
Write-Host "[3/4] パッケージをインストール中... (5〜10分)" -ForegroundColor Yellow
python -m pip install --upgrade pip --quiet
pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) {
    Write-Host "[エラー] パッケージインストールに失敗" -ForegroundColor Red
    Read-Host "Enterで終了"
    exit 1
}

# デモデータ生成
Write-Host "[4/4] デモ用データを生成中..."
python scripts\generate_demo_prices.py
python scripts\generate_sample_results.py --all

Write-Host ""
Write-Host "===========================================================" -ForegroundColor Green
Write-Host "  セットアップ完了" -ForegroundColor Green
Write-Host "===========================================================" -ForegroundColor Green
Write-Host ""
Write-Host "次のステップ:"
Write-Host "  run_dashboard.bat  ダッシュボードを起動"
Write-Host "  run_live.bat       AIに当日の判断をさせる"
Write-Host "  run_backtest.bat   バックテスト実行"
Read-Host "Enterで終了"
