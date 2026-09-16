from __future__ import annotations

import json
import os
import struct
import subprocess
import sys
from pathlib import Path

APP_STATE = Path.home() / ".course_archiver_app"
PROFILES_FILE = APP_STATE / "profiles.json"


def read_message():
    raw = sys.stdin.buffer.read(4)
    if len(raw) != 4:
        return None
    size = struct.unpack("<I", raw)[0]
    if size <= 0 or size > 4 * 1024 * 1024:
        raise ValueError("Nieprawidłowy rozmiar wiadomości Native Messaging")
    data = sys.stdin.buffer.read(size)
    if len(data) != size:
        raise EOFError("Niepełna wiadomość Native Messaging")
    return json.loads(data.decode("utf-8"))


def write_message(obj):
    data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
    sys.stdout.buffer.write(struct.pack("<I", len(data)))
    sys.stdout.buffer.write(data)
    sys.stdout.buffer.flush()


def profiles():
    try:
        data = json.loads(PROFILES_FILE.read_text(encoding="utf-8"))
        return sorted(data.keys()) if isinstance(data, dict) else []
    except Exception:
        return []


def launch_app(url, profile, action):
    if getattr(sys, "frozen", False):
        host_dir = Path(sys.executable).resolve().parent
        app = host_dir.parent / "CourseArchiver" / "CourseArchiver.exe"
        app_dir = app.parent
        args = [str(app), "--url", url, "--action", action]
    else:
        app_dir = Path(__file__).resolve().parent
        pythonw = Path(sys.executable)
        app = app_dir / "app.pyw"
        args = [str(pythonw), str(app), "--url", url, "--action", action]
    if not app.exists():
        raise RuntimeError("Nie znaleziono aplikacji Course Archiver. Uruchom ponownie instalator.")
    if profile:
        args += ["--profile", profile]
    kwargs = {"cwd": str(app_dir), "stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    subprocess.Popen(args, **kwargs)


def handle(msg):
    cmd = msg.get("cmd")
    if cmd == "status":
        return {"ok": True, "profiles": profiles()}
    if cmd == "launch":
        url = str(msg.get("url") or "").strip()
        action = str(msg.get("action") or "open")
        profile = str(msg.get("profile") or "").strip()
        if not (url.startswith("http://") or url.startswith("https://")):
            return {"ok": False, "error": "Dozwolone są tylko adresy http/https."}
        if action not in {"open", "login", "discover", "run"}:
            return {"ok": False, "error": "Nieznana akcja."}
        launch_app(url, profile, action)
        return {"ok": True}
    return {"ok": False, "error": "Nieznane polecenie."}


def main():
    try:
        msg = read_message()
        if msg is None:
            return
        write_message(handle(msg))
    except Exception as e:
        write_message({"ok": False, "error": str(e)})


if __name__ == "__main__":
    main()
