@echo off
chcp 65001 >nul
cd /d "%~dp0"

if not exist "app\.venv\Scripts\python.exe" (
  echo [X] Not set up yet. Double-click "1 - SETUP (run once)" first.
  echo.
  pause
  exit /b 1
)
REM Use the environment's Python by full path -- NEVER "activate": activation
REM scripts hard-code the folder's original location and break if it is moved.
set "PY=%~dp0app\.venv\Scripts\python.exe"

REM --- make sure the local AI engine (Ollama) is running ---
where ollama >nul 2>&1
if not errorlevel 1 (
  ollama list >nul 2>&1
  if errorlevel 1 (
    echo Starting the local AI engine...
    start "" /MIN ollama serve
    timeout /t 5 /nobreak >nul
  )
)

echo Processes EVERY audio + transcript pair it can find, one after another.
echo   - with no argument: everything in the "audio" and "transcripts" folders
echo   - or drag a folder onto this file to process that folder instead
echo Files that were already processed are skipped automatically.
echo.
echo Checking the pairing first...
echo.
"%PY%" "app\batch.py" --dry-run %*
if errorlevel 1 (
  echo.
  echo [X] Something went wrong above.
  echo.
  pause
  exit /b 1
)

echo.
set /p CONFIRM=Process ALL of the above? This can run for many hours. [y/N]
if /i not "%CONFIRM%"=="y" (
  echo Cancelled. Nothing was processed.
  echo.
  pause
  exit /b 0
)

echo.
echo Working... leave this window open, keep the laptop PLUGGED IN, sleep set to Never.
echo.
"%PY%" "app\batch.py" %*
if errorlevel 1 (
  echo.
  echo [X] Something went wrong above.
  echo.
  pause
  exit /b 1
)

echo.
echo All done. Status sheet: output\data_log.xlsx
echo Opening the review in your browser. Use the list on the left of the page
echo to switch between the processed interviews.
echo KEEP THIS WINDOW OPEN while you review -- it is what saves your changes.
echo When you are finished, just close this window.
echo.
"%PY%" "app\serve_review.py"
