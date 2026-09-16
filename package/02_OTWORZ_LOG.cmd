@echo off
setlocal
set "LOCALLOG=%LOCALAPPDATA%\CourseArchiverInstaller\INSTALL_LOG.txt"
set "ROOTLOG=%~dp0INSTALL_LOG.txt"
if exist "%LOCALLOG%" (
  start "" notepad.exe "%LOCALLOG%"
  exit /b 0
)
if exist "%ROOTLOG%" (
  start "" notepad.exe "%ROOTLOG%"
  exit /b 0
)
echo Nie znaleziono jeszcze logu instalacji.
echo Uruchom najpierw 01_URUCHOM_INSTALACJE.cmd
pause
