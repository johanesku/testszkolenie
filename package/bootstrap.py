from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
import traceback
from pathlib import Path

APP_NAME = "Course Archiver & Transcriber"
APP_VERSION = "4.7.0"
MIN_FREE_GB = 8
PYINSTALLER_REQ = "pyinstaller>=6.10,<7"

CHROME_URL = "https://dl.google.com/chrome/install/latest/chrome_installer.exe"
INNO_URL = "https://jrsoftware.org/download.php/is.exe"
VCREDIST_URL = "https://aka.ms/vs/17/release/vc_redist.x64.exe"

EXTENSION_ID = "dfmedhencldblnhceamhppjklgomoffk"

# Windows Smart App Control / WDAC blokuje niepodpisane pliki EXE bez reputacji.
# CreateProcess zwraca wtedy WinError 4551 ("Zasady kontroli aplikacji zablokowaly
# ten plik"). To zabezpieczenie systemu, nie blad instalatora.
APP_CONTROL_WINERRORS = {4551}
APP_CONTROL_HINT = (
    "Smart App Control (Windows 11) zablokowal uruchomienie swiezo zbudowanego, "
    "niepodpisanego pliku. To zabezpieczenie systemu, nie blad aplikacji."
)


class InstallerError(RuntimeError):
    pass


def now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


class Logger:
    def __init__(self, path: Path):
        # Logger Pythona MUSI używać osobnego pliku niż plik, do którego
        # cmd.exe przekierowuje stdout/stderr procesu. Na Windows uchwyt
        # przekierowania może blokować równoległe otwarcie tego samego pliku.
        # Dodatkowy fallback sprawia, że nawet antywirus / synchronizacja /
        # przypadkowa blokada logu nie zatrzyma instalatora na samym logowaniu.
        preferred = Path(path)
        candidates = [
            preferred,
            Path(tempfile.gettempdir()) / f"CourseArchiver_BOOTSTRAP_{os.getpid()}.log",
        ]
        last_error = None
        for candidate in candidates:
            try:
                candidate.parent.mkdir(parents=True, exist_ok=True)
                mode = "a" if candidate.exists() else "w"
                with candidate.open(mode, encoding="utf-8") as f:
                    if mode == "a":
                        f.write("\n")
                    f.write(f"{APP_NAME} bootstrap {APP_VERSION}\nStart: {now()}\n\n")
                self.path = candidate
                if candidate != preferred:
                    print(f"[WARN] Glowny log bootstrap byl niedostepny: {preferred}", flush=True)
                    print(f"[WARN] Uzywam logu awaryjnego: {candidate}", flush=True)
                return
            except OSError as e:
                last_error = e
        raise InstallerError(f"Nie udalo sie utworzyc logu bootstrap. Ostatni blad: {last_error}")

    def line(self, text: str = ""):
        print(text, flush=True)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(text + "\n")

    def command(self, cmd):
        display = subprocess.list2cmdline([str(x) for x in cmd]) if isinstance(cmd, (list, tuple)) else str(cmd)
        self.line(f"$ {display}")


def run(log: Logger, cmd, *, cwd: Path | None = None, check: bool = True, env=None, capture=False):
    log.command(cmd)
    p = subprocess.run(
        [str(x) for x in cmd],
        cwd=str(cwd) if cwd else None,
        env=env,
        text=True,
        capture_output=capture,
        errors="replace",
    )
    if capture:
        if p.stdout:
            log.line(p.stdout.rstrip())
        if p.stderr:
            log.line(p.stderr.rstrip())
    if check and p.returncode != 0:
        raise InstallerError(f"Polecenie zakonczylo sie kodem {p.returncode}: {cmd[0]}")
    return p


def stage(log: Logger, n: int, total: int, title: str):
    log.line()
    log.line("=" * 68)
    log.line(f"[{n}/{total}] {title}")
    log.line("=" * 68)


