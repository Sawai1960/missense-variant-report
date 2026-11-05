@echo off
rem Launcher for the missense variant report tool. Double-click to start.
rem If the resident server (scripts/start_server.bat) is already running on
rem 127.0.0.1:8501, this only opens the browser and starts nothing new.
rem Otherwise it starts the app on 127.0.0.1:8501 only. It never listens on all
rem addresses, so the app is not reachable from the hospital LAN without login.
rem Closing this window stops an app that was started here.
rem (ASCII only: cmd reads batch files in the OEM code page, so Japanese text here would break.)
cd /d "%~dp0"
curl -sf -o nul --max-time 3 http://127.0.0.1:8501/_stcore/health
if not errorlevel 1 (
    echo The report tool is already running. Opening it in the browser...
    start "" http://localhost:8501
    exit /b 0
)
echo Starting the missense variant report tool...
echo A browser tab will open. Close this window to stop the app.
echo.
python -m streamlit run app.py --server.address 127.0.0.1 --server.port 8501 --browser.gatherUsageStats false
if errorlevel 1 (
    echo.
    echo Failed to start. See the messages above.
    pause
)
