"""Podbij wersję aplikacji w jednym miejscu.

Wersja żyje w kilku plikach (payload uruchamia się na Windows niezależnie), więc
ręczna zmiana kończyła się rozjazdem. To narzędzie zmienia wszystkie naraz i
dopisuje wpis do CHANGELOG.md.

Użycie:
    python tools/bump_version.py 4.7.0 ["opis wydania"]
    python tools/bump_version.py --check      # tylko sprawdź spójność
"""

from __future__ import annotations

import re
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / "package"

# Plik -> (regex wyszukujący wersję, funkcja budująca nową linię).
SPOTS = [
    (PKG / "src" / "VERSION.txt", r"^\s*(\d+\.\d+\.\d+)\s*$", lambda v: v + "\n"),
    (PKG / "bootstrap.py", r'APP_VERSION = "(\d+\.\d+\.\d+)"', lambda v: f'APP_VERSION = "{v}"'),
    (PKG / "installer" / "CourseArchiver.iss", r'#define MyAppVersion "(\d+\.\d+\.\d+)"', lambda v: f'#define MyAppVersion "{v}"'),
    (PKG / "installer" / "CourseArchiver.iss", r"VersionInfoVersion=(\d+\.\d+\.\d+)\.0", lambda v: f"VersionInfoVersion={v}.0"),
    (PKG / "worker_install.cmd", r'set "VERSION=(\d+\.\d+\.\d+)"', lambda v: f'set "VERSION={v}"'),
]

CHANGELOG = PKG / "CHANGELOG.md"


def current_versions() -> dict:
    found = {}
    for path, pattern, _ in SPOTS:
        text = path.read_text(encoding="utf-8")
        m = re.search(pattern, text, re.MULTILINE)
        found[(path.name, pattern)] = m.group(1) if m else None
    return found


def check() -> int:
    vals = [v for v in current_versions().values()]
    if None in vals:
        print("FAIL: nie znaleziono wersji w którymś z plików:", current_versions())
        return 1
    if len(set(vals)) != 1:
        print("FAIL: wersje są rozjechane:", current_versions())
        return 1
    print("OK: wszystkie miejsca deklarują wersję", vals[0])
    return 0


def valid(v: str) -> bool:
    return re.fullmatch(r"\d+\.\d+\.\d+", v) is not None


def bump(new: str, note: str) -> int:
    if not valid(new):
        print("Wersja musi mieć format X.Y.Z, np. 4.7.0"); return 2
    for path, pattern, render in SPOTS:
        text = path.read_text(encoding="utf-8")
        new_text, n = re.subn(pattern, lambda m: render(new), text, flags=re.MULTILINE)
        if n == 0:
            print(f"FAIL: nie znaleziono wzorca wersji w {path}"); return 1
        path.write_text(new_text, encoding="utf-8")
        print(f"  zaktualizowano {path.relative_to(ROOT)} ({n}x)")

    entry = f"## {new} — {date.today().isoformat()}\n\n- {note or 'Nowe wydanie.'}\n\n"
    if CHANGELOG.exists():
        old = CHANGELOG.read_text(encoding="utf-8")
        head, _, rest = old.partition("\n")  # zachowaj nagłówek pliku
        CHANGELOG.write_text(head + "\n\n" + entry + rest.lstrip("\n"), encoding="utf-8")
    else:
        CHANGELOG.write_text(f"# Historia zmian — Course Archiver & Transcriber\n\n{entry}", encoding="utf-8")
    print(f"  dopisano wpis do {CHANGELOG.relative_to(ROOT)}")
    print(f"Wersja podbita do {new}.")
    return 0


def main(argv) -> int:
    if len(argv) >= 2 and argv[1] == "--check":
        return check()
    if len(argv) < 2:
        print(__doc__); return 2
    return bump(argv[1], argv[2] if len(argv) > 2 else "")


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
