"""Spójność wersji i konfiguracji logów wewnątrz paczki instalacyjnej."""

from pathlib import Path
import ast

ROOT = Path(__file__).resolve().parents[1]
VERSION = "4.7.0"

boot = (ROOT / "bootstrap.py").read_text(encoding="utf-8")
cmd = (ROOT / "worker_install.cmd").read_text(encoding="utf-8")
iss = (ROOT / "installer" / "CourseArchiver.iss").read_text(encoding="utf-8")
ver = (ROOT / "src" / "VERSION.txt").read_text(encoding="utf-8").strip()

ast.parse(boot, filename="bootstrap.py")
assert f'APP_VERSION = "{VERSION}"' in boot
assert f'set "VERSION={VERSION}"' in cmd
assert f'#define MyAppVersion "{VERSION}"' in iss
assert f'VersionInfoVersion={VERSION}.0' in iss
assert ver == VERSION

# Regression: NEVER point the Python logger to the same file used by cmd.exe
# for the child's stdout/stderr redirection.
assert 'set "COURSEARCHIVER_INSTALL_LOG=%BOOTLOG%"' in cmd
assert 'set "COURSEARCHIVER_INSTALL_LOG=%LOG%"' not in cmd
assert '>>"%LOG%" 2>&1' in cmd
assert 'BOOTSTRAP_LOG.txt' in cmd
assert 'INSTALL_LOG.txt' in cmd

# Regression: bootstrap must expect exactly what Inno will generate.
assert 'CourseArchiver_Setup_{APP_VERSION}.exe' in boot
assert 'OutputBaseFilename=CourseArchiver_Setup_{#MyAppVersion}' in iss

# Logger fallback should exist, so logging alone cannot abort the install.
assert 'CourseArchiver_BOOTSTRAP_' in boot
assert 'tempfile.gettempdir()' in boot

# Regresja 4.6: znika stare, ślepe ponowne użycie EXE po numerze wersji katalogu
# (try_reuse_previous_build), które wgrywało nieaktualny kod. 4.7 używa cache
# opartego na hashu źródeł+wersji, więc nigdy nie przywróci nieaktualnego pliku.
assert 'try_reuse_previous_build' not in boot
assert 'build_binaries(log, py, root, manifest, manifest_path)' in boot

# Nowy wspolny modul musi byc wymagany i dolaczony do obu plikow EXE.
assert 'root / "src" / "session_events.py"' in boot
assert boot.count('"--hidden-import", "session_events"') == 2

# Regresja 4.6.4: Smart App Control blokuje niepodpisany Setup.exe (WinError 4551).
# Instalator musi to obsluzyc trybem przenosnym, a nie crashowac tracebackiem.
assert "APP_CONTROL_WINERRORS" in boot
assert "4551" in boot
assert "def portable_install(" in boot
assert "def wire_native_messaging(" in boot
assert "except OSError as e:" in boot  # przechwycenie blokady CreateProcess

# 4.7.0: inkrementalna budowa i wdrożenie oparte na hashach komponentów.
assert "def component_hash(" in boot
assert "def build_binaries(log: Logger, py: Path, root: Path, manifest: dict" in boot
assert "def deploy_incrementally(" in boot
assert "build_manifest.json" in boot
assert ".install_manifest.json" in boot
# Cache budowy i venv żyją poza staging, żeby przetrwać między uruchomieniami.
assert "def build_cache_dir(" in boot
assert 'shutil.rmtree(p, ignore_errors=True)' in boot
print("PASS Smart App Control -> tryb przenośny; inkrementalna budowa/wdrożenie")

print("PASS installer version consistency", VERSION)
print("PASS separate cmd/bootstrap log files")
print("PASS logger fallback")
print("PASS budowa oparta na hashu (bez ślepego reuse po numerze wersji)")
