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
echo ダッシュボードを起動中...
echo ブラウザが自動で http://localhost:8501 を開きます
echo 終了するにはこのウィンドウで Ctrl+C を押してください
echo.

streamlit run app\dashboard.py
pause
