"""Testy statyczne poprawki 4.6: widoczny status po udanym logowaniu.

Uruchomienie: python tests/test_login_flow.py
Testy nie wymagają PySide6, Playwright ani Windows.
"""

from pathlib import Path
import ast
import sys

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

import session_events as ev  # noqa: E402

AGENT = (SRC / "agent_generic.py").read_text(encoding="utf-8")
APP = (SRC / "app.pyw").read_text(encoding="utf-8")


def test_event_roundtrip():
    line = ev.format_event(ev.EVENT_LOGIN_OK, already_logged_in=False, url="https://portal/x")
    assert line.startswith(ev.EVENT_PREFIX)
    evt = ev.parse_event(line)
    assert evt["event"] == ev.EVENT_LOGIN_OK
    assert evt["already_logged_in"] is False
    assert "ZALOGOWANO" in ev.describe(evt)
    assert "ZALOGOWANO" in ev.describe({"event": ev.EVENT_LOGIN_OK, "already_logged_in": True})
    assert ev.parse_event("zwykla linia logu") is None
    assert ev.parse_event(ev.EVENT_PREFIX + "to nie jest json") is None
    print("PASS protokół zdarzeń (format/parse/describe)")


def test_output_splitter_keeps_events_whole():
    """Zdarzenie rozcięte między dwiema porcjami stdout musi przetrwać."""
    stream = "Ladowanie\n" + ev.format_event(ev.EVENT_LOGIN_OK, already_logged_in=True) + "\nKoniec\n"
    for cut in range(1, len(stream)):
        splitter = ev.OutputSplitter()
        lines = splitter.feed(stream[:cut]) + splitter.feed(stream[cut:]) + splitter.flush()
        events = [ev.parse_event(x) for x in lines]
        names = [e["event"] for e in events if e]
        assert names == [ev.EVENT_LOGIN_OK], (cut, lines)
        assert [x for x in lines if ev.parse_event(x) is None] == ["Ladowanie", "Koniec"], (cut, lines)

    splitter = ev.OutputSplitter()
    assert splitter.feed("bez konca linii") == []
    assert splitter.flush() == ["bez konca linii"]
    assert splitter.flush() == []
    assert ev.OutputSplitter().feed("crlf\r\n") == ["crlf"]
    print("PASS buforowanie stdout (zdarzenie nie ginie przy podziale porcji)")


def test_session_marker(tmp: Path):
    marker = ev.session_marker_path(tmp, "portal_testowy")
    assert ev.read_session_marker(marker) is None
    ev.write_session_marker(marker, portal_name="Portal Testowy", start_url="https://portal/x")
    data = ev.read_session_marker(marker)
    assert data["logged_in"] is True
    assert data["portal_name"] == "Portal Testowy"
    assert data["checked_at"]
    print("PASS trwały znacznik sesji")


def test_agent_reports_login():
    """Regresja 4.5: tryb --login-only kończył się bez sygnału dla GUI."""
    ast.parse(AGENT, filename="agent_generic.py")
    assert "def login_stage(" in AGENT
    assert "def verify_session(" in AGENT
    assert "emit(ev.EVENT_LOGIN_OK" in AGENT
    assert "emit(ev.EVENT_LOGIN_REQUIRED" in AGENT
    assert "emit(ev.EVENT_FINISHED" in AGENT
    assert "emit(ev.EVENT_FAILED" in AGENT
    assert "write_session_marker" in AGENT
    # Stara, cicha ścieżka wyjścia nie może wrócić.
    assert 'if args.login_only:log("Sesja logowania zapisana lokalnie.")' not in AGENT
    # manual_login nie może już po cichu wychodzić przy aktywnej sesji.
    assert "if not looks_like_login(page):return\n" not in AGENT
    print("PASS agent zgłasza wynik logowania")


def test_agent_can_chain_after_login():
    assert '"--after-login"' in AGENT
    assert "def final_stage(" in AGENT
    assert "STAGE_STOP" in AGENT
    print("PASS agent potrafi przejść dalej po zalogowaniu")


