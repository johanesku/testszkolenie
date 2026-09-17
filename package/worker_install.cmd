@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"
title Course Archiver - instalacja automatyczna
chcp 65001 >nul 2>nul

set "APPNAME=Course Archiver and Transcriber"
set "VERSION=4.7.0"
set "ROOT=%~dp0"
set "LOGDIR=%LOCALAPPDATA%\CourseArchiverInstaller"
set "LOG=%LOGDIR%\INSTALL_LOG.txt"
set "ROOTLOG=%ROOT%INSTALL_LOG.txt"
set "BOOTLOG=%LOGDIR%\BOOTSTRAP_LOG.txt"
set "ROOTBOOTLOG=%ROOT%BOOTSTRAP_LOG.txt"
set "DESKTOPLOG=%USERPROFILE%\Desktop\CourseArchiver_INSTALL_LOG.txt"
set "PYPRIVATE=%LOCALAPPDATA%\CourseArchiverBuilder\Python312"
set "PYEXE="
set "PRIVATEPY=0"
set "PYSETUP=%TEMP%\CourseArchiver_python-3.12.10-amd64.exe"
set "PYURL=https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe"
set "TMPPY=%TEMP%\CourseArchiver_python_path.txt"

if not exist "%LOGDIR%" mkdir "%LOGDIR%" >nul 2>nul

if "%COURSEARCHIVER_STAGED%"=="1" (
  >>"%LOG%" echo ============================================================
  >>"%LOG%" echo Course Archiver and Transcriber - worker %VERSION%
) else (
  >"%LOG%" echo ============================================================
  >>"%LOG%" echo Course Archiver and Transcriber - installer %VERSION%
)
>>"%LOG%" echo Start: %DATE% %TIME%
>>"%LOG%" echo Folder: %ROOT%
>>"%LOG%" echo Windows: %OS%
>>"%LOG%" echo User: %USERNAME%
>>"%LOG%" echo ============================================================
copy /y "%LOG%" "%ROOTLOG%" >nul 2>nul

call :say "============================================================"
call :say "  Course Archiver and Transcriber"
call :say "  AUTOMATYCZNA INSTALACJA - wersja %VERSION%"
call :say "============================================================"
call :say ""
call :say "Nie musisz niczego instalowac recznie."
call :say "Instalator sprawdzi komputer i pobierze brakujace skladniki."
call :say "Pelny log jest tworzony OD PIERWSZEJ SEKUNDY instalacji."
call :say ""

rem ------------------------------------------------------------------
rem 1. Znajdz kompatybilny Python. Alias Microsoft Store jest ignorowany.
rem ------------------------------------------------------------------
call :say "[1/3] Sprawdzam Python 3.11/3.12..."
del /q "%TMPPY%" >nul 2>nul

where py.exe >>"%LOG%" 2>&1
if not errorlevel 1 (
  py -3.12 -c "import sys; print(sys.executable)" >"%TMPPY%" 2>>"%LOG%"
  if not errorlevel 1 set /p PYEXE=<"%TMPPY%"
  if not defined PYEXE (
    py -3.11 -c "import sys; print(sys.executable)" >"%TMPPY%" 2>>"%LOG%"
    if not errorlevel 1 set /p PYEXE=<"%TMPPY%"
  )
)

if not defined PYEXE if exist "%PYPRIVATE%\python.exe" set "PYEXE=%PYPRIVATE%\python.exe"
if not defined PYEXE if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" set "PYEXE=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if not defined PYEXE if exist "%LOCALAPPDATA%\Programs\Python\Python311\python.exe" set "PYEXE=%LOCALAPPDATA%\Programs\Python\Python311\python.exe"

if defined PYEXE (
  "%PYEXE%" -c "import sys; raise SystemExit(0 if sys.version_info[:2] in [(3,11),(3,12)] else 7)" >>"%LOG%" 2>&1
  if errorlevel 1 set "PYEXE="
)

if not defined PYEXE (
  call :say "Python nie jest zainstalowany. Pobieram prywatna kopie Python 3.12..."
  del /q "%PYSETUP%" >nul 2>nul

  where curl.exe >>"%LOG%" 2>&1
  if not errorlevel 1 (
    curl.exe -fL --retry 3 --retry-delay 2 --connect-timeout 30 -o "%PYSETUP%" "%PYURL%" >>"%LOG%" 2>&1
  ) else (
    call :say "curl.exe nie jest dostepny. Probuje certutil..."
    certutil.exe -urlcache -split -f "%PYURL%" "%PYSETUP%" >>"%LOG%" 2>&1
  )

  if not exist "%PYSETUP%" (
    call :say "Bezposrednie pobranie Python nie powiodlo sie. Probuje Windows Package Manager..."
    where winget.exe >>"%LOG%" 2>&1
    if not errorlevel 1 (
      winget.exe install --id Python.Python.3.12 -e --silent --accept-package-agreements --accept-source-agreements --disable-interactivity >>"%LOG%" 2>&1
      if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" set "PYEXE=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
    )
  )

  if not defined PYEXE if exist "%PYSETUP%" (
    if not exist "%PYPRIVATE%" mkdir "%PYPRIVATE%" >>"%LOG%" 2>&1
    call :say "Instaluje Python lokalnie dla tego instalatora..."
    "%PYSETUP%" /quiet InstallAllUsers=0 TargetDir="%PYPRIVATE%" PrependPath=0 Include_launcher=0 Include_test=0 Include_pip=1 Include_tcltk=1 Shortcuts=0 AssociateFiles=0 >>"%LOG%" 2>&1
    set "PYRC=%ERRORLEVEL%"
    if "!PYRC!"=="0" if exist "%PYPRIVATE%\python.exe" (
      set "PYEXE=%PYPRIVATE%\python.exe"
      set "PRIVATEPY=1"
    )
    if "!PYRC!"=="3010" if exist "%PYPRIVATE%\python.exe" (
      set "PYEXE=%PYPRIVATE%\python.exe"
      set "PRIVATEPY=1"
    )
  )
)

