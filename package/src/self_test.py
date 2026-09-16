from __future__ import annotations

import base64
import hashlib
import json
import struct
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
EXPECTED_ID = "dfmedhencldblnhceamhppjklgomoffk"


def extension_id_from_key(key_b64: str) -> str:
    raw = base64.b64decode(key_b64)
    digest = hashlib.sha256(raw).digest()[:16]
    alphabet = "abcdefghijklmnop"
    return "".join(alphabet[b >> 4] + alphabet[b & 15] for b in digest)


def test_manifest():
    m = json.loads((ROOT / "chrome_extension" / "manifest.json").read_text(encoding="utf-8"))
    assert m["manifest_version"] == 3
    assert "nativeMessaging" in m["permissions"]
    ext_id = extension_id_from_key(m["key"])
    assert ext_id == EXPECTED_ID, (ext_id, EXPECTED_ID)
    return ext_id


def test_native_protocol():
    payload = json.dumps({"cmd": "status"}).encode("utf-8")
    framed = struct.pack("<I", len(payload)) + payload
    p = subprocess.run([sys.executable, str(ROOT / "native_host.py")], input=framed, capture_output=True, timeout=10)
    assert p.returncode == 0, p.stderr.decode(errors="replace")
    assert len(p.stdout) >= 4
    n = struct.unpack("<I", p.stdout[:4])[0]
    data = json.loads(p.stdout[4:4+n].decode("utf-8"))
    assert data.get("ok") is True, data
    assert isinstance(data.get("profiles"), list), data
    return data


def main():
    ext_id = test_manifest()
    status = test_native_protocol()
    print("OK manifest MV3 / extension id:", ext_id)
    print("OK Native Messaging framing/status:", status)
    print("OK Python source compilation is checked separately by setup/package build.")


if __name__ == "__main__":
    main()
