"""Testy inkrementalnej budowy i wdrożenia (bez Windows, bez PyInstaller).

Ładujemy bootstrap.py (czysta biblioteka standardowa) i sprawdzamy logikę
hashowania komponentów oraz wdrożenia dodaj/zmień/usuń.
"""

from importlib.machinery import SourceFileLoader
from pathlib import Path
import tempfile

ROOT = Path(__file__).resolve().parents[1]
boot = SourceFileLoader("ca_bootstrap", str(ROOT / "bootstrap.py")).load_module()


class _Log:
    def __init__(self): self.lines = []
    def line(self, text=""): self.lines.append(text)


def _write(p: Path, data: bytes):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)


def test_hash_files_detects_change(tmp: Path):
    a = tmp / "a.py"; _write(a, b"print(1)")
    h1 = boot.hash_files([a])
    assert h1 == boot.hash_files([a]), "hash musi być stabilny"
    _write(a, b"print(2)")
    assert boot.hash_files([a]) != h1, "zmiana treści musi zmienić hash"
    missing = tmp / "nope.py"
    assert boot.hash_files([missing]) == boot.hash_files([missing])
    print("PASS hash_files wykrywa zmiany treści")


def test_component_hash_inputs(tmp: Path):
    src = tmp / "src"; (src).mkdir()
    _write(src / "native_host.py", b"x=1")
    _write(src / "app.pyw", b"gui=1")
    _write(src / "agent_generic.py", b"agent=1")
    _write(src / "session_events.py", b"ev=1")
    specs = {s["name"]: s for s in boot.component_specs(tmp)}

    agent = specs["CourseArchiverAgent"]; host = specs["NativeHost"]
    h_agent = boot.component_hash(agent, "deps-A", "1.0.0")
    # Zmiana wersji => inny hash.
    assert boot.component_hash(agent, "deps-A", "1.0.1") != h_agent
    # Agent zależy od deps => zmiana deps zmienia hash.
    assert boot.component_hash(agent, "deps-B", "1.0.0") != h_agent
    # NativeHost NIE zależy od deps => zmiana deps nie zmienia hashu.
    h_host = boot.component_hash(host, "deps-A", "1.0.0")
    assert boot.component_hash(host, "deps-B", "1.0.0") == h_host
    # Zmiana źródła agenta zmienia hash agenta.
    _write(src / "agent_generic.py", b"agent=2")
    assert boot.component_hash(agent, "deps-A", "1.0.0") != h_agent
    print("PASS component_hash reaguje na wersję, deps i źródła")


def test_deploy_incrementally(tmp: Path):
    dest = tmp / "dest"
    src_a = tmp / "s_a"; _write(src_a / "CourseArchiver.exe", b"A1"); _write(src_a / "_internal" / "x.dll", b"dll")
    src_agent = tmp / "s_agent"; _write(src_agent / "CourseArchiverAgent.exe", b"AG1")
    src_host = tmp / "s_host"; _write(src_host / "CourseArchiverNativeHost.exe", b"H1")
    src_ext = tmp / "s_ext"; _write(src_ext / "manifest.json", b"{}")

    sources = {"CourseArchiver": src_a, "Agent": src_agent, "NativeHost": src_host, "ChromeExtension": src_ext}

    log = _Log(); boot.deploy_incrementally(log, dest, sources)
    assert (dest / "CourseArchiver" / "CourseArchiver.exe").read_bytes() == b"A1"
    assert (dest / "ChromeExtension" / "manifest.json").exists()
    assert "Dodane: CourseArchiver, Agent, NativeHost, ChromeExtension" in log.lines[-1]

    # Drugie wdrożenie bez zmian => wszystko "bez zmian".
    log = _Log(); boot.deploy_incrementally(log, dest, sources)
    assert "bez zmian: CourseArchiver, Agent, NativeHost, ChromeExtension" in log.lines[-1]
    assert "zaktualizowane: brak" in log.lines[-1]

    # Zmieniamy tylko GUI => tylko CourseArchiver zaktualizowany.
    _write(src_a / "CourseArchiver.exe", b"A2")
    log = _Log(); boot.deploy_incrementally(log, dest, sources)
    assert (dest / "CourseArchiver" / "CourseArchiver.exe").read_bytes() == b"A2"
    assert "zaktualizowane: CourseArchiver;" in log.lines[-1]

    # Usuwamy rozszerzenie ze źródeł => komponent skasowany z dest.
    del sources["ChromeExtension"]
    log = _Log(); boot.deploy_incrementally(log, dest, sources)
    assert not (dest / "ChromeExtension").exists()
    assert "usuniete: ChromeExtension" in log.lines[-1]
    print("PASS wdrożenie inkrementalne: dodaj / zmień / bez zmian / usuń")


def main():
    with tempfile.TemporaryDirectory() as d:
        test_hash_files_detects_change(Path(d) / "h")
    with tempfile.TemporaryDirectory() as d:
        test_component_hash_inputs(Path(d))
    with tempfile.TemporaryDirectory() as d:
        test_deploy_incrementally(Path(d))
    print("\nWSZYSTKIE TESTY INKREMENTALNE: PASS")


if __name__ == "__main__":
    main()
