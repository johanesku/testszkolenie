"""Weryfikacja statyczna gotowej paczki one-click.

Skrypt odtwarza kroki, które na Windows wykonuje 01_INSTALUJ.cmd:
wyciąga linie PAYLOAD:, dekoduje base64, sprawdza sumę SHA256, rozpakowuje
payload i uruchamia na nim komplet testów paczki. Dzięki temu sprawdzamy to,
co naprawdę trafi do użytkownika, a nie katalog źródłowy.

Uruchomienie:  python tools/verify_package.py
"""

from __future__ import annotations

import base64
import hashlib
import io
import re
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
# Pliki, których obecności 01_INSTALUJ.cmd pilnuje przed startem instalacji.
REQUIRED_BY_LAUNCHER = ("bootstrap.py", "worker_install.cmd", "installer/CourseArchiver.iss")
PACKAGE_TESTS = ("tests/test_package.py", "tests/test_installer_integrity.py", "tests/test_login_flow.py", "tests/test_incremental.py")

failures: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"[{'OK ' if ok else 'FAIL'}] {label}" + (f" — {detail}" if detail else ""))
    if not ok:
        failures.append(label)


def newest_package() -> Path:
    packages = sorted(DIST.glob("CourseArchiver_OneClick_*.zip"))
    if not packages:
        raise SystemExit(f"Brak paczki w {DIST}. Uruchom najpierw tools/build_oneclick.py")
    return packages[-1]


def main() -> int:
    pkg = newest_package()
    print(f"Paczka: {pkg}\n")

    with zipfile.ZipFile(pkg) as z:
        names = z.namelist()
        cmd_name = next((n for n in names if n.endswith("01_INSTALUJ.cmd")), None)
        check("paczka zawiera 01_INSTALUJ.cmd", cmd_name is not None, ", ".join(names))
        check("paczka zawiera README.txt", any(n.endswith("README.txt") for n in names))
        if cmd_name is None:
            return 1
        raw = z.read(cmd_name)

    text = raw.decode("utf-8")
    check("launcher ma zakończenia linii CRLF", b"\r\n" in raw and not re.search(rb"(?<!\r)\n", raw))

    version = re.search(r'set "VERSION=([0-9.]+)"', text)
    check("launcher deklaruje wersję", version is not None, version.group(1) if version else "")
    declared_version = version.group(1) if version else ""

    # Krok 1: to samo, co robi findstr /b /c:"PAYLOAD:" w 01_INSTALUJ.cmd.
    payload_lines = [ln[len("PAYLOAD:"):] for ln in text.splitlines() if ln.startswith("PAYLOAD:")]
    check("launcher zawiera wbudowany payload", len(payload_lines) > 100, f"{len(payload_lines)} linii")

    try:
        payload = base64.b64decode("".join(payload_lines), validate=True)
    except Exception as e:
        check("payload dekoduje się z base64", False, str(e))
        return 1
    check("payload dekoduje się z base64", True, f"{len(payload) / 1024:.1f} KB")

    declared_sha = re.search(r"REM SHA256: ([0-9a-f]{64})", text)
    actual_sha = hashlib.sha256(payload).hexdigest()
    check("suma SHA256 w launcherze zgadza się z payloadem",
          declared_sha is not None and declared_sha.group(1) == actual_sha, actual_sha)

    with tempfile.TemporaryDirectory() as tmp:
        stage = Path(tmp)
        try:
            with zipfile.ZipFile(io.BytesIO(payload)) as z:
                z.extractall(stage)
        except zipfile.BadZipFile as e:
            check("payload jest poprawnym archiwum ZIP", False, str(e))
            return 1
        check("payload jest poprawnym archiwum ZIP", True)

        for rel in REQUIRED_BY_LAUNCHER:
            check(f"payload zawiera {rel}", (stage / rel).exists())

        staged_version = (stage / "src" / "VERSION.txt").read_text(encoding="utf-8").strip()
        check("wersja w payloadzie zgadza się z launcherem", staged_version == declared_version,
              f"{staged_version} vs {declared_version}")
        check("nazwa paczki zawiera wersję", declared_version.replace(".", "_") in pkg.name)

        print("\n--- testy uruchomione na rozpakowanym payloadzie ---")
        for rel in PACKAGE_TESTS:
            p = subprocess.run([sys.executable, str(stage / rel)], cwd=stage, capture_output=True, text=True)
            if p.stdout.strip():
                print("\n".join("      " + x for x in p.stdout.strip().splitlines()))
            check(f"test {rel}", p.returncode == 0, (p.stderr.strip().splitlines() or [""])[-1])

        print("\n--- kompilacja wszystkich modułów Pythona z payloadu ---")
        sources = sorted(stage.rglob("*.py")) + sorted(stage.rglob("*.pyw"))
        p = subprocess.run([sys.executable, "-m", "py_compile", *[str(x) for x in sources]],
                           capture_output=True, text=True)
        check(f"kompilacja {len(sources)} plików", p.returncode == 0, p.stderr.strip()[-300:])

    print()
    if failures:
        print(f"WYNIK: FAIL ({len(failures)}): " + "; ".join(failures))
        return 1
    print("WYNIK: PASS — paczka jest spójna i gotowa do uruchomienia na Windows.")
    return 0



if __name__ == "__main__":
    raise SystemExit(main())
