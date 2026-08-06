@echo off
setlocal
cd /d "%~dp0"
if not defined LUMINAPROMPT_PORT set "LUMINAPROMPT_PORT=8088"
if not defined LUMINAPROMPT_HOST set "LUMINAPROMPT_HOST=0.0.0.0"
set "PORT=%LUMINAPROMPT_PORT%"
set "HOST=%LUMINAPROMPT_HOST%"
set "PYTHONUNBUFFERED=1"

echo ==========================================
echo Starting Image to Prompt Generator
echo ==========================================
call "%~dp0venv\Scripts\activate.bat"
if errorlevel 1 (
    echo [ERROR] Virtual environment not found. Please run setup_env.bat first!
    pause
    exit /b 1
)

for /f %%P in ('powershell -NoProfile -Command "$conn = Get-NetTCPConnection -LocalPort %PORT% -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty OwningProcess; if ($conn) { $conn }"') do set "PORT_IN_USE=%%P"
if defined PORT_IN_USE (
    echo [ERROR] Port %PORT% is already in use by PID %PORT_IN_USE%.
    echo [ERROR] Stop the existing process and run start_app.bat again.
    pause
    exit /b 1
)

if /I "%HOST%"=="0.0.0.0" (
    echo [INFO] Local URL:   http://localhost:%PORT%
    powershell -NoProfile -Command "$port=%PORT%; $ips = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue | Where-Object { $_.IPAddress -notlike '127.*' -and $_.IPAddress -notlike '169.254.*' } | Select-Object -ExpandProperty IPAddress -Unique; if ($ips) { foreach ($ip in $ips) { Write-Host ('[INFO] Network URL: http://' + $ip + ':' + $port) } } else { Write-Host '[INFO] Network URL: no active IPv4 address detected' }"
) else (
    if /I "%HOST%"=="::" (
        echo [INFO] Local URL:   http://localhost:%PORT%
        powershell -NoProfile -Command "$port=%PORT%; $ips = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue | Where-Object { $_.IPAddress -notlike '127.*' -and $_.IPAddress -notlike '169.254.*' } | Select-Object -ExpandProperty IPAddress -Unique; if ($ips) { foreach ($ip in $ips) { Write-Host ('[INFO] Network URL: http://' + $ip + ':' + $port) } } else { Write-Host '[INFO] Network URL: no active IPv4 address detected' }"
    ) else (
        if /I "%HOST%"=="127.0.0.1" (
            echo [INFO] Local URL:   http://localhost:%PORT%
        ) else (
            if /I "%HOST%"=="localhost" (
                echo [INFO] Local URL:   http://localhost:%PORT%
            ) else (
                echo [INFO] Bound URL:   http://%HOST%:%PORT%
            )
        )
    )
)
echo [INFO] Press Ctrl+C to stop the server.

python -m uvicorn main:app --host %HOST% --port %PORT%
if errorlevel 1 (
    echo [ERROR] Application crashed or failed to start.
    pause
)
