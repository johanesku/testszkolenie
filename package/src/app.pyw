from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

import mss
import soundcard as sc
import yaml
from PySide6.QtCore import QProcess, QProcessEnvironment, QTimer, QUrl
from PySide6.QtGui import QDesktopServices, QTextCursor
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QFileDialog, QFormLayout, QHBoxLayout,
    QLabel, QLineEdit, QMainWindow, QMessageBox, QPushButton, QPlainTextEdit,
    QSpinBox, QTabWidget, QVBoxLayout, QWidget
)

import session_events as ev

APP_DIR = (Path(sys.executable).resolve().parent if getattr(sys, 'frozen', False) else Path(__file__).resolve().parent)
PROFILES_DIR = Path.home() / ".course_archiver_app"
PROFILES_DIR.mkdir(parents=True, exist_ok=True)
PROFILES_FILE = PROFILES_DIR / "profiles.json"

STATUS_STYLES = {
    "idle": "background:#eceff1; color:#37474f; border:1px solid #cfd8dc;",
    "busy": "background:#fff3e0; color:#8a4b00; border:1px solid #ffcc80;",
    "ok": "background:#e6f4ea; color:#137333; border:1px solid #a8d5b5;",
    "error": "background:#fce8e6; color:#b3261e; border:1px solid #f2b8b5;",
}


def slugify(s: str) -> str:
    s = re.sub(r"[^A-Za-z0-9._-]+", "_", (s or "portal").strip())
    return s.strip("_") or "portal"


def default_profile():
    return {
        "portal_name": "Instytut Kryptografii",
        "start_url": "https://instytutkryptografii.pl/product/lessons/11009#lesson",
        "output_dir": str(Path.home() / "Documents" / "CourseArchiver" / "InstytutKryptografii"),
        "browser_profile_dir": str(PROFILES_DIR / "browser_profiles" / "instytut_kryptografii"),
        "lesson_url_regex": r"/product/lessons/",
        "link_selector": "",
        "max_lessons": 500,
        "crawl_depth": 3,
        "capture_seconds": 8,
        "download_media": True,
        "record_fallback": True,
        "record_fps": 10,
        "record_max_minutes": 180,
        "transcribe": True,
        "whisper_model": "large-v3",
        "whisper_language": "pl",
        "same_origin_only": True,
        "debug": False,
        "record_monitor": {"index": 1},
        "browser_on_record_monitor": True,
        "record_audio_device": "__default__",
        "auto_scan_after_login": True,
    }


