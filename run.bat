@echo off
setlocal
cd /d "%~dp0"
title SICK MLS Operator

where py >nul 2>&1
if errorlevel 1 (
  echo Python-Launcher "py" wurde nicht gefunden.
  echo Bitte Python 3 von https://www.python.org/downloads/ installieren
  echo und beim Setup "Add python.exe to PATH" bzw. den py-Launcher aktivieren.
  goto :fail
)

if not exist ".venv\Scripts\python.exe" (
  echo Erstelle virtuelle Umgebung...
  py -3 -m venv .venv
  if errorlevel 1 goto :fail
  echo Installiere Abhaengigkeiten...
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt
  if errorlevel 1 goto :fail
)

echo.
echo Starte MLS Operator...
echo Das Fenster muss offen bleiben, solange die Oberflaeche laeuft.
echo.
".venv\Scripts\python.exe" run.py
if errorlevel 1 goto :fail
goto :eof

:fail
echo.
echo Start fehlgeschlagen. Dieses Fenster bleibt offen, damit du die Meldung lesen kannst.
pause
