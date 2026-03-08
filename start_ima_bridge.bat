@echo off
setlocal

set "PROJECT_ROOT=%~dp0"
cd /d "%PROJECT_ROOT%"

set "IMA_PYTHON=%USERPROFILE%\miniconda3\envs\ima\python.exe"
if not exist "%IMA_PYTHON%" set "IMA_PYTHON=%USERPROFILE%\anaconda3\envs\ima\python.exe"

if not exist "%IMA_PYTHON%" (
  echo.
  echo [ima] Cannot find python.exe in the ima environment.
  echo [ima] Please create it first: conda env create -f environment.yml
  echo.
  pause
  exit /b 1
)

set "PYTHONPATH=%PROJECT_ROOT%src"
set "HOST=127.0.0.1"
set "UI_PORT=8765"
set "WORKERS=10"

echo [ima] Starting UI at http://%HOST%:%UI_PORT% ^(workers=%WORKERS%^)
"%IMA_PYTHON%" -m ima_bridge ui --host %HOST% --ui-port %UI_PORT% --workers %WORKERS%
set "EXIT_CODE=%ERRORLEVEL%"

if not "%EXIT_CODE%"=="0" (
  echo.
  echo [ima] Startup failed. Check the output above.
  echo.
  pause
)

exit /b %EXIT_CODE%
