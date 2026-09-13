' Runs start_server.bat without a console window.
' A shortcut to this script named "MissenseReportServer" sits in the user's
' Startup folder (shell:startup), so the server starts at Windows logon.
' To stop the server, end the python.exe process that serves app.py
' (Task Manager), or run:  taskkill /F /IM python.exe  (kills every python).
Option Explicit
Dim fso, shell, here
Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")
here = fso.GetParentFolderName(WScript.ScriptFullName)
shell.Run "cmd.exe /c """ & here & "\start_server.bat""", 0, False
