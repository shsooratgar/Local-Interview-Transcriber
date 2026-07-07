@echo off
setlocal enabledelayedexpansion
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

REM --- pick the first audio file in the "audio" folder ---
set "AUDIO="
for %%F in (audio\*.mp3 audio\*.m4a audio\*.wav audio\*.mp4 audio\*.aac audio\*.flac audio\*.ogg audio\*.opus) do (
  if not defined AUDIO set "AUDIO=%%F"
)
REM --- pick the first transcript (.docx) in the "transcripts" folder ---
set "BASE="
for %%F in (transcripts\*.docx) do (
  if not defined BASE set "BASE=%%F"
)

if not defined AUDIO (
  echo [X] No audio file found in the "audio" folder.
  echo     Put ONE audio file there and try again.
  echo.
  pause
  exit /b 1
)
if not defined BASE (
  echo [X] No .docx transcript found in the "transcripts" folder.
  echo     Put ONE .docx there and try again.
  echo.
  pause
  exit /b 1
)

echo Found:
echo    audio:      !AUDIO!
echo    transcript: !BASE!
echo.
echo Working... For a long interview this can take a FEW HOURS on a laptop.
echo Please leave this window open and keep the laptop plugged in.
"%PY%" "app\pipeline.py" "!AUDIO!" --base "!BASE!"
if errorlevel 1 (
  echo.
  echo [X] Something went wrong above.
  echo.
  pause
  exit /b 1
)

echo.
echo Opening the review in your browser.
echo KEEP THIS WINDOW OPEN while you review -- it is what saves your changes.
echo When you are finished, just close this window.
echo.
"%PY%" "app\serve_review.py"
