@echo off
echo ==========================================
echo Starting Image to Prompt Generator
echo ==========================================
call venv\Scripts\activate
if %errorlevel% neq 0 (
    echo [ERROR] Virtual environment not found. Please run setup_env.bat first!
    pause
    exit /b %errorlevel%
)

python main.py
if %errorlevel% neq 0 (
    echo [ERROR] Application crashed or failed to start.
    pause
)
