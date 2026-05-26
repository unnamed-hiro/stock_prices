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
echo   本日トレードシミュレーション
echo ===========================================================
echo   その日の1分足を寄り付きから引けまで再生し、
echo   AIが分単位で売買したらどうなるかを一気に再現します。
echo   (引け後の実行がおすすめ / 1分足は直近7日まで)
echo.
echo モード:
echo   1. 本日を1分ごとに判断      (標準)
echo   2. 本日を5分ごとに判断      (高速)
echo   3. 引けで手仕舞いせず持ち越し
echo.
set /p choice="番号を入力 [1-3]: "

if "%choice%"=="1" python scripts\run_intraday.py
if "%choice%"=="2" python scripts\run_intraday.py --step 5
if "%choice%"=="3" python scripts\run_intraday.py --hold

echo.
echo 結果は run_dashboard.bat の「本日シミュレーション」タブでも確認できます
pause
