@echo off
cd /d "%~dp0"
echo ============================================================
echo   LOCAL TRANSCRIBER - ONE-TIME SETUP
echo.
echo   Installs Python, ffmpeg, Ollama and the AI models.
echo   Needs an internet connection. Takes about 15-40 minutes.
echo   You only need to do this ONCE.
echo.
echo   TIP: if it ever stops and says something was "not found",
echo   just close this window and double-click this file again.
echo ============================================================
echo.
pause

where winget >nul 2>&1
if errorlevel 1 (
  echo.
  echo [X] "winget" is not available on this PC.
  echo     Open the Microsoft Store, install "App Installer", then run this again.
  echo.
  pause
  exit /b 1
)

echo.
echo [1/5] Installing Python 3.11 ...
winget install -e --id Python.Python.3.11 --silent --accept-package-agreements --accept-source-agreements

echo.
echo [2/5] Installing ffmpeg ...
winget install -e --id Gyan.FFmpeg --silent --accept-package-agreements --accept-source-agreements

echo.
echo [3/5] Installing Ollama (the local AI engine) ...
winget install -e --id Ollama.Ollama --silent --accept-package-agreements --accept-source-agreements

echo.
echo [4/5] Setting up the Python environment ...
REM check for python.exe (not just the folder) so a half-created environment
REM from an earlier failed run is repaired instead of skipped forever
if not exist "app\.venv\Scripts\python.exe" (
  py -3.11 -m venv "app\.venv" 2>nul || python -m venv "app\.venv"
)
if not exist "app\.venv\Scripts\python.exe" (
  echo.
  echo [!] Python isn't on the PATH yet. Close this window and double-click
  echo     "1 - SETUP" one more time to finish.
  echo.
  pause
  exit /b 1
)
REM Use the environment's Python by full path -- NEVER "activate": activation
REM scripts hard-code the folder's original location and break if it is moved.
set "PY=%~dp0app\.venv\Scripts\python.exe"
"%PY%" -m pip install --upgrade pip
"%PY%" -m pip install -r "app\requirements-windows.txt"
if errorlevel 1 (
  echo.
  echo [X] Installing the Python packages failed (see above). Check your internet and re-run.
  echo.
  pause
  exit /b 1
)

echo.
echo [5/5] Downloading the AI models (the big download) ...
"%PY%" -c "from faster_whisper import WhisperModel; WhisperModel('large-v3'); print('speech model ready')"

where ollama >nul 2>&1
if errorlevel 1 (
  echo.
  echo [!] Ollama was just installed but isn't on the PATH yet.
  echo     Close this window and double-click "1 - SETUP" one more time to finish.
  echo.
  pause
  exit /b 1
)
REM the silent installer does not always start the Ollama service -- start it if needed
ollama list >nul 2>&1
if errorlevel 1 (
  start "" /MIN ollama serve
  timeout /t 5 /nobreak >nul
)
ollama pull qwen2.5:7b
if errorlevel 1 (
  echo.
  echo [X] Downloading the AI model failed. Check your internet and re-run this file.
  echo.
  pause
  exit /b 1
)

echo.
echo ============================================================
echo   ALL DONE. You can close this window.
echo.
echo   Next: put an audio file in the "audio" folder and a
echo   transcript (.docx) in the "transcripts" folder, then
echo   double-click "2 - PROCESS".
echo ============================================================
pause
