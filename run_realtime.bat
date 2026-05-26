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
echo   準リアルタイム AI 売買 (5分ポーリング・20銘柄)
echo ===========================================================
echo.
echo 注意:
echo   - Yahoo Finance データは約15分遅延します
echo   - 営業時間 (9:00-11:30, 12:30-15:00 JST) のみ自動実行
echo   - 停止するには Ctrl+C を押してください
echo   - 仮想売買のためリアルマネーは動きません
echo.
echo 動作モード:
echo   1. 通常実行       (営業時間中ループ、口座を更新)
echo   2. dry-run        (判断だけ表示、口座は変更しない)
echo   3. force-run      (営業時間外でも実行、動作確認用)
echo   4. once           (1ティックだけ実行して終了)
echo   5. reset          (リアルタイム用仮想口座をリセット)
echo.
set /p choice="番号を入力 [1-5]: "

if "%choice%"=="1" python scripts\run_realtime.py
if "%choice%"=="2" python scripts\run_realtime.py --dry-run
if "%choice%"=="3" python scripts\run_realtime.py --force-run
if "%choice%"=="4" python scripts\run_realtime.py --once --force-run
if "%choice%"=="5" python scripts\run_realtime.py --reset

echo.
pause