def download(log: Logger, url: str, target: Path):
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".part")
    if tmp.exists():
        tmp.unlink()
    log.line(f"Pobieranie: {url}")
    req = urllib.request.Request(url, headers={"User-Agent": "CourseArchiverInstaller/4.6"})
    try:
        with urllib.request.urlopen(req, timeout=60) as src, tmp.open("wb") as dst:
            total = int(src.headers.get("Content-Length") or 0)
            done = 0
            last_pct = -1
            while True:
                chunk = src.read(1024 * 1024)
                if not chunk:
                    break
                dst.write(chunk)
                done += len(chunk)
                if total:
                    pct = int(done * 100 / total)
                    if pct // 10 != last_pct // 10:
                        print(f"  ... {pct}%", flush=True)
                        last_pct = pct
        tmp.replace(target)
    except Exception as e:
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass
        raise InstallerError(f"Nie udalo sie pobrac {url}: {e}") from e
    if not target.exists() or target.stat().st_size < 50_000:
        raise InstallerError(f"Pobrany plik wyglada na uszkodzony: {target}")
    log.line(f"Pobrano: {target.name} ({target.stat().st_size / 1024 / 1024:.1f} MB)")


def winget() -> str | None:
    return shutil.which("winget") or shutil.which("winget.exe")


def install_winget_package(log: Logger, package_id: str) -> bool:
    wg = winget()
    if not wg:
        return False
    log.line(f"Probuje automatyczna instalacje przez Windows Package Manager: {package_id}")
    p = run(
        log,
        [wg, "install", "--id", package_id, "-e", "--silent", "--accept-package-agreements", "--accept-source-agreements", "--disable-interactivity"],
        check=False,
    )
    return p.returncode == 0


def chrome_candidates() -> list[Path]:
    vals = []
    for env_name in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
        base = os.environ.get(env_name)
        if base:
            vals.append(Path(base) / "Google" / "Chrome" / "Application" / "chrome.exe")
    return vals


def find_chrome() -> Path | None:
    for p in chrome_candidates():
        if p.exists():
            return p
    return None


def ensure_chrome(log: Logger, cache: Path) -> Path:
    existing = find_chrome()
    if existing:
        log.line(f"Google Chrome: OK ({existing})")
        return existing
    log.line("Google Chrome: brak - zostanie zainstalowany automatycznie.")
    install_winget_package(log, "Google.Chrome")
    existing = find_chrome()
    if existing:
        return existing
    setup = cache / "chrome_installer.exe"
    download(log, CHROME_URL, setup)
    run(log, [setup, "/silent", "/install"], check=True)
    time.sleep(2)
    existing = find_chrome()
    if not existing:
        raise InstallerError("Chrome zostal uruchomiony do instalacji, ale nie znaleziono chrome.exe po instalacji.")
    return existing


def inno_candidates() -> list[Path]:
    vals = []
    pf86 = os.environ.get("PROGRAMFILES(X86)")
    pf = os.environ.get("PROGRAMFILES")
    la = os.environ.get("LOCALAPPDATA")
    if pf86:
        vals.append(Path(pf86) / "Inno Setup 6" / "ISCC.exe")
    if pf:
        vals.append(Path(pf) / "Inno Setup 6" / "ISCC.exe")
    if la:
        vals.append(Path(la) / "Programs" / "Inno Setup 6" / "ISCC.exe")
    return vals


def find_inno() -> Path | None:
    for p in inno_candidates():
        if p.exists():
            return p
    return None


def ensure_inno(log: Logger, cache: Path) -> Path:
    existing = find_inno()
    if existing:
        log.line(f"Inno Setup 6: OK ({existing})")
        return existing
    log.line("Inno Setup 6: brak - zostanie zainstalowany automatycznie.")
    install_winget_package(log, "JRSoftware.InnoSetup")
    existing = find_inno()
    if existing:
        return existing
    setup = cache / "innosetup.exe"
    download(log, INNO_URL, setup)
    # /CURRENTUSER avoids an unnecessary admin prompt for the compiler itself.
    run(log, [setup, "/CURRENTUSER", "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/SP-"], check=True)
    existing = find_inno()
    if not existing:
        raise InstallerError("Inno Setup nie zostal znaleziony po automatycznej instalacji.")
    return existing


