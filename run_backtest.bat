@echo off
chcp 65001 >nul
cd /d "%~dp0"

if not exist .venv (
    echo [エラー] 先に setup.bat を実行してください
    pause
    exit /b 1
)

call .venv\Scripts\activate.bat

echo ===========================================================
echo   バックテスト (過去データで戦略を検証)
echo ===========================================================
echo.
echo 戦略を選んでください:
echo   1. テクニカル (移動平均+RSI)  ★おすすめ
echo   2. 機械学習   (LightGBM)
echo   3. LLM        (Claude API、要 ANTHROPIC_API_KEY)
echo.
set /p choice="番号を入力 [1-3]: "
echo.
set /p limit="銘柄数を入力 (例: 20 で動作確認、空欄で全400銘柄): "

set ARGS=
if "%choice%"=="1" set ARGS=--strategy technical
if "%choice%"=="2" set ARGS=--strategy ml
if "%choice%"=="3" set ARGS=--strategy llm
if not "%limit%"=="" set ARGS=%ARGS% --limit %limit%

echo.
echo 実行コマンド: python scripts\run_backtest.py %ARGS%
echo.
python scripts\run_backtest.py %ARGS%

echo.
echo 結果は results\last_run.json に保存されました
echo run_dashboard.bat でブラウザから確認できます
echo.
pause
