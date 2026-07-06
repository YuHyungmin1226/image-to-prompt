@echo off
echo ==========================================
echo Setting up Python Virtual Environment (venv)
echo ==========================================
python -m venv venv
if %errorlevel% neq 0 (
    echo [ERROR] Failed to create virtual environment. Please make sure Python is installed and added to PATH.
    pause
    exit /b %errorlevel%
)

echo.
echo Activating virtual environment...
call venv\Scripts\activate

echo.
echo Installing PyTorch with CUDA 12.1 support...
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu121
if %errorlevel% neq 0 (
    echo [ERROR] Failed to install PyTorch with CUDA.
    pause
    exit /b %errorlevel%
)

echo.
echo Installing other required packages...
pip install -r requirements.txt
if %errorlevel% neq 0 (
    echo [ERROR] Failed to install requirements.
    pause
    exit /b %errorlevel%
)

echo.
echo ==========================================
echo Setup complete successfully!
echo Use start_app.bat to launch the application.
echo ==========================================
pause
