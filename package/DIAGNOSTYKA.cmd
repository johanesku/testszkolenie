@echo off
setlocal EnableExtensions
cd /d "%~dp0"
chcp 65001 >nul 2>nul
set "DLOG=%~dp0DIAGNOSTYKA_LOG.txt"
set "ILOG=%LOCALAPPDATA%\CourseArchiverInstaller\INSTALL_LOG.txt"

>"%DLOG%" echo Course Archiver - diagnostyka
>>"%DLOG%" echo Data: %DATE% %TIME%
>>"%DLOG%" echo Folder: %CD%
>>"%DLOG%" echo.
>>"%DLOG%" echo === SYSTEM ===
ver >>"%DLOG%" 2>&1
wmic os get Caption,Version,OSArchitecture  >>"%DLOG%" 2>&1
>>"%DLOG%" echo.
>>"%DLOG%" echo === PYTHON LAUNCHER ===
where py.exe >>"%DLOG%" 2>&1
py -0p >>"%DLOG%" 2>&1
>>"%DLOG%" echo.
>>"%DLOG%" echo === PYTHON PRIVATE ===
if exist "%LOCALAPPDATA%\CourseArchiverBuilder\Python312\python.exe" (
  "%LOCALAPPDATA%\CourseArchiverBuilder\Python312\python.exe" --version >>"%DLOG%" 2>&1
) else (
  >>"%DLOG%" echo brak
)
>>"%DLOG%" echo.
>>"%DLOG%" echo === CHROME ===
where chrome.exe >>"%DLOG%" 2>&1
if exist "%PROGRAMFILES%\Google\Chrome\Application\chrome.exe" "%PROGRAMFILES%\Google\Chrome\Application\chrome.exe" --version >>"%DLOG%" 2>&1
if exist "%PROGRAMFILES(X86)%\Google\Chrome\Application\chrome.exe" "%PROGRAMFILES(X86)%\Google\Chrome\Application\chrome.exe" --version >>"%DLOG%" 2>&1
>>"%DLOG%" echo.
>>"%DLOG%" echo === WINGET ===
where winget.exe >>"%DLOG%" 2>&1
winget.exe --version >>"%DLOG%" 2>&1
>>"%DLOG%" echo.
>>"%DLOG%" echo === INSTALATOR LOG ===
if exist "%ILOG%" type "%ILOG%" >>"%DLOG%" 2>&1

echo Diagnostyka zapisana w:
echo %DLOG%
start "" notepad.exe "%DLOG%"
pause