def test_agent_stage_selection():
    """final_stage() wyliczamy bez importu agenta (brak Playwright w testach)."""
    tree = ast.parse(AGENT, filename="agent_generic.py")
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "final_stage")
    namespace = {"ev": ev, "STAGE_STOP": "stop"}
    exec(compile(ast.Module(body=[fn], type_ignores=[]), "final_stage", "exec"), namespace)
    final_stage = namespace["final_stage"]

    class A:
        def __init__(self, login_only=False, discover_only=False, after_login=None):
            self.login_only = login_only
            self.discover_only = discover_only
            self.after_login = after_login

    assert final_stage(A(login_only=True)) == "stop"
    assert final_stage(A(login_only=True, after_login="discover")) == ev.STAGE_DISCOVER
    assert final_stage(A(login_only=True, after_login="process")) == ev.STAGE_PROCESS
    assert final_stage(A(discover_only=True)) == ev.STAGE_DISCOVER
    assert final_stage(A()) == ev.STAGE_PROCESS
    print("PASS wybór etapu agenta")


def test_gui_shows_status():
    ast.parse(APP, filename="app.pyw")
    assert "self.status_label" in APP
    assert "def set_status(" in APP
    assert "def handle_event(" in APP
    assert "ev.parse_event(line)" in APP
    assert "ev.EVENT_LOGIN_OK" in APP
    assert "ZALOGOWANO" in APP
    assert "def refresh_session_status(" in APP
    assert "read_session_marker" in APP
    print("PASS GUI pokazuje status sesji")


def test_gui_one_click_and_auto_scan():
    assert "self.b_all" in APP
    assert "ZRÓB WSZYSTKO" in APP
    assert "auto_scan_after_login" in APP
    assert '"--after-login", ev.STAGE_DISCOVER' in APP
    assert "def offer_next_step(" in APP
    # Jeden klik i przycisk startu muszą być blokowane podczas pracy agenta.
    assert "self.b_all.setEnabled(not running)" in APP
    print("PASS jeden klik + automatyczne przejście do skanowania")


class FakeWindow:
    """Minimalna atrapa okna: pozwala wykonać logikę statusu bez PySide6."""

    def __init__(self, auto_scan=False):
        self.status = ("idle", "")
        self.step = ""
        self.lines = []
        self.login_confirmed = False
        self.error_reported = False
        self.chained_run = False
        self.current_mode = None
        self.running = None
        self.offered = False
        self.started = []
        self.auto_scan = auto_scan

    # Metody podmienione atrapami.
    def set_status(self, kind, text): self.status = (kind, text)
    def set_step(self, text): self.step = text
    def read_output(self): pass
    def flush_output(self): pass
    def refresh_session_status(self): self.status = ("idle", "Sesja nieznana")
    def material_reset(self, total): self.materials = []
    def material_add(self, evt): self.materials.append(evt)
    def set_running(self, running): self.running = running
    def start_agent(self, mode, persist=True): self.started.append(mode)

    def offer_next_step(self):
        self.offered = True
        if self.auto_scan:
            self.start_agent("discover")

    @property
    def log(self):
        window = self

        class _Log:
            def appendPlainText(self, text): window.lines.append(text)
        return _Log()


def gui_methods():
    """Wyjmij prawdziwe metody GUI z app.pyw i zwiąż je z atrapą okna."""
    tree = ast.parse(APP, filename="app.pyw")
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "MainWindow")
    wanted = {"handle_event", "finished"}
    funcs = [n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name in wanted]
    assert {f.name for f in funcs} == wanted, [f.name for f in funcs]
    namespace = {"ev": ev}
    exec(compile(ast.Module(body=funcs, type_ignores=[]), "app_methods", "exec"), namespace)
    return namespace


