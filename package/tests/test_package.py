from pathlib import Path
import ast, base64, hashlib, json

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
EXPECTED = "dfmedhencldblnhceamhppjklgomoffk"

for name in ["app.pyw", "agent_generic.py", "native_host.py", "session_events.py"]:
    ast.parse((SRC/name).read_text(encoding="utf-8"), filename=name)
print("PASS Python syntax")

m=json.loads((SRC/"chrome_extension"/"manifest.json").read_text(encoding="utf-8"))
assert m["manifest_version"] == 3
raw=base64.b64decode(m["key"])
digest=hashlib.sha256(raw).digest()[:16]
alphabet="abcdefghijklmnop"
extid="".join(alphabet[x>>4]+alphabet[x&15] for x in digest)
assert extid == EXPECTED, (extid, EXPECTED)
print("PASS Chrome extension fixed ID", extid)

iss=(ROOT/"installer"/"CourseArchiver.iss").read_text(encoding="utf-8")
assert EXPECTED in iss
assert "NativeMessagingHosts\\com.coursearchiver.bridge" in iss
assert "CourseArchiverNativeHost.exe" in iss
print("PASS installer/native messaging wiring")

app=(SRC/"app.pyw").read_text(encoding="utf-8")
assert "CourseArchiverAgent.exe" in app
agent=(SRC/"agent_generic.py").read_text(encoding="utf-8")
assert 'channel="chrome"' in agent
print("PASS packaged app -> agent and system Chrome wiring")
