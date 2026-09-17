"""Zbuduj paczkę one-click: 01_INSTALUJ.cmd z wbudowanym payloadem + zewnętrzny ZIP.

Uruchomienie:  python tools/build_oneclick.py
Wynik:         dist/CourseArchiver_OneClick_<wersja>.zip
"""

from __future__ import annotations

import base64
import hashlib
import io
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "package"
TOOLS = ROOT / "tools"
DIST = ROOT / "dist"
TEMPLATE = TOOLS / "oneclick_launcher.cmd.tmpl"
B64_WIDTH = 76
# Stała data w ZIP-ie, żeby ta sama zawartość dawała ten sam plik wynikowy.
ZIP_DATE = (2026, 1, 1, 0, 0, 0)


def version() -> str:
    return (PACKAGE / "src" / "VERSION.txt").read_text(encoding="utf-8").strip()


EXCLUDED_DIRS = {"__pycache__", ".pytest_cache", ".git"}
EXCLUDED_SUFFIXES = {".pyc", ".pyo"}


def payload_files() -> list[Path]:
    files = [
        p for p in sorted(PACKAGE.rglob("*"))
        if p.is_file()
        and not EXCLUDED_DIRS.intersection(p.parts)
        and p.suffix not in EXCLUDED_SUFFIXES
    ]
    if not files:
        raise SystemExit(f"Brak plików do spakowania w {PACKAGE}")
    return files


def build_payload_zip() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for path in payload_files():
            info = zipfile.ZipInfo(path.relative_to(PACKAGE).as_posix(), date_time=ZIP_DATE)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            z.writestr(info, path.read_bytes())
    return buf.getvalue()


def render_launcher(payload: bytes, ver: str) -> str:
    template = TEMPLATE.read_text(encoding="utf-8")
    text = (
        template
        .replace("{{VERSION_UNDERSCORE}}", ver.replace(".", "_"))
        .replace("{{VERSION_SHORT}}", ".".join(ver.split(".")[:2]))
        .replace("{{VERSION}}", ver)
        .replace("{{SHA256}}", hashlib.sha256(payload).hexdigest())
    )
    if "{{" in text:
        raise SystemExit("Szablon launchera zawiera niepodstawione znaczniki.")
    encoded = base64.b64encode(payload).decode("ascii")
    lines = [encoded[i:i + B64_WIDTH] for i in range(0, len(encoded), B64_WIDTH)]
    body = text.rstrip("\n") + "\n" + "\n".join("PAYLOAD:" + x for x in lines) + "\n"
    # cmd.exe wymaga CRLF, inaczej etykiety i goto potrafią się rozjechać.
    return body.replace("\r\n", "\n").replace("\n", "\r\n")


def readme(ver: str) -> str:
    text = f"""COURSE ARCHIVER & TRANSCRIBER {ver}

Kliknij dwukrotnie:
01_INSTALUJ.cmd

Co nowego w {ver}:
- Inkrementalna budowa: komponenty bez zmian sa przywracane z pamieci
  podrecznej, wiec kolejne instalacje trwaja sekundy zamiast dziesiatek minut.
- Jesli Windows (Smart App Control) zablokuje instalator, aplikacja wdraza sie
  w trybie przenosnym i pokazuje instrukcje.
- Ciemny interfejs z lista profili, zywa lista materialow i widokiem Archiwum.
- Widoczny status ZALOGOWANO i przycisk ZROB WSZYSTKO (caly proces jednym klikiem).

Pelna historia zmian: package/CHANGELOG.md

W razie bledu:
%LOCALAPPDATA%\\CourseArchiverInstaller\\INSTALL_LOG.txt

Finalny instalator po sukcesie:
%USERPROFILE%\\Downloads\\CourseArchiver_Setup_{ver}.exe
"""
    return text.replace("\r\n", "\n").replace("\n", "\r\n")


def main() -> None:
    ver = version()
    payload = build_payload_zip()
    launcher = render_launcher(payload, ver)
    DIST.mkdir(parents=True, exist_ok=True)
    out = DIST / f"CourseArchiver_OneClick_{ver.replace('.', '_')}.zip"
    folder = f"CourseArchiver_OneClick_{ver.replace('.', '_')}"
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in ((f"{folder}/01_INSTALUJ.cmd", launcher), (f"{folder}/README.txt", readme(ver))):
            info = zipfile.ZipInfo(name, date_time=ZIP_DATE)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            z.writestr(info, data.encode("utf-8"))

    print(f"Wersja:            {ver}")
    print(f"Plików w payload:  {len(payload_files())}")
    print(f"Payload SHA256:    {hashlib.sha256(payload).hexdigest()}")
    print(f"Launcher:          {len(launcher)} bajtów")
    print(f"Paczka:            {out} ({out.stat().st_size / 1024:.1f} KB)")


if __name__ == "__main__":
    main()