class MainWindow(QMainWindow):
    def __init__(self, launch_args=None):
        super().__init__()
        self.launch_args = launch_args or argparse.Namespace(url=None, profile=None, action="open")
        self.setWindowTitle("Course Archiver & Transcriber")
        self.resize(1160, 860)
        self.proc = None
        self.current_mode = None
        self.login_confirmed = False
        self.error_reported = False
        self.chained_run = False
        self.splitter = ev.OutputSplitter()
        self.profiles = self.load_profiles()
        self.build_ui()
        self.refresh_profiles()
        if self.profiles:
            self.profile_combo.setCurrentIndex(0)
            self.load_selected_profile()
        else:
            self.apply_profile(default_profile())
        self.apply_external_launch()

    def load_profiles(self):
        try:
            return json.loads(PROFILES_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def save_profiles_file(self):
        PROFILES_FILE.write_text(json.dumps(self.profiles, ensure_ascii=False, indent=2), encoding="utf-8")

    def build_ui(self):
        root = QWidget(); self.setCentralWidget(root)
        main = QVBoxLayout(root)

        top = QHBoxLayout()
        self.profile_combo = QComboBox(); self.profile_combo.currentIndexChanged.connect(self.load_selected_profile)
        b_new = QPushButton("Nowy profil"); b_new.clicked.connect(self.new_profile)
        b_save = QPushButton("Zapisz profil"); b_save.clicked.connect(self.save_profile)
        b_delete = QPushButton("Usuń profil"); b_delete.clicked.connect(self.delete_profile)
        top.addWidget(QLabel("Portal / profil:")); top.addWidget(self.profile_combo, 1); top.addWidget(b_new); top.addWidget(b_save); top.addWidget(b_delete)
        main.addLayout(top)

        self.status_label = QLabel()
        self.status_label.setWordWrap(True)
        self.status_label.setStyleSheet("font-size:15px; font-weight:600; padding:11px 14px; border-radius:8px;")
        main.addWidget(self.status_label)
        self.set_status("idle", "Sesja nieznana — zacznij od „1. Zaloguj się”.")

        self.step_label = QLabel("")
        self.step_label.setWordWrap(True)
        self.step_label.setStyleSheet("color:#555; padding:0 4px 4px;")
        main.addWidget(self.step_label)

        tabs = QTabWidget(); main.addWidget(tabs, 1)

        basic = QWidget(); tabs.addTab(basic, "Podstawowe")
        form = QFormLayout(basic)
        self.portal_name = QLineEdit(); self.start_url = QLineEdit(); self.output_dir = QLineEdit(); self.browser_profile_dir = QLineEdit()
        form.addRow("Nazwa portalu:", self.portal_name)
        form.addRow("URL startowy / kursu:", self.start_url)
        form.addRow("Katalog wynikowy:", self.dir_picker(self.output_dir))
        form.addRow("Profil przeglądarki:", self.dir_picker(self.browser_profile_dir))
        self.download_media = QCheckBox("Najpierw próbuj pobrać oryginalny plik/strumień")
        self.record_fallback = QCheckBox("Jeśli pobranie się nie uda: odtwórz i nagraj lokalnie")
        self.transcribe = QCheckBox("Twórz pełną transkrypcję dla każdego materiału")
        form.addRow("", self.download_media); form.addRow("", self.record_fallback); form.addRow("", self.transcribe)
        note = QLabel("Logowanie odbywa się w normalnym oknie Google Chrome. Sesja/cookies są zapisywane lokalnie dla profilu; hasło nie trafia do konfiguracji. "
                      "Po udanym logowaniu pasek statusu u góry pokaże „ZALOGOWANO”, a aplikacja może od razu przejść do skanowania kursu.")
        note.setWordWrap(True); note.setStyleSheet("color:#555"); form.addRow("Logowanie:", note)

        tr = QWidget(); tabs.addTab(tr, "Transkrypcja")
        trf = QFormLayout(tr)
        self.whisper_model = QComboBox(); self.whisper_model.addItems(["large-v3", "medium", "small", "base"])
        self.whisper_language = QComboBox(); self.whisper_language.setEditable(True); self.whisper_language.addItems(["pl", "en", "de", "auto"])
        trf.addRow("Model Whisper:", self.whisper_model); trf.addRow("Język:", self.whisper_language)
        trnote = QLabel("large-v3 = najwyższa jakość, ale większe wymagania. Transkrypcja odbywa się lokalnie.")
        trnote.setWordWrap(True); trf.addRow("", trnote)

        disc = QWidget(); tabs.addTab(disc, "Wykrywanie materiałów")
        df = QFormLayout(disc)
        self.lesson_url_regex = QLineEdit(); self.link_selector = QLineEdit()
        self.max_lessons = QSpinBox(); self.max_lessons.setRange(1, 10000)
        self.crawl_depth = QSpinBox(); self.crawl_depth.setRange(0, 10)
        self.same_origin_only = QCheckBox("Nie wychodź poza domenę portalu")
        df.addRow("Regex URL lekcji (opcjonalnie):", self.lesson_url_regex)
        df.addRow("Selektor CSS linków (opcjonalnie):", self.link_selector)
        df.addRow("Maks. liczba materiałów:", self.max_lessons); df.addRow("Głębokość skanowania AUTO:", self.crawl_depth); df.addRow("", self.same_origin_only)
        auto = QLabel("Puste regex + selector = tryb AUTO. Dla nietypowego LMS ustaw regex lub selektor bez zmiany kodu.")
        auto.setWordWrap(True); df.addRow("Tryb AUTO:", auto)

        rec = QWidget(); tabs.addTab(rec, "Nagrywanie / 2 monitory")
        rf = QFormLayout(rec)
        self.monitor_combo = QComboBox(); self.refresh_monitor_list()
        self.browser_on_record_monitor = QCheckBox("Otwieraj i utrzymuj Chromium na wybranym monitorze")
        self.audio_device_combo = QComboBox(); self.refresh_audio_devices()
        self.capture_seconds = QSpinBox(); self.capture_seconds.setRange(2, 60)
        self.record_fps = QSpinBox(); self.record_fps.setRange(2, 30)
        self.record_max_minutes = QSpinBox(); self.record_max_minutes.setRange(1, 600)
        rf.addRow("Monitor odtwarzania/nagrywania:", self.monitor_combo)
        rf.addRow("", self.browser_on_record_monitor)
        rf.addRow("Audio loopback do nagrania:", self.audio_device_combo)
        rf.addRow("Czas wykrywania źródła [s]:", self.capture_seconds)
        rf.addRow("FPS nagrywania ekranu:", self.record_fps)
        rf.addRow("Maks. czas jednego nagrania [min]:", self.record_max_minutes)
        recnote = QLabel(
            "Obraz jest przechwytywany wyłącznie z wybranego monitora, więc na drugim możesz normalnie pracować. "
            "Audio loopback dotyczy wybranego urządzenia wyjściowego; jeśli równolegle odtworzysz dźwięk na tym samym urządzeniu, może trafić do nagrania. "
            "Najlepsza izolacja: osobne wyjście audio dla Chromium (np. HDMI monitora 2) i inne wyjście do Twojej pracy."
        )
        recnote.setWordWrap(True); recnote.setStyleSheet("color:#8a4b00"); rf.addRow("Ważne:", recnote)

        adv = QWidget(); tabs.addTab(adv, "Zaawansowane")
        af = QFormLayout(adv)
        self.debug = QCheckBox("Zapisuj diagnostykę wykrywania"); af.addRow("", self.debug)
        ext_note = QLabel("Rozszerzenie Chrome może przekazać bieżącą kartę do tej aplikacji przez lokalny Native Messaging Host. Nie przesyła loginów ani haseł.")
        ext_note.setWordWrap(True); af.addRow("Chrome addon:", ext_note)
        self.b_addon = QPushButton("Otwórz instalację dodatku Chrome")
        self.b_addon.clicked.connect(self.open_chrome_addon)
        af.addRow("", self.b_addon)

        oneclick = QHBoxLayout()
        self.b_all = QPushButton("▶  ZRÓB WSZYSTKO  —  logowanie → skan → pobieranie → transkrypcja")
        self.b_all.setMinimumHeight(44)
        self.b_all.setStyleSheet("font-size:15px; font-weight:700;")
        self.b_all.clicked.connect(lambda: self.start_agent("run"))
        self.auto_scan_after_login = QCheckBox("Po udanym logowaniu automatycznie skanuj kurs")
        self.auto_scan_after_login.setChecked(True)
        oneclick.addWidget(self.b_all, 1); oneclick.addWidget(self.auto_scan_after_login)
        main.addLayout(oneclick)

        actions = QHBoxLayout()
        self.b_login = QPushButton("1. Zaloguj się")
        self.b_scan = QPushButton("2. Skanuj strukturę")
        self.b_run = QPushButton("3. Pobierz i transkrybuj")
        self.b_stop = QPushButton("Zatrzymaj")
        self.b_open = QPushButton("Otwórz katalog wynikowy")
        self.b_login.clicked.connect(lambda: self.start_agent("login")); self.b_scan.clicked.connect(lambda: self.start_agent("discover")); self.b_run.clicked.connect(lambda: self.start_agent("run"))
        self.b_stop.clicked.connect(self.stop_agent); self.b_open.clicked.connect(self.open_output)
        actions.addWidget(self.b_login); actions.addWidget(self.b_scan); actions.addWidget(self.b_run); actions.addWidget(self.b_stop); actions.addStretch(1); actions.addWidget(self.b_open)
        main.addLayout(actions)

        self.log = QPlainTextEdit(); self.log.setReadOnly(True); self.log.setMaximumBlockCount(5000); main.addWidget(self.log, 1)
        self.set_running(False)

    def refresh_monitor_list(self):
        self.monitor_combo.clear()
        try:
            with mss.mss() as sct:
                for idx, mon in enumerate(sct.monitors[1:], 1):
                    data = {"index": idx, "left": int(mon["left"]), "top": int(mon["top"]), "width": int(mon["width"]), "height": int(mon["height"])}
                    label = f"Monitor {idx} — {data['width']}×{data['height']} @ ({data['left']},{data['top']})"
                    self.monitor_combo.addItem(label, data)
        except Exception as e:
            self.monitor_combo.addItem(f"Monitor 1 (nie udało się odczytać geometrii: {e})", {"index": 1})

    def refresh_audio_devices(self):
        self.audio_device_combo.clear(); self.audio_device_combo.addItem("Domyślne urządzenie systemowe", "__default__")
        try:
            for sp in sc.all_speakers():
                name = str(sp.name)
                self.audio_device_combo.addItem(name, name)
        except Exception:
            pass

    def dir_picker(self, line):
        w = QWidget(); l = QHBoxLayout(w); l.setContentsMargins(0,0,0,0); b = QPushButton("Wybierz…")
        def pick():
            d = QFileDialog.getExistingDirectory(self, "Wybierz katalog", line.text() or str(Path.home()))
            if d: line.setText(d)
        b.clicked.connect(pick); l.addWidget(line,1); l.addWidget(b); return w

    def refresh_profiles(self, select=None):
        self.profile_combo.blockSignals(True); self.profile_combo.clear()
        for name in sorted(self.profiles): self.profile_combo.addItem(name)
        if select and select in self.profiles: self.profile_combo.setCurrentText(select)
        self.profile_combo.blockSignals(False)

    def new_profile(self):
        p = default_profile(); p["portal_name"] = "Nowy portal"; p["start_url"] = ""
        p["output_dir"] = str(Path.home()/"Documents"/"CourseArchiver"/"NowyPortal")
        p["browser_profile_dir"] = str(PROFILES_DIR/"browser_profiles"/"nowy_portal"); self.apply_profile(p)

    def selected_monitor(self):
        data = self.monitor_combo.currentData()
        return data if isinstance(data, dict) else {"index": max(1, self.monitor_combo.currentIndex()+1)}

    def collect_profile(self):
        return {
            "portal_name": self.portal_name.text().strip() or "Portal",
            "start_url": self.start_url.text().strip(),
            "output_dir": self.output_dir.text().strip(),
            "browser_profile_dir": self.browser_profile_dir.text().strip(),
            "lesson_url_regex": self.lesson_url_regex.text().strip(),
            "link_selector": self.link_selector.text().strip(),
            "max_lessons": self.max_lessons.value(), "crawl_depth": self.crawl_depth.value(), "capture_seconds": self.capture_seconds.value(),
            "download_media": self.download_media.isChecked(), "record_fallback": self.record_fallback.isChecked(), "record_fps": self.record_fps.value(),
            "record_max_minutes": self.record_max_minutes.value(), "transcribe": self.transcribe.isChecked(), "whisper_model": self.whisper_model.currentText(),
            "whisper_language": self.whisper_language.currentText(), "same_origin_only": self.same_origin_only.isChecked(), "debug": self.debug.isChecked(),
            "record_monitor": self.selected_monitor(), "browser_on_record_monitor": self.browser_on_record_monitor.isChecked(),
            "record_audio_device": self.audio_device_combo.currentData() or "__default__",
            "auto_scan_after_login": self.auto_scan_after_login.isChecked(),
        }

    def apply_profile(self, p):
        self.portal_name.setText(p.get("portal_name", "")); self.start_url.setText(p.get("start_url", "")); self.output_dir.setText(p.get("output_dir", "")); self.browser_profile_dir.setText(p.get("browser_profile_dir", ""))
        self.lesson_url_regex.setText(p.get("lesson_url_regex", "")); self.link_selector.setText(p.get("link_selector", ""))
        self.max_lessons.setValue(int(p.get("max_lessons",500))); self.crawl_depth.setValue(int(p.get("crawl_depth",3))); self.capture_seconds.setValue(int(p.get("capture_seconds",8)))
        self.record_fps.setValue(int(p.get("record_fps",10))); self.record_max_minutes.setValue(int(p.get("record_max_minutes",180)))
        self.download_media.setChecked(bool(p.get("download_media",True))); self.record_fallback.setChecked(bool(p.get("record_fallback",True))); self.transcribe.setChecked(bool(p.get("transcribe",True)))
        self.same_origin_only.setChecked(bool(p.get("same_origin_only",True))); self.debug.setChecked(bool(p.get("debug",False))); self.browser_on_record_monitor.setChecked(bool(p.get("browser_on_record_monitor",True)))
        self.whisper_model.setCurrentText(p.get("whisper_model","large-v3")); self.whisper_language.setCurrentText(p.get("whisper_language","pl"))
        target = p.get("record_monitor") or {"index":1}; idx = int(target.get("index",1))
        for i in range(self.monitor_combo.count()):
            data = self.monitor_combo.itemData(i) or {}
            if all(str(data.get(k)) == str(target.get(k)) for k in ("left","top","width","height") if k in target):
                self.monitor_combo.setCurrentIndex(i); break
            if int(data.get("index",0)) == idx: self.monitor_combo.setCurrentIndex(i)
        audio = p.get("record_audio_device","__default__")
        for i in range(self.audio_device_combo.count()):
            if self.audio_device_combo.itemData(i) == audio: self.audio_device_combo.setCurrentIndex(i); break
        self.auto_scan_after_login.setChecked(bool(p.get("auto_scan_after_login", True)))
        self.refresh_session_status()

    def load_selected_profile(self):
        name = self.profile_combo.currentText()
        if name in self.profiles: self.apply_profile(self.profiles[name])

    def save_profile(self):
        p = self.collect_profile(); name = p["portal_name"]
        if not p["start_url"]:
            QMessageBox.warning(self,"Brak URL","Podaj URL startowy portalu/kursu."); return False
        if not p["browser_profile_dir"]:
            p["browser_profile_dir"] = str(PROFILES_DIR/"browser_profiles"/slugify(name)); self.browser_profile_dir.setText(p["browser_profile_dir"])
        self.profiles[name] = p; self.save_profiles_file(); self.refresh_profiles(name); self.log.appendPlainText(f"Zapisano profil: {name}"); return True

    def delete_profile(self):
        name = self.profile_combo.currentText()
        if name and name in self.profiles and QMessageBox.question(self,"Usuń profil",f"Usunąć ustawienia profilu '{name}'?\nSesja przeglądarki i pobrane pliki pozostaną na dysku.") == QMessageBox.Yes:
            del self.profiles[name]; self.save_profiles_file(); self.refresh_profiles();
            if self.profiles: self.load_selected_profile()

    def session_file(self):
        return ev.session_marker_path(PROFILES_DIR, slugify(self.portal_name.text().strip() or "Portal"))

    def refresh_session_status(self):
        """Pokaż stan sesji zapamiętany po ostatnim udanym logowaniu."""
        if self.proc and self.proc.state() != QProcess.NotRunning: return
        marker = ev.read_session_marker(self.session_file())
        if marker and marker.get("logged_in"):
            self.login_confirmed = True
            self.set_status("ok", f"ZALOGOWANO — sesja zapisana lokalnie (ostatnie potwierdzenie: {marker.get('checked_at','?')}).")
        else:
            self.login_confirmed = False
            self.set_status("idle", "Sesja nieznana — zacznij od „1. Zaloguj się”.")

    def set_status(self, kind, text):
        self.status_label.setStyleSheet(
            "font-size:15px; font-weight:600; padding:11px 14px; border-radius:8px;" + STATUS_STYLES.get(kind, STATUS_STYLES["idle"])
        )
        self.status_label.setText(text)

    def set_step(self, text):
        self.step_label.setText(text)

    def make_runtime_config(self):
        p = self.collect_profile()
        if not p["start_url"] or not p["output_dir"]: raise ValueError("URL startowy i katalog wynikowy są wymagane.")
        if not p["browser_profile_dir"]: p["browser_profile_dir"] = str(PROFILES_DIR/"browser_profiles"/slugify(p["portal_name"]))
        p["session_state_file"] = str(self.session_file())
        run_dir = PROFILES_DIR / "runtime"; run_dir.mkdir(parents=True, exist_ok=True)
        path = run_dir / (slugify(p["portal_name"]) + ".yaml"); path.write_text(yaml.safe_dump(p, allow_unicode=True, sort_keys=False), encoding="utf-8"); return path

    def start_agent(self, mode, persist=True):
        if self.proc and self.proc.state() != QProcess.NotRunning: return
        try: cfg = self.make_runtime_config()
        except Exception as e: QMessageBox.warning(self,"Brak danych",str(e)); return
        if persist and not self.save_profile(): return
        if getattr(sys, "frozen", False):
            candidates = [
                APP_DIR.parent / "Agent" / "CourseArchiverAgent.exe",
                APP_DIR / "CourseArchiverAgent.exe",
            ]
            agent_exe = next((x for x in candidates if x.exists()), candidates[0])
            program = str(agent_exe)
            args = ["--config", str(cfg)]
            workdir = str(agent_exe.parent)
        else:
            program = sys.executable
            args = [str(APP_DIR / "agent_generic.py"), "--config", str(cfg)]
            workdir = str(APP_DIR)
        self.chained_run = False
        if mode == "login":
            args.append("--login-only")
            if self.auto_scan_after_login.isChecked():
                args += ["--after-login", ev.STAGE_DISCOVER]
                self.chained_run = True
        elif mode == "discover": args.append("--discover-only")
        self.current_mode = mode
        self.login_confirmed = False
        self.error_reported = False
        self.splitter = ev.OutputSplitter()
        self.proc = QProcess(self); self.proc.setProgram(program); self.proc.setArguments(args); self.proc.setWorkingDirectory(workdir); self.proc.setProcessChannelMode(QProcess.MergedChannels)
        env = QProcessEnvironment.systemEnvironment()
        env.insert("PYTHONUTF8", "1"); env.insert("PYTHONIOENCODING", "utf-8")
        self.proc.setProcessEnvironment(env)
        self.proc.readyReadStandardOutput.connect(self.read_output); self.proc.finished.connect(self.finished)
        self.log.appendPlainText("\n===== START =====")
        self.set_status("busy", "Uruchamiam Chrome… za chwilę otworzy się okno przeglądarki.")
        self.set_step("")
        self.proc.start(); self.set_running(True)

    def read_output(self):
        if not self.proc: return
        raw = bytes(self.proc.readAllStandardOutput()).decode("utf-8", errors="replace")
        if raw: self.consume_lines(self.splitter.feed(raw))

    def flush_output(self):
        self.consume_lines(self.splitter.flush())

    def consume_lines(self, lines):
        visible = []
        for line in lines:
            evt = ev.parse_event(line)
            if evt is None:
                visible.append(line)
            else:
                self.handle_event(evt)
                text = ev.describe(evt)
                if text: visible.append(">>> " + text)
        if visible:
            self.log.moveCursor(QTextCursor.End); self.log.insertPlainText("\n".join(visible) + "\n"); self.log.ensureCursorVisible()

    def handle_event(self, evt):
        name = evt.get("event")
        if name == ev.EVENT_LOGIN_REQUIRED:
            self.set_status("busy", "LOGOWANIE — zaloguj się w otwartym oknie Chrome. Aplikacja czeka i sama wykryje koniec logowania.")
        elif name == ev.EVENT_LOGIN_OK:
            self.login_confirmed = True
            self.set_status("ok", ev.describe(evt))
            if self.chained_run:
                self.set_step("Automatyczne przejście do skanowania kursu…")
        elif name == ev.EVENT_LOGIN_FAILED:
            self.error_reported = True
            self.set_status("error", ev.describe(evt))
        elif name == ev.EVENT_SCAN_START:
            self.set_step("Skanuję strukturę kursu…")
        elif name == ev.EVENT_SCAN_DONE:
            self.set_step(f"Znaleziono materiałów: {evt.get('count', 0)}.")
        elif name == ev.EVENT_PROCESS_START:
            self.set_step(f"Pobieranie i transkrypcja: 0/{evt.get('total', 0)}.")
        elif name == ev.EVENT_LESSON_DONE:
            self.set_step(f"Materiał {evt.get('index', 0)}/{evt.get('total', 0)}: {evt.get('title') or ''}")
        elif name == ev.EVENT_FAILED:
            self.error_reported = True
            self.set_status("error", ev.describe(evt))

    def finished(self, code, status):
        self.read_output(); self.flush_output()
        self.log.appendPlainText(f"\n===== KONIEC (kod {code}) =====\n"); self.set_running(False)
        mode, chained = self.current_mode, self.chained_run
        self.current_mode = None; self.chained_run = False
        if code != 0:
            if not self.error_reported:
                self.set_status("error", f"Proces zakończył się błędem (kod {code}). Szczegóły w logu poniżej.")
            return
        if mode == "login" and self.login_confirmed:
            if chained:
                self.set_status("ok", "ZALOGOWANO — skanowanie kursu zakończone. Możesz uruchomić „3. Pobierz i transkrybuj”.")
                return
            self.set_status("ok", "ZALOGOWANO — sesja zapisana lokalnie.")
            self.offer_next_step()
        elif mode == "discover":
            self.set_status("ok", "Skanowanie zakończone. Możesz uruchomić „3. Pobierz i transkrybuj”.")
        elif mode == "run":
            self.set_status("ok", "GOTOWE — materiały i transkrypcje są w katalogu wynikowym.")
        else:
            # Proces zakończył się bez potwierdzenia logowania: nie zostawiaj
            # użytkownika z paskiem „Uruchamiam Chrome…”, tak jak robiła 4.5.
            self.refresh_session_status()

    def offer_next_step(self):
        answer = QMessageBox.question(
            self, "Zalogowano",
            "Logowanie zakończone powodzeniem, sesja została zapisana lokalnie.\n\n"
            "Uruchomić teraz skanowanie struktury kursu?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes,
        )
        if answer == QMessageBox.Yes:
            self.start_agent("discover")

    def stop_agent(self):
        if self.proc and self.proc.state() != QProcess.NotRunning:
            self.error_reported = True
            self.set_status("idle", "Zatrzymano na żądanie użytkownika.")
            self.proc.terminate(); QTimer.singleShot(3000, self.kill_if_needed)

    def kill_if_needed(self):
        if self.proc and self.proc.state() != QProcess.NotRunning: self.proc.kill()

    def set_running(self, running):
        self.b_login.setEnabled(not running); self.b_scan.setEnabled(not running); self.b_run.setEnabled(not running)
        self.b_all.setEnabled(not running); self.b_stop.setEnabled(running)

    def open_output(self):
        p = Path(os.path.expandvars(self.output_dir.text())).expanduser(); p.mkdir(parents=True, exist_ok=True); QDesktopServices.openUrl(QUrl.fromLocalFile(str(p.resolve())))


    def open_chrome_addon(self):
        if getattr(sys, "frozen", False):
            extension_dir = APP_DIR.parent / "ChromeExtension"
        else:
            extension_dir = APP_DIR / "chrome_extension"
        if not extension_dir.exists():
            QMessageBox.warning(self, "Brak dodatku", f"Nie znaleziono katalogu dodatku Chrome:\n{extension_dir}")
            return
        chrome_candidates = [
            Path(os.environ.get("PROGRAMFILES", "")) / "Google" / "Chrome" / "Application" / "chrome.exe",
            Path(os.environ.get("PROGRAMFILES(X86)", "")) / "Google" / "Chrome" / "Application" / "chrome.exe",
            Path(os.environ.get("LOCALAPPDATA", "")) / "Google" / "Chrome" / "Application" / "chrome.exe",
        ]
        chrome = next((x for x in chrome_candidates if x.exists()), None)
        try:
            if chrome:
                QProcess.startDetached(str(chrome), ["chrome://extensions/"])
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(extension_dir.resolve())))
        except Exception as e:
            QMessageBox.warning(self, "Chrome addon", str(e))
            return
        QMessageBox.information(
            self, "Dodatek Chrome",
            "Chrome i folder dodatku zostały otwarte.\n\n"
            "1. W Chrome włącz Tryb dewelopera.\n"
            "2. Kliknij 'Załaduj rozpakowane'.\n"
            "3. Wskaż otwarty folder ChromeExtension.\n\n"
            "To jest jedyny krok dodatku, którego Chrome nie pozwala automatyzować dla nieopublikowanego rozszerzenia."
        )

    def apply_external_launch(self):
        a = self.launch_args
        if getattr(a, "profile", None) and a.profile in self.profiles:
            self.profile_combo.setCurrentText(a.profile); self.apply_profile(self.profiles[a.profile])
        if getattr(a, "url", None): self.start_url.setText(a.url)
        action = getattr(a, "action", "open") or "open"
        if action in ("login", "discover", "run"):
            self.log.appendPlainText(f"Uruchomiono z rozszerzenia Chrome. Akcja: {action}")
            QTimer.singleShot(700, lambda: self.start_agent(action, persist=False))


def parse_args(argv):
    ap = argparse.ArgumentParser(add_help=False)
    ap.add_argument("--url"); ap.add_argument("--profile"); ap.add_argument("--action", choices=["open","login","discover","run"], default="open")
    args, _ = ap.parse_known_args(argv[1:]); return args


def main():
    args = parse_args(sys.argv)
    app = QApplication(sys.argv); app.setApplicationName("Course Archiver & Transcriber")
    win = MainWindow(args); win.show(); sys.exit(app.exec())


if __name__ == "__main__": main()