def has_vcredist() -> bool:
    if os.name != "nt":
        return True
    try:
        import winreg
        paths = [
            r"SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64",
            r"SOFTWARE\WOW6432Node\Microsoft\VisualStudio\14.0\VC\Runtimes\x64",
        ]
        for key_path in paths:
            try:
                with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key_path) as key:
                    val, _ = winreg.QueryValueEx(key, "Installed")
                    if int(val) == 1:
                        return True
            except OSError:
                pass
    except Exception:
        pass
    return False


def ensure_vcredist(log: Logger, cache: Path):
    if has_vcredist():
        log.line("Microsoft Visual C++ Runtime x64: OK")
        return
    log.line("Microsoft Visual C++ Runtime x64: brak - zostanie zainstalowany automatycznie.")
    if install_winget_package(log, "Microsoft.VCRedist.2015+.x64") and has_vcredist():
        return
    setup = cache / "vc_redist.x64.exe"
    download(log, VCREDIST_URL, setup)
    p = run(log, [setup, "/install", "/quiet", "/norestart"], check=False)
    # 0 = installed, 1638 = newer/equivalent version already present, 3010 = restart recommended.
    if p.returncode not in (0, 1638, 3010):
        raise InstallerError(f"Instalacja Microsoft Visual C++ Runtime zwrocila kod {p.returncode}.")
    log.line("Microsoft Visual C++ Runtime: OK")


def check_platform(log: Logger, root: Path):
    if os.name != "nt":
        raise InstallerError("Ten instalator jest przeznaczony wylacznie dla Windows 10/11.")
    if platform.machine().lower() not in {"amd64", "x86_64", "arm64"}:
        raise InstallerError(f"Nieobslugiwana architektura systemu: {platform.machine()}")
    free = shutil.disk_usage(root).free / 1024**3
    log.line(f"Windows: {platform.platform()}")
    log.line(f"Architektura: {platform.machine()}")
    log.line(f"Wolne miejsce: {free:.1f} GB")
    if free < MIN_FREE_GB:
        raise InstallerError(f"Potrzeba co najmniej {MIN_FREE_GB} GB wolnego miejsca na czas budowy aplikacji.")
    # Quick Internet/TLS check against a site that the build actually needs.
    try:
        with urllib.request.urlopen("https://pypi.org/simple/pip/", timeout=15) as r:
            if getattr(r, "status", 200) >= 400:
                raise OSError(f"HTTP {r.status}")
        log.line("Polaczenie z Internetem/TLS: OK")
    except Exception as e:
        raise InstallerError(f"Brak dostepu do Internetu wymaganego do pobrania skladnikow: {e}") from e


# -------------------------------------------------------------------------
# Inkrementalna budowa: komponent przebudowujemy tylko, gdy zmienil sie jego
# kod zrodlowy, zaleznosci albo wersja aplikacji. Wynik jest cache'owany w
# stabilnym katalogu i przywracany, gdy nic sie nie zmienilo - to skraca
# kolejne uruchomienia z kilkudziesieciu minut do sekund.
# -------------------------------------------------------------------------

def builder_root() -> Path:
    return Path(os.environ.get("LOCALAPPDATA", tempfile.gettempdir())) / "CourseArchiverBuilder"


def build_cache_dir() -> Path:
    return builder_root() / "cache"


def build_venv_dir() -> Path:
    return builder_root() / "buildvenv"


def hash_files(paths) -> str:
    h = hashlib.sha256()
    for p in sorted((Path(x) for x in paths), key=str):
        h.update(p.name.encode("utf-8"))
        h.update(b"\0")
        h.update(p.read_bytes() if p.exists() else b"<brak>")
    return h.hexdigest()


def hash_tree(directory: Path) -> str:
    h = hashlib.sha256()
    for p in sorted(directory.rglob("*"), key=lambda x: x.relative_to(directory).as_posix()):
        if p.is_file():
            h.update(p.relative_to(directory).as_posix().encode("utf-8"))
            h.update(b"\0")
            h.update(p.read_bytes())
    return h.hexdigest()


