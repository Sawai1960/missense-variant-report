@echo off
rem Launcher for the missense variant report tool. Double-click to start.
rem Closing this window stops the app.
rem (ASCII only: cmd reads batch files in the OEM code page, so Japanese text here would break.)
cd /d "%~dp0"
echo Starting the missense variant report tool...
echo A browser tab will open. Close this window to stop the app.
echo.
python -m streamlit run app.py --browser.gatherUsageStats false
if errorlevel 1 (
    echo.
    echo Failed to start. See the messages above.
    pause
)
