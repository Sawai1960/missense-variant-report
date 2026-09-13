@echo off
rem Server-mode launcher for the missense variant report tool.
rem Used by the scheduled task "MissenseReportServer" at Windows logon, and can
rem also be double-clicked to run the app without opening a browser.
rem Differences from the interactive launcher in the parent folder:
rem   - headless: no browser tab is opened
rem   - binds to 127.0.0.1 only: reachable from this PC and from cloudflared,
rem     never directly from the network
rem   - restarts automatically if the process exits
rem   - output goes to logs\server.log
rem (ASCII only: cmd reads batch files in the OEM code page.)
cd /d "%~dp0.."
if not exist logs mkdir logs
:loop
echo [%date% %time%] starting streamlit >> logs\server.log
python -m streamlit run app.py ^
    --server.headless true ^
    --server.address 127.0.0.1 ^
    --server.port 8501 ^
    --browser.gatherUsageStats false ^
    >> logs\server.log 2>&1
echo [%date% %time%] streamlit exited with code %errorlevel%; restarting in 10 s >> logs\server.log
timeout /t 10 /nobreak > nul
goto loop
