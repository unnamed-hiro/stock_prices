@echo off
chcp 65001 >nul
cd /d "%~dp0"

if not exist .venv (
    echo [エラー] 先に setup.bat を実行してください
    pause
    exit /b 1
)

call .venv\Scripts\activate.bat

echo.
echo ===========================================================
echo   統合ダッシュボード (全機能Web操作)
echo ===========================================================
echo   ブラウザが自動で http://localhost:8501 を開きます
echo.
echo   利用可能なタブ:
echo     📊 結果ダッシュボード  既存の結果を閲覧
echo     ▶  バックテスト実行    戦略/銘柄数を選んで実行
echo     🤖 AI日次判断          1日分のAI判断を実行
echo     ⏱  準リアルタイム      5分ポーリングの売買 (1ティック実行)
echo     📁 生ログ              JSONログを直接閲覧
echo     ⚙  設定編集            config.yaml をブラウザから編集
echo.
echo   終了するにはこのウィンドウで Ctrl+C を押してください
echo ===========================================================

streamlit run app\dashboard.py
pause
