@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  py -3 -m venv .venv || goto :failed
)
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -r requirements.txt || goto :failed
".venv\Scripts\python.exe" browser.py || goto :failed
exit /b 0
:failed
echo Traceleaf could not start. Install 64-bit Python 3.12 or 3.13 and review the error above.
pause
exit /b 1
