@echo off
setlocal
cd /d "%~dp0"

if /I "%~1"=="--run" goto run_main

set "LOGFILE=%~dp0setup_env_last_run.log"
del "%LOGFILE%" 2>nul

echo ==========================================
echo Running setup_env.bat
echo Log file: %LOGFILE%
echo ==========================================
echo.

cmd /d /v:off /c ""%~f0" --run" > "%LOGFILE%" 2>&1
set "SETUP_EXITCODE=%ERRORLEVEL%"

type "%LOGFILE%"
echo.
echo ==========================================
if %SETUP_EXITCODE% neq 0 (
    echo Setup failed with exit code %SETUP_EXITCODE%.
) else (
    echo Setup finished successfully.
)
echo Full log saved to:
echo %LOGFILE%
echo ==========================================
pause
exit /b %SETUP_EXITCODE%

:run_main
setlocal
cd /d "%~dp0"

set "LLAMA_CPP_VERSION=0.3.34"
set "LLAMA_CPP_CUDA_INDEX_URL=https://abetlen.github.io/llama-cpp-python/whl/cu118"
set "VENV_PYTHON=%CD%\venv\Scripts\python.exe"
set "VS_INSTALL="
set "VS_BUILD_TOOLS_X86=C:\PROGRA~2\Microsoft Visual Studio\2022\BuildTools"
set "VS_BUILD_TOOLS_X64=C:\PROGRA~1\Microsoft Visual Studio\2022\BuildTools"

if exist "%VS_BUILD_TOOLS_X86%\VC\Auxiliary\Build\vcvars64.bat" set "VS_INSTALL=%VS_BUILD_TOOLS_X86%"
if not defined VS_INSTALL if exist "%VS_BUILD_TOOLS_X64%\VC\Auxiliary\Build\vcvars64.bat" set "VS_INSTALL=%VS_BUILD_TOOLS_X64%"

for /f %%P in ('powershell -NoProfile -Command "$venv = [System.IO.Path]::GetFullPath($env:VENV_PYTHON); $proc = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object { $_.ExecutablePath -and [System.IO.Path]::GetFullPath($_.ExecutablePath) -ieq $venv } | Select-Object -First 1 -ExpandProperty ProcessId; if ($proc) { $proc }"') do set "VENV_IN_USE_PID=%%P"
if defined VENV_IN_USE_PID (
    echo [ERROR] The project's virtual environment is currently in use by PID %VENV_IN_USE_PID%.
    echo [INFO] Stop the running app or any Python process using this venv, then run setup_env.bat again.
    exit /b 1
)

echo ==========================================
echo Setting up Python Virtual Environment (venv)
echo ==========================================
if exist "%VENV_PYTHON%" (
    echo [INFO] Existing virtual environment detected. Reusing .\venv
) else (
    python -m venv venv
    if errorlevel 1 (
        echo [ERROR] Failed to create virtual environment. Please make sure Python is installed and added to PATH.
        exit /b 1
    )
)

echo.
echo Activating virtual environment...
call venv\Scripts\activate.bat
if errorlevel 1 (
    echo [ERROR] Failed to activate virtual environment.
    exit /b 1
)

echo.
echo Upgrading pip...
python -m pip install --upgrade pip
if errorlevel 1 (
    echo [ERROR] Failed to upgrade pip.
    exit /b 1
)

echo.
echo Installing FastAPI and shared runtime dependencies...
pip install -r requirements.txt
if errorlevel 1 (
    echo [ERROR] Failed to install requirements.
    exit /b 1
)

echo.
echo Checking Visual Studio C++ Build Tools...
if not defined VS_INSTALL (
    echo [ERROR] Visual Studio C++ Build Tools were not found.
    echo [INFO] Install Visual Studio 2022 Build Tools and include Desktop development with C++.
    exit /b 1
)

if not exist "%VS_INSTALL%\VC\Auxiliary\Build\vcvars64.bat" (
    echo [ERROR] vcvars64.bat was not found under:
    echo %VS_INSTALL%
    echo [INFO] Repair or reinstall Visual Studio 2022 Build Tools.
    exit /b 1
)

echo [INFO] Loading MSVC build environment...
cmd /d /c ""%VS_INSTALL%\VC\Auxiliary\Build\vcvars64.bat" && where cl >nul 2>nul && where nmake >nul 2>nul"
if errorlevel 1 (
    echo [ERROR] Failed to initialize the Visual Studio build environment or locate cl.exe/nmake.exe.
    exit /b 1
)

echo.
echo Checking CUDA toolkit...
where nvcc >nul 2>nul
if errorlevel 1 (
    echo [ERROR] nvcc.exe was not found in PATH.
    echo [INFO] Install NVIDIA CUDA Toolkit 11.8 or newer, then open a new terminal and run setup_env.bat again.
    exit /b 1
)

for /f "tokens=*" %%I in ('where nvcc') do (
    echo [INFO] Using CUDA compiler: %%I
    goto :cuda_found
)
:cuda_found

echo.
echo Installing llama-cpp-python CUDA wheel...
pip install --upgrade --force-reinstall --no-cache-dir llama-cpp-python==%LLAMA_CPP_VERSION% --extra-index-url %LLAMA_CPP_CUDA_INDEX_URL%
if errorlevel 1 (
    echo [ERROR] Failed to install the llama-cpp-python CUDA wheel.
    echo [INFO] Confirm CUDA 11.8 is installed and reachable as nvcc.exe, then run setup_env.bat again.
    exit /b 1
)

echo.
echo ==========================================
echo Setup complete successfully!
echo Use start_app.bat to launch the application.
echo The Gemma model files will download automatically on first launch.
echo They will be stored under your Documents\LLM-Models folder.
echo If you want a different model folder, set LUMINAPROMPT_MODELS_DIR before the first launch.
echo ==========================================
exit /b 0
