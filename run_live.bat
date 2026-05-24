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
echo   AIライブ売買 (本日分の判断と実行)
echo ===========================================================
echo.
echo 戦略を選んでください:
echo   1. テクニカル (移動平均+RSI、API課金なし) ★おすすめ
echo   2. 機械学習   (LightGBM、API課金なし)
echo   3. LLM        (Claude API使用、要 ANTHROPIC_API_KEY)
echo   4. dry-run    (判断だけ表示、口座は変更しない)
echo   5. reset      (仮想口座をリセット)
echo.
set /p choice="番号を入力 [1-5]: "

if "%choice%"=="1" python scripts\run_live.py --strategy technical
if "%choice%"=="2" python scripts\run_live.py --strategy ml
if "%choice%"=="3" python scripts\run_live.py --strategy llm
if "%choice%"=="4" python scripts\run_live.py --strategy technical --dry-run
if "%choice%"=="5" python scripts\run_live.py --reset

echo.
pause