def test_gui_status_state_machine():
    m = gui_methods()

    # 1. Logowanie wymagane -> status roboczy; potem sukces -> zielone ZALOGOWANO.
    w = FakeWindow()
    w.current_mode = "login"
    m["handle_event"](w, {"event": ev.EVENT_LOGIN_REQUIRED, "url": "https://portal/login"})
    assert w.status[0] == "busy" and "Chrome" in w.status[1]
    m["handle_event"](w, {"event": ev.EVENT_LOGIN_OK, "already_logged_in": False})
    assert w.status[0] == "ok" and "ZALOGOWANO" in w.status[1]
    assert w.login_confirmed is True

    # 2. Regresja 4.5: koniec procesu logowania NIE może zostawić pustego statusu.
    m["finished"](w, 0, None)
    assert w.status[0] == "ok" and "ZALOGOWANO" in w.status[1], w.status
    assert w.offered is True, "GUI musi zaproponować kolejny krok po zalogowaniu"
    assert w.running is False

    # 3. Sesja już aktywna (bez formularza logowania) też daje jasny status.
    w = FakeWindow()
    w.current_mode = "login"
    m["handle_event"](w, {"event": ev.EVENT_LOGIN_OK, "already_logged_in": True})
    m["finished"](w, 0, None)
    assert "ZALOGOWANO" in w.status[1]

    # 4. Tryb łańcuchowy: logowanie + skan w jednym procesie, bez pytania.
    w = FakeWindow()
    w.current_mode = "login"
    w.chained_run = True
    m["handle_event"](w, {"event": ev.EVENT_LOGIN_OK, "already_logged_in": False})
    assert "skanowania" in w.step
    m["handle_event"](w, {"event": ev.EVENT_SCAN_DONE, "count": 12})
    assert "12" in w.step
    m["finished"](w, 0, None)
    assert w.status[0] == "ok" and w.offered is False

    # 5. Błąd agenta: czerwony status z treścią błędu, bez fałszywego sukcesu.
    w = FakeWindow()
    w.current_mode = "run"
    m["handle_event"](w, {"event": ev.EVENT_FAILED, "error": "Sesja wygasła"})
    assert w.status[0] == "error" and "Sesja wygasła" in w.status[1]
    m["finished"](w, 1, None)
    assert w.status[0] == "error" and "Sesja wygasła" in w.status[1]

    # 6. Błąd bez zdarzenia (np. crash) nadal daje czytelny komunikat.
    w = FakeWindow()
    w.current_mode = "discover"
    m["finished"](w, 3, None)
    assert w.status[0] == "error" and "kod 3" in w.status[1]

    # 7. Pełny proces zakończony sukcesem.
    w = FakeWindow()
    w.current_mode = "run"
    m["handle_event"](w, {"event": ev.EVENT_PROCESS_START, "total": 5})
    m["handle_event"](w, {"event": ev.EVENT_LESSON_DONE, "index": 5, "total": 5, "title": "Lekcja 5", "status": "done"})
    assert "5/5" in w.step
    m["finished"](w, 0, None)
    assert w.status[0] == "ok" and "GOTOWE" in w.status[1]

    # 8. Koniec bez potwierdzenia logowania nie może zostawić paska „Uruchamiam…”.
    w = FakeWindow()
    w.current_mode = "login"
    w.status = ("busy", "Uruchamiam Chrome…")
    m["finished"](w, 0, None)
    assert w.status[0] != "busy", w.status
    print("PASS maszyna stanów statusu GUI (wykonana realnie)")


def test_login_detection_is_robust():
    """Regresja: pojedyncze pole hasła na podstronie NIE może znaczyć „logowanie"."""
    # Samo pole hasła (bez pola loginu, poza adresem logowania) nie wystarcza —
    # inaczej strony konta WooCommerce dawały fałszywe „Sesja wygasła".
    assert "input[type=\"password\"]:visible" in AGENT
    assert "def session_lost(" in AGENT
    assert "companion" in AGENT
    # Stara, nadwrażliwa reguła nie może wrócić.
    assert "if page.locator('input[type=\"password\"]').count()>0:return True" not in AGENT
    # Skanowanie i przetwarzanie muszą re-weryfikować, zanim zerwą przebieg.
    assert "if session_lost(page,start):raise" in AGENT
    assert "if session_lost(page,cfg[\"start_url\"]):raise" in AGENT
    print("PASS odporna detekcja logowania (brak fałszywego „sesja wygasła")