def load_manifest(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_manifest(path: Path, data: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def deps_signature(root: Path) -> str:
    return hash_files([root / "src" / "requirements.txt"]) + ":" + hashlib.sha256(PYINSTALLER_REQ.encode()).hexdigest()[:12]


def component_specs(root: Path) -> list[dict]:
    src = root / "src"
    return [
        {
            "name": "CourseArchiver", "dist_subdir": "CourseArchiver", "exe": "CourseArchiver.exe", "deps": True,
            "sources": [src / "app.pyw", src / "session_events.py"],
            "args": ["--onedir", "--windowed", "--name", "CourseArchiver",
                     "--paths", src, "--hidden-import", "session_events",
                     "--collect-all", "mss", "--collect-all", "soundcard", src / "app.pyw"],
        },
        {
            "name": "CourseArchiverAgent", "dist_subdir": "CourseArchiverAgent", "exe": "CourseArchiverAgent.exe", "deps": True,
            "sources": [src / "agent_generic.py", src / "session_events.py"],
            "args": ["--onedir", "--console", "--name", "CourseArchiverAgent",
                     "--paths", src, "--hidden-import", "session_events",
                     "--collect-all", "playwright", "--collect-all", "faster_whisper", "--collect-all", "ctranslate2",
                     "--collect-all", "tokenizers", "--collect-all", "huggingface_hub", "--collect-all", "imageio_ffmpeg",
                     "--collect-all", "soundcard", "--collect-all", "mss", "--collect-all", "av", src / "agent_generic.py"],
        },
        {
            "name": "NativeHost", "dist_subdir": "NativeHost", "exe": "CourseArchiverNativeHost.exe", "deps": False,
            "sources": [src / "native_host.py"],
            "args": ["--onefile", "--console", "--name", "CourseArchiverNativeHost", src / "native_host.py"],
        },
    ]


def component_hash(spec: dict, deps_sig: str, version: str) -> str:
    h = hashlib.sha256()
    h.update(version.encode("utf-8")); h.update(b"|")
    if spec.get("deps"):
        h.update(deps_sig.encode("utf-8"))
    h.update(b"|")
    h.update(hash_files(spec["sources"]).encode("utf-8"))
    h.update(b"|")
    h.update("::".join(str(a) for a in spec["args"]).encode("utf-8"))
    return h.hexdigest()


def valid_venv_python(py: Path) -> bool:
    if not py.exists():
        return False
    try:
        p = subprocess.run([str(py), "-c", "import sys; print(sys.version_info[:2])"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return p.returncode == 0
    except Exception:
        return False


def ensure_build_venv(log: Logger, root: Path) -> Path:
    venv_dir = build_venv_dir()
    py = venv_dir / "Scripts" / "python.exe"
    if valid_venv_python(py):
        log.line("Srodowisko budowy: OK (wykorzystuje istniejace).")
        return py
    if venv_dir.exists():
        shutil.rmtree(venv_dir, ignore_errors=True)
    log.line("Tworzenie odseparowanego srodowiska budowy...")
    run(log, [sys.executable, "-m", "venv", venv_dir])
    return py


def install_python_dependencies(log: Logger, py: Path, root: Path, manifest: dict, manifest_path: Path):
    sig = deps_signature(root)
    if manifest.get("_deps") == sig and valid_venv_python(py):
        log.line("Biblioteki bez zmian - pomijam instalacje zaleznosci.")
        return
    run(log, [py, "-m", "pip", "install", "--disable-pip-version-check", "--upgrade", "pip", "setuptools", "wheel"])
    run(log, [py, "-m", "pip", "install", "--disable-pip-version-check", "--prefer-binary", "-r", root / "src" / "requirements.txt", PYINSTALLER_REQ])
    manifest["_deps"] = sig
    save_manifest(manifest_path, manifest)


def build_binaries(log: Logger, py: Path, root: Path, manifest: dict, manifest_path: Path) -> Path:
    build = root / "build"
    dist = build / "dist"
    if build.exists():
        shutil.rmtree(build, ignore_errors=True)
    dist.mkdir(parents=True, exist_ok=True)

    cache = build_cache_dir()
    deps_sig = deps_signature(root)
    reused, rebuilt = [], []

    for spec in component_specs(root):
        name = spec["name"]
        chash = component_hash(spec, deps_sig, APP_VERSION)
        cached_dir = cache / name
        produced = dist / spec["dist_subdir"]
        if manifest.get(name) == chash and (cached_dir / spec["exe"]).exists():
            log.line(f"Komponent {name}: bez zmian - przywracam z pamieci podrecznej.")
            if produced.exists():
                shutil.rmtree(produced, ignore_errors=True)
            shutil.copytree(cached_dir, produced)
            reused.append(name)
            continue
        log.line(f"Komponent {name}: zmieniony lub nowy - buduje od nowa.")
        produced.parent.mkdir(parents=True, exist_ok=True)
        run(log, [py, "-m", "PyInstaller", "--noconfirm", "--clean",
                  "--distpath", produced.parent if spec["dist_subdir"] != "NativeHost" else produced,
                  "--workpath", build / f"work_{name}", "--specpath", build / f"spec_{name}"] + list(spec["args"]))
        if not (produced / spec["exe"]).exists():
            raise InstallerError(f"Budowa komponentu {name} nie utworzyla pliku: {produced / spec['exe']}")
        if cached_dir.exists():
            shutil.rmtree(cached_dir, ignore_errors=True)
        shutil.copytree(produced, cached_dir)
        manifest[name] = chash
        save_manifest(manifest_path, manifest)
        rebuilt.append(name)

    log.line(f"Komponenty przywrocone z cache: {', '.join(reused) or 'brak'}.")
    log.line(f"Komponenty przebudowane: {', '.join(rebuilt) or 'brak'}.")

    expected = [
        dist / "CourseArchiver" / "CourseArchiver.exe",
        dist / "CourseArchiverAgent" / "CourseArchiverAgent.exe",
        dist / "NativeHost" / "CourseArchiverNativeHost.exe",
    ]
    missing = [str(p) for p in expected if not p.exists()]
    if missing:
        raise InstallerError("Budowa zakonczyla sie bez wymaganych plikow:\n" + "\n".join(missing))
    return dist



def compile_installer(log: Logger, inno: Path, root: Path) -> Path:
    out = root / "GOTOWY_INSTALATOR"
    out.mkdir(parents=True, exist_ok=True)
    run(log, [inno, root / "installer" / "CourseArchiver.iss"], cwd=root)
    setup = out / f"CourseArchiver_Setup_{APP_VERSION}.exe"
    if not setup.exists():
        raise InstallerError(f"Nie znaleziono wygenerowanego instalatora: {setup}")
    return setup


def installed_app_candidates() -> list[Path]:
    vals = []
    for env_name in ("PROGRAMFILES", "PROGRAMFILES(X86)"):
        base = os.environ.get(env_name)
        if base:
            vals.append(Path(base) / "Course Archiver & Transcriber" / "CourseArchiver" / "CourseArchiver.exe")
    return vals


def wire_native_messaging(log: Logger, dest: Path):
    """Zarejestruj mostek Chrome tak samo jak robi to instalator Inno."""
    if os.name != "nt":
        return
    import json
    import winreg
    host = dest / "NativeHost" / "CourseArchiverNativeHost.exe"
    manifest_dir = Path(os.environ["LOCALAPPDATA"]) / "CourseArchiver"
    manifest_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = manifest_dir / "com.coursearchiver.bridge.json"
    manifest_path.write_text(json.dumps({
        "name": "com.coursearchiver.bridge",
        "description": "Local bridge for Course Archiver & Transcriber",
        "path": str(host),
        "type": "stdio",
        "allowed_origins": [f"chrome-extension://{EXTENSION_ID}/"],
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Software\Google\Chrome\NativeMessagingHosts\com.coursearchiver.bridge") as key:
        winreg.SetValueEx(key, None, 0, winreg.REG_SZ, str(manifest_path))
    log.line("Mostek Chrome (Native Messaging) skonfigurowany.")


def create_shortcuts(log: Logger, app: Path):
    if os.name != "nt":
        return
    targets = []
    up = os.environ.get("USERPROFILE")
    if up:
        targets.append(Path(up) / "Desktop")
    appdata = os.environ.get("APPDATA")
    if appdata:
        targets.append(Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs")
    for folder in targets:
        try:
            folder.mkdir(parents=True, exist_ok=True)
            lnk = folder / f"{APP_NAME}.lnk"
            ps = (
                "$s=(New-Object -ComObject WScript.Shell).CreateShortcut('{lnk}');"
                "$s.TargetPath='{tgt}';$s.WorkingDirectory='{wd}';$s.Save()"
            ).format(lnk=str(lnk), tgt=str(app), wd=str(app.parent))
            subprocess.run(["powershell", "-NoProfile", "-Command", ps], check=False,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            pass
    log.line("Utworzono skroty na Pulpicie i w menu Start.")


def deploy_incrementally(log: Logger, dest: Path, sources: dict):
    """Skopiuj tylko te komponenty, ktore sie zmienily; usun te, ktorych juz nie ma.

    Stan poprzedniego wdrozenia trzymamy w .install_manifest.json (hash drzewa
    kazdego komponentu). Dzieki temu ponowna instalacja nie kopiuje setek MB,
    gdy zmienil sie tylko jeden plik EXE.
    """
    manifest_path = dest / ".install_manifest.json"
    previous = load_manifest(manifest_path)
    current = {}
    added, updated, unchanged = [], [], []

    for name, source in sources.items():
        if not source.exists():
            if name in ("CourseArchiver", "Agent", "NativeHost"):
                raise InstallerError(f"Brak zbudowanego komponentu do wdrozenia: {source}")
            continue
        new_hash = hash_tree(source)
        current[name] = new_hash
        target = dest / name
        if previous.get(name) == new_hash and target.exists():
            unchanged.append(name)
            continue
        if target.exists():
            shutil.rmtree(target, ignore_errors=True)
            updated.append(name)
        else:
            added.append(name)
        shutil.copytree(source, target)

    # Komponenty obecne wczesniej, ktorych juz nie dostarczamy - usun.
    removed = []
    for name in previous:
        if name not in current and (dest / name).exists():
            shutil.rmtree(dest / name, ignore_errors=True)
            removed.append(name)

    save_manifest(manifest_path, current)
    log.line(f"Dodane: {', '.join(added) or 'brak'}; zaktualizowane: {', '.join(updated) or 'brak'}; "
             f"bez zmian: {', '.join(unchanged) or 'brak'}; usuniete: {', '.join(removed) or 'brak'}.")


def portable_install(log: Logger, root: Path) -> Path:
    """Wdroz aplikacje bez uruchamiania niepodpisanego instalatora EXE.

    Uzywane, gdy Smart App Control zablokuje Setup.exe. Kopiuje juz zbudowane
    pliki do %LOCALAPPDATA%\\Programs, konfiguruje mostek Chrome i skroty.
    """
    dist = root / "build" / "dist"
    dest = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "Programs" / "Course Archiver & Transcriber"
    dest.mkdir(parents=True, exist_ok=True)
    log.line(f"Tryb przenosny: aktualizuje aplikacje w {dest}")

    # Zrodlo -> podkatalog docelowy. Rozszerzenie Chrome bierzemy wprost z src.
    sources = {
        "CourseArchiver": dist / "CourseArchiver",
        "Agent": dist / "CourseArchiverAgent",
        "NativeHost": dist / "NativeHost",
        "ChromeExtension": root / "src" / "chrome_extension",
    }
    deploy_incrementally(log, dest, sources)
    app = dest / "CourseArchiver" / "CourseArchiver.exe"
    try:
        wire_native_messaging(log, dest)
    except Exception as e:
        log.line(f"[WARN] Nie udalo sie skonfigurowac mostka Chrome: {e}")
    try:
        create_shortcuts(log, app)
    except Exception as e:
        log.line(f"[WARN] Nie udalo sie utworzyc skrotow: {e}")
    log.line("Tryb przenosny gotowy. Aplikacja zainstalowana bez uruchamiania Setup.exe.")
    return app


def install_final_app(log: Logger, setup: Path, root: Path) -> Path:
    log.line("Uruchamiam finalny instalator aplikacji. Windows moze pokazac jedno okno UAC - wybierz TAK.")
    try:
        p = run(log, [setup, "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/SP-"], check=False)
    except OSError as e:
        if getattr(e, "winerror", None) in APP_CONTROL_WINERRORS:
            log.line("")
            log.line("[UWAGA] " + APP_CONTROL_HINT)
            log.line("Przechodze na tryb przenosny (nie wymaga uruchamiania Setup.exe).")
            return portable_install(log, root)
        raise
    if p.returncode in (0, 3010):
        for app in installed_app_candidates():
            if app.exists():
                return app
        log.line("[WARN] Instalator zakonczyl prace, ale nie znaleziono aplikacji. Uzywam trybu przenosnego.")
        return portable_install(log, root)
    raise InstallerError(f"Finalny instalator zwrocil kod {p.returncode}. Jezeli anulowales UAC, uruchom instalacje ponownie.")


def cleanup_build(log: Logger, root: Path):
    # Usuwamy tylko wynik biezacej budowy w staging. Srodowisko budowy i cache
    # komponentow (poza staging, w CourseArchiverBuilder) zostaja, aby kolejne
    # uruchomienia byly szybkie.
    p = root / "build"
    if p.exists():
        log.line("Usuwam pliki tymczasowe: build")
        shutil.rmtree(p, ignore_errors=True)


def launch_app(log: Logger, app: Path):
    try:
        subprocess.Popen([str(app)], cwd=str(app.parent), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        log.line("Aplikacja zostala uruchomiona.")
    except OSError as e:
        if getattr(e, "winerror", None) in APP_CONTROL_WINERRORS:
            log.line("[UWAGA] " + APP_CONTROL_HINT)
            log.line("Aplikacja zostala zainstalowana, ale Windows blokuje jej pierwsze uruchomienie.")
            log.line("Aby ja uruchomic: Ustawienia > Prywatnosc i zabezpieczenia > Zabezpieczenia")
            log.line("Windows > Kontrola aplikacji i przegladarki > Smart App Control > Wylacz,")
            log.line("albo kliknij skrot na Pulpicie i wybierz 'Uruchom mimo to' jesli sie pojawi.")
        else:
            log.line(f"Nie udalo sie automatycznie uruchomic aplikacji: {e}")
            log.line(f"Uruchom ja ze skrotu na pulpicie: {APP_NAME}")
    except Exception as e:
        log.line(f"Nie udalo sie automatycznie uruchomic aplikacji: {e}")
        log.line(f"Uruchom ja ze skrotu na pulpicie: {APP_NAME}")


def self_test_sources(root: Path):
    required = [
        root / "src" / "app.pyw",
        root / "src" / "agent_generic.py",
        root / "src" / "session_events.py",
        root / "src" / "native_host.py",
        root / "src" / "requirements.txt",
        root / "src" / "chrome_extension" / "manifest.json",
        root / "installer" / "CourseArchiver.iss",
    ]
    missing = [str(p) for p in required if not p.exists()]
    if missing:
        raise InstallerError("Paczka instalacyjna jest niekompletna:\n" + "\n".join(missing))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=None)
    ap.add_argument("--log", default=None)
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()

    # Najbardziej niezawodny wariant dla Windows: katalog paczki ustalamy
    # bezposrednio z polozenia tego pliku. Nie musimy przekazywac sciezki
    # konczacej sie backslashem przez cmd.exe -> CreateProcess -> argv.
    root = Path(args.root).expanduser().resolve() if args.root else Path(__file__).resolve().parent

    env_log = os.environ.get("COURSEARCHIVER_INSTALL_LOG")
    if args.log:
        log_path = Path(args.log).expanduser().resolve()
    elif env_log:
        log_path = Path(env_log).expanduser().resolve()
    else:
        base = Path(os.environ.get("LOCALAPPDATA", root)) / "CourseArchiverInstaller"
        log_path = (base / "INSTALL_LOG.txt").resolve()
    log = Logger(log_path)
    log.line(f"Root package: {root}")
    log.line(f"Python executable: {sys.executable}")
    log.line(f"Python version: {sys.version.replace(chr(10), ' ')}")
    try:
        self_test_sources(root)
        if args.self_test:
            log.line("SELF-TEST: OK")
            return 0

        total = 8
        stage(log, 1, total, "Sprawdzenie komputera")
        check_platform(log, root)

        cache = Path(os.environ.get("LOCALAPPDATA", tempfile.gettempdir())) / "CourseArchiverInstaller" / "downloads"
        cache.mkdir(parents=True, exist_ok=True)

        stage(log, 2, total, "Sprawdzenie Google Chrome")
        chrome = ensure_chrome(log, cache)
        log.line(f"Chrome gotowy: {chrome}")

        stage(log, 3, total, "Sprawdzenie Microsoft Visual C++ Runtime")
        ensure_vcredist(log, cache)

        stage(log, 4, total, "Sprawdzenie narzedzia do tworzenia instalatora")
        inno = ensure_inno(log, cache)
        log.line(f"Inno Setup gotowy: {inno}")

        stage(log, 5, total, "Przygotowanie aplikacji")
        # Inkrementalnie: srodowisko i biblioteki odtwarzamy tylko przy zmianie
        # requirements.txt; komponenty budujemy tylko gdy zmienil sie ich kod
        # lub wersja. Manifest (hash na komponent) pilnuje, ze nie wgramy nigdy
        # nieaktualnego pliku.
        manifest_path = build_cache_dir() / "build_manifest.json"
        manifest = load_manifest(manifest_path)
        py = ensure_build_venv(log, root)
        install_python_dependencies(log, py, root, manifest, manifest_path)

        stage(log, 6, total, "Budowa aplikacji Windows")
        build_binaries(log, py, root, manifest, manifest_path)

        stage(log, 7, total, "Tworzenie jednego instalatora EXE")
        setup = compile_installer(log, inno, root)
        log.line(f"Gotowy instalator: {setup}")

        # Keep a convenient copy outside the staging directory.
        try:
            downloads = Path.home() / "Downloads"
            downloads.mkdir(parents=True, exist_ok=True)
            saved_setup = downloads / setup.name
            shutil.copy2(setup, saved_setup)
            log.line(f"Kopia instalatora zapisana w Pobrane: {saved_setup}")
        except Exception as e:
            log.line(f"[WARN] Nie udalo sie skopiowac instalatora do Pobrane: {e}")

        stage(log, 8, total, "Instalacja i uruchomienie aplikacji")
        app = install_final_app(log, setup, root)
        cleanup_build(log, root)
        launch_app(log, app)

        log.line()
        log.line("INSTALACJA ZAKONCZONA POWODZENIEM.")
        log.line(f"Finalny instalator pozostawiono tutaj: {setup}")
        log.line("Na pulpicie i w menu Start znajduje sie skrot do aplikacji.")
        log.line("Pierwszy model Whisper zostanie pobrany automatycznie dopiero przy pierwszej transkrypcji.")
        return 0
    except Exception as e:
        log.line()
        log.line("*** BLAD INSTALACJI ***")
        log.line(f"Typ bledu: {type(e).__name__}")
        log.line(str(e))
        log.line("--- TRACEBACK ---")
        log.line(traceback.format_exc().rstrip())
        log.line("--- KONIEC TRACEBACK ---")
        log.line(f"Pelny log: {log.path}")
        try:
            root_log = root / "INSTALL_LOG.txt"
            if root_log.resolve() != log.path.resolve():
                shutil.copy2(log.path, root_log)
        except Exception:
            pass
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
