@echo off
:: ============================================================
::  NeTEx → EDIFACT Converter
:: ============================================================
::  1. Put NeTEx files in Source/
::  2. Double-click this file (or run: convert.bat)
::  3. Get EDIFACT output in Output/
:: ============================================================

cd /d "%~dp0"
python convert.py
if errorlevel 1 (
    echo.
    echo ERROR: Conversion failed. Check messages above.
)
echo.
pause