if not defined PYEXE (
  call :fail "Nie udalo sie zainstalowac ani znalezc Python 3.11/3.12."
  exit /b 10
)

"%PYEXE%" --version >>"%LOG%" 2>&1
if errorlevel 1 (
  call :fail "Python zostal znaleziony, ale nie daje sie uruchomic."
  exit /b 11
)
call :say "Python: OK"

rem ------------------------------------------------------------------
rem 2. Uruchom builder. Caly stdout/stderr laduje w tym samym logu.
rem ------------------------------------------------------------------
call :say "[2/3] Uruchamiam instalator skladnikow i budowe aplikacji..."
call :say "To moze potrwac kilkanascie lub kilkadziesiat minut."
call :say "Nie zamykaj tego okna."

rem Nie przekazujemy --root z wartoscia konczaca sie backslashem.
rem Na Windows sekwencja \" na koncu argumentu moze zostac zinterpretowana
rem przez parser argv jako escaped quote i skleic dwa argumenty.
rem Bootstrap sam ustala katalog z lokalizacji bootstrap.py, a sciezke logu
rem pobiera ze zmiennej srodowiskowej.
rem WAZNE: cmd.exe trzyma otwarty uchwyt do INSTALL_LOG.txt przez caly
rem czas dzialania bootstrap.py (przekierowanie stdout/stderr). Dlatego
rem Python zapisuje swoj logger do ODDZIELNEGO BOOTSTRAP_LOG.txt.
rem To usuwa WinError 13 / PermissionError wystepujacy w wersji 4.2.
del /q "%BOOTLOG%" >nul 2>nul
set "COURSEARCHIVER_INSTALL_LOG=%BOOTLOG%"
"%PYEXE%" "%ROOT%bootstrap.py" >>"%LOG%" 2>&1
set "RC=%ERRORLEVEL%"

rem Zawsze skopiuj oba logi do folderu paczki. INSTALL_LOG zawiera caly
rem stdout/stderr, a BOOTSTRAP_LOG jest niezaleznym logiem wewnetrznym.
copy /y "%LOG%" "%ROOTLOG%" >nul 2>nul
if exist "%BOOTLOG%" copy /y "%BOOTLOG%" "%ROOTBOOTLOG%" >nul 2>nul

if not "%RC%"=="0" (
  call :fail "Instalacja nie zakonczyla sie powodzeniem. Kod bledu: %RC%"
  exit /b %RC%
)

rem ------------------------------------------------------------------
rem 3. Sukces i sprzatanie.
rem ------------------------------------------------------------------
call :say "[3/3] Sprzatanie plikow tymczasowych..."
if "%PRIVATEPY%"=="1" rmdir /s /q "%PYPRIVATE%" >>"%LOG%" 2>&1
del /q "%PYSETUP%" "%TMPPY%" >nul 2>nul
copy /y "%LOG%" "%ROOTLOG%" >nul 2>nul
if exist "%BOOTLOG%" copy /y "%BOOTLOG%" "%ROOTBOOTLOG%" >nul 2>nul

call :say ""
call :say "============================================================"
call :say "  GOTOWE - aplikacja zostala zainstalowana."
call :say "============================================================"
call :say "Log instalacji pozostaje w folderze paczki jako INSTALL_LOG.txt."
call :say "Mozesz zamknac to okno."
call :say ""
pause
exit /b 0

:say
set "MSG=%~1"
if defined MSG (
  echo(!MSG!
  >>"%LOG%" echo(!MSG!
) else (
  echo(
  >>"%LOG%" echo(
)
exit /b 0

:fail
set "FAILMSG=%~1"
call :say ""
call :say "============================================================"
call :say "  BLAD INSTALACJI"
call :say "============================================================"
call :say "%FAILMSG%"
call :say ""
call :say "Log zostal zapisany w:"
call :say "%LOG%"
copy /y "%LOG%" "%ROOTLOG%" >nul 2>nul
if exist "%BOOTLOG%" copy /y "%BOOTLOG%" "%ROOTBOOTLOG%" >nul 2>nul
if exist "%USERPROFILE%\Desktop" copy /y "%LOG%" "%DESKTOPLOG%" >nul 2>nul
call :say ""
call :say "Kopia logu powinna byc tez w folderze paczki jako INSTALL_LOG.txt."
if exist "%USERPROFILE%\Desktop" call :say "Dodatkowa kopia: Pulpit\CourseArchiver_INSTALL_LOG.txt"
call :say "Otwieram log w Notatniku."
start "" notepad.exe "%LOG%"
pause
exit /b 1
