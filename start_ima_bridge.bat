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
set "LOGIN_TIMEOUT=180"
set "START_REASON=existing"
set "HEALTH_STATUS=ERROR"

call :run_health_check
if "%HEALTH_STATUS%"=="OK" goto start_ui
if "%HEALTH_STATUS%"=="AUTH" goto need_login

echo.
echo [ima] Health check failed. Check the output above.
echo.
pause
exit /b 1

:need_login
echo.
echo [ima] Login or target knowledge base confirmation is required.
echo [ima] Opening the login window now...
echo.
"%IMA_PYTHON%" -m ima_bridge login --timeout %LOGIN_TIMEOUT%
set "EXIT_CODE=%ERRORLEVEL%"

if not "%EXIT_CODE%"=="0" (
  echo.
  echo [ima] Login was not completed. UI will not start.
  echo.
  pause
  exit /b %EXIT_CODE%
)

echo.
echo [ima] Login succeeded. Verifying health again...
call :run_health_check
if "%HEALTH_STATUS%"=="OK" (
  set "START_REASON=after-login"
  goto start_ui
)

echo.
echo [ima] Health check still failed after login. UI will not start.
echo.
pause
exit /b 1

:start_ui
echo.
if /i "%START_REASON%"=="after-login" (
  echo [ima] Login completed. Starting UI at http://%HOST%:%UI_PORT% ^(workers=%WORKERS%^)
) else (
  echo [ima] Existing login is ready. Starting UI at http://%HOST%:%UI_PORT% ^(workers=%WORKERS%^)
)

"%IMA_PYTHON%" -m ima_bridge ui --host %HOST% --ui-port %UI_PORT% --workers %WORKERS%
set "EXIT_CODE=%ERRORLEVEL%"

if not "%EXIT_CODE%"=="0" (
  echo.
  echo [ima] Startup failed. Check the output above.
  echo.
  pause
)

exit /b %EXIT_CODE%

:run_health_check
set "HEALTH_STATUS=ERROR"
echo.
echo [ima] Running headless health check...
"%IMA_PYTHON%" -c "import sys; from ima_bridge.config import get_settings; from ima_bridge.service import IMAAskService; sys.stdout.reconfigure(encoding='utf-8'); result = IMAAskService(settings=get_settings(driver_mode='web')).health(); code = result.error_code or ''; label = code or 'NONE'; message = result.error_message or ''; print(f'[ima] Health result: ok={result.ok} code={label}'); message and print('[ima] ' + message); sys.exit(0 if result.ok else 10 if code in ('LOGIN_REQUIRED', 'KB_NOT_FOUND') else 20)"
set "HEALTH_EXIT=%ERRORLEVEL%"

if "%HEALTH_EXIT%"=="0" (
  set "HEALTH_STATUS=OK"
  exit /b 0
)

if "%HEALTH_EXIT%"=="10" (
  set "HEALTH_STATUS=AUTH"
  exit /b 0
)

set "HEALTH_STATUS=ERROR"
exit /b 0
