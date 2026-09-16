from __future__ import annotations

import base64
import hashlib
import json
import os
import struct
import subprocess
import sys
from pathlib import Path

EXPECTED_ID = "dfmedhencldblnhceamhppjklgomoffk"
ROOT = Path(__file__).resolve().parent


def extension_id():
    manifest = json.loads((ROOT / "chrome_extension" / "manifest.json").read_text(encoding="utf-8"))
    raw = base64.b64decode(manifest["key"])
    digest = hashlib.sha256(raw).digest()[:16]
    alphabet = "abcdefghijklmnop"
    return "".join(alphabet[x >> 4] + alphabet[x & 15] for x in digest)


def framed_status(exe: Path):
    data = json.dumps({"cmd": "status"}).encode("utf-8")
    frame = struct.pack("<I", len(data)) + data
    p = subprocess.run([str(exe)], input=frame, capture_output=True, timeout=15)
    if p.returncode != 0:
        raise RuntimeError(p.stderr.decode(errors="replace"))
    n = struct.unpack("<I", p.stdout[:4])[0]
    return json.loads(p.stdout[4:4+n].decode("utf-8"))


def main():
    assert extension_id() == EXPECTED_ID
    print("[OK] Manifest V3 i stały Extension ID")

    if os.name != "nt":
        print("[SKIP] Test rejestru/EXE Native Messaging wymaga Windows")
        return

    import winreg
    manifest_path = Path(os.environ["LOCALAPPDATA"]) / "CourseArchiver" / "com.coursearchiver.bridge.json"
    assert manifest_path.exists(), manifest_path
    manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    host_exe = Path(manifest["path"])
    assert host_exe.exists(), host_exe
    assert manifest["allowed_origins"] == [f"chrome-extension://{EXPECTED_ID}/"]
    print("[OK] Native host manifest")

    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Google\Chrome\NativeMessagingHosts\com.coursearchiver.bridge") as key:
        reg_value, _ = winreg.QueryValueEx(key, None)
    assert Path(reg_value) == manifest_path
    print("[OK] Rejestr Chrome Native Messaging")

    status = framed_status(host_exe)
    assert status.get("ok") is True, status
    print("[OK] Native Messaging EXE protocol/status")

    import mss
    with mss.mss() as sct:
        monitor_count = len(sct.monitors) - 1
    assert monitor_count >= 1
    print(f"[OK] Wykrywanie monitorów: {monitor_count}")

    try:
        import soundcard as sc
        speakers = list(sc.all_speakers())
        print(f"[OK] Wykrywanie urządzeń audio: {len(speakers)}")
    except Exception as e:
        print(f"[WARN] Nie udało się wylistować urządzeń audio: {e}")

    print("Wynik: PASS")


if __name__ == "__main__":
    main()
