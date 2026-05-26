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
echo   1. マルチAI合議制 (technical+ml+fundamental、課金なし) ★おすすめ
echo   2. テクニカル (移動平均+RSI、課金なし)
echo   3. 機械学習   (LightGBM、課金なし)
echo   4. ファンダメンタルズ (PER/PBR/ROE、課金なし)
echo   5. LLM        (Claude API使用、要 ANTHROPIC_API_KEY)
echo   6. dry-run    (合議制で判断だけ表示、口座は変更しない)
echo   7. reset      (仮想口座をリセット)
echo.
set /p choice="番号を入力 [1-7]: "

if "%choice%"=="1" python scripts\run_live.py --strategy ensemble
if "%choice%"=="2" python scripts\run_live.py --strategy technical
if "%choice%"=="3" python scripts\run_live.py --strategy ml
if "%choice%"=="4" python scripts\run_live.py --strategy fundamental
if "%choice%"=="5" python scripts\run_live.py --strategy llm
if "%choice%"=="6" python scripts\run_live.py --strategy ensemble --dry-run
if "%choice%"=="7" python scripts\run_live.py --reset

echo.
pause
