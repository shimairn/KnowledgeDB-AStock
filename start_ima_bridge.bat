@echo off
setlocal

python -m ima_bridge --driver web start %*
set EXIT_CODE=%ERRORLEVEL%

if not "%EXIT_CODE%"=="0" (
  echo.
  echo startup failed, check the JSON error output above.
)

exit /b %EXIT_CODE%