def test_scan_debug_dir_guarded():
    """Regresja: skan zapisywał do _debug nawet przy wyłączonym debugu (Errno 2)."""
    # debug_dir musi być None, gdy debug wyłączony — Path jest zawsze truthy,
    # więc stary jednolinijkowiec zawsze przechodził `if debug_dir:` i pisał do
    # nieistniejącego katalogu _debug.
    assert "debug_dir=None" in AGENT
    assert 'debug_dir=out_dir/"_debug"; debug_dir.mkdir(parents=True,exist_ok=True) if cfg.get("debug") else None' not in AGENT
    print("PASS skan nie pisze do _debug przy wyłączonym debugu")


def test_agent_forces_utf8_output():
    """Regresja: polskie znaki docierały do GUI jako „�" (stdout nie był UTF-8)."""
    assert "def configure_console(" in AGENT
    assert 'reconfigure(encoding="utf-8"' in AGENT
    assert "configure_console()" in AGENT  # wywołane w main()
    # GUI dodatkowo wymusza UTF-8 w środowisku procesu agenta.
    assert 'env.insert("PYTHONUTF8", "1")' in APP
    assert "QProcessEnvironment" in APP
    print("PASS agent wymusza UTF-8 (brak zniekształconych polskich znaków)")


def test_playback_record_transcribe_present():
    """Legalny łańcuch: odtwórz → nagraj ekran+audio → transkrybuj."""
    for needle in ("def record_fallback(", "def try_play(", "ScreenAudioRecorder",
                   "detect_drm", "class Transcriber"):
        assert needle in AGENT, needle
    # Materiały z DRM pozostają pomijane — bez obchodzenia zabezpieczeń.
    assert "protected" in AGENT
    print("PASS odtwarzanie → nagrywanie → transkrypcja (DRM pomijany)")


def test_gui_dark_sidebar_shell():
    """Nowa warstwa wizualna z makiet: ciemny motyw, sidebar, archiwum."""
    assert "DARK_QSS" in APP
    assert "app.setStyleSheet(DARK_QSS)" in APP
    assert "def build_sidebar(" in APP
    assert "self.profile_list = QListWidget(" in APP
    assert "def build_archive_page(" in APP
    assert "def refresh_archive(" in APP
    assert "self.material_list" in APP
    assert "def switch_view(" in APP
    # Profil wybierany w liście sidebaru, nie w combo.
    assert "profile_combo" not in APP
    assert "def current_profile_name(" in APP
    print("PASS ciemny sidebar + archiwum (makiety w aplikacji)")


def test_existing_features_preserved():
    """Dwa monitory, lokalna sesja Chrome, transkrypcja, dodatek Chrome."""
    for needle in ("record_monitor", "resolve_monitor_spec", "ScreenAudioRecorder",
                   'channel="chrome"', "launch_persistent_context", "WhisperModel",
                   "record_audio_device"):
        assert needle in AGENT, needle
    for needle in ("monitor_combo", "audio_device_combo", "whisper_model",
                   "open_chrome_addon", "browser_on_record_monitor", "b_login", "b_scan", "b_run"):
        assert needle in APP, needle
    assert (SRC / "chrome_extension" / "manifest.json").exists()
    assert (SRC / "native_host.py").exists()
    print("PASS zachowane dotychczasowe funkcje")


def main():
    import tempfile
    test_event_roundtrip()
    test_output_splitter_keeps_events_whole()
    with tempfile.TemporaryDirectory() as d:
        test_session_marker(Path(d))
    test_agent_reports_login()
    test_agent_can_chain_after_login()
    test_agent_stage_selection()
    test_gui_shows_status()
    test_gui_one_click_and_auto_scan()
    test_gui_status_state_machine()
    test_gui_dark_sidebar_shell()
    test_login_detection_is_robust()
    test_scan_debug_dir_guarded()
    test_agent_forces_utf8_output()
    test_playback_record_transcribe_present()
    test_existing_features_preserved()
    print("\nWSZYSTKIE TESTY PRZEPŁYWU LOGOWANIA: PASS")


if __name__ == "__main__":
    main()
