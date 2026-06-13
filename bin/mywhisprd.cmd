@echo off
rem MyWhispr daemon launcher (Windows). Uses the repo-local venv.
setlocal
set ROOT=%~dp0..
"%ROOT%\.venv\Scripts\python.exe" -m mywhispr %*
endlocal
