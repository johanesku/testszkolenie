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
from PySide6.QtCore import Qt, QProcess, QProcessEnvironment, QTimer, QUrl
from PySide6.QtGui import QColor, QDesktopServices, QIcon, QPainter, QPixmap, QTextCursor
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QFileDialog, QFormLayout, QFrame, QHBoxLayout,
    QLabel, QLineEdit, QListWidget, QListWidgetItem, QMainWindow, QMessageBox,
    QPushButton, QPlainTextEdit, QSpinBox, QSplitter, QStackedWidget, QTabWidget,
    QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget
)

import session_events as ev

APP_DIR = (Path(sys.executable).resolve().parent if getattr(sys, 'frozen', False) else Path(__file__).resolve().parent)
PROFILES_DIR = Path.home() / ".course_archiver_app"
PROFILES_DIR.mkdir(parents=True, exist_ok=True)
PROFILES_FILE = PROFILES_DIR / "profiles.json"

# Duży pasek statusu pod nagłówkiem — jeden kolor na stan pracy.
STATUS_STYLES = {
    "idle": "background:#171A20; color:#9AA4B2; border:1px solid #24282F;",
    "busy": "background:rgba(233,162,59,0.10); color:#F0B45C; border:1px solid rgba(233,162,59,0.30);",
    "ok": "background:rgba(85,197,122,0.10); color:#6FDC96; border:1px solid rgba(85,197,122,0.30);",
    "error": "background:rgba(229,72,77,0.10); color:#FF9AA0; border:1px solid rgba(229,72,77,0.32);",
}

# Mały chip w nagłówku (tekst, styl tła/koloru).
CHIP_STYLES = {
    "idle": ("BRAK SESJI", "background:rgba(126,136,150,0.14); color:#9AA4B2;"),
    "busy": ("PRACUJE…", "background:rgba(233,162,59,0.16); color:#F0B45C;"),
    "ok": ("ZALOGOWANO", "background:rgba(85,197,122,0.16); color:#6FDC96;"),
    "error": ("BŁĄD", "background:rgba(229,72,77,0.16); color:#FF9AA0;"),
}

# Kolory i etykiety końcowego statusu materiału (spójne z makietą „System statusów").
MATERIAL_COLORS = {
    "done": "#6FDC96", "protected": "#F0B45C", "skipped": "#9AA4B2",
    "media_unavailable": "#FF9AA0", "error": "#FF9AA0",
}
MATERIAL_LABELS = {
    "done": "GOTOWE", "protected": "CHRONIONE", "skipped": "POMINIĘTE",
    "media_unavailable": "BRAK MEDIÓW", "error": "BŁĄD",
}

DARK_QSS = """
* { font-family: 'Segoe UI', 'Segoe UI Variable', sans-serif; }
QMainWindow, QWidget { background: #0E1014; color: #E9ECF1; font-size: 13px; }
QWidget#sidebar { background: #15181D; border-right: 1px solid #24282F; }
QWidget#header { background: #0E1014; border-bottom: 1px solid #24282F; }
QLabel#brandMark { background: #3DD6B5; color: #0C1316; border-radius: 7px; font-weight: 700; font-size: 13px; }
QLabel#brand { font-size: 14px; font-weight: 600; }
QLabel#brandVer { color: #7E8896; font-size: 10px; }
QLabel#caption { color: #7E8896; font-size: 10px; font-weight: 600; }
QLabel#title { font-size: 17px; font-weight: 600; }
QLabel#chip { padding: 3px 10px; border-radius: 9px; font-size: 11px; font-weight: 600; }
QLabel#hint { color: #7E8896; font-size: 11px; }
QLabel#warn { color: #F0B45C; font-size: 12px; }

QListWidget#profiles { background: transparent; border: 0; outline: 0; }
QListWidget#profiles::item { padding: 8px 10px; border-radius: 7px; color: #9AA4B2; margin: 1px 4px; }
QListWidget#profiles::item:selected { background: #1E2229; color: #E9ECF1; }
QListWidget#profiles::item:hover { background: #191D23; }
QListWidget#materials { background: #0F1216; border: 1px solid #24282F; border-radius: 10px; outline: 0; }
QListWidget#materials::item { padding: 6px 8px; }

QPushButton { background: #1B1F26; color: #C6CCD5; border: 1px solid #333944; border-radius: 8px; padding: 8px 14px; font-size: 13px; }
QPushButton:hover { background: #222732; border-color: #3A414C; }
QPushButton:disabled { color: #5A626E; border-color: #262B32; background: #16191F; }
QPushButton#primary { background: #3DD6B5; color: #0C1316; border: 0; font-weight: 700; }
QPushButton#primary:hover { background: #52E0C3; }
QPushButton#primary:disabled { background: #234942; color: #5F7B74; }
QPushButton#danger { background: rgba(229,72,77,0.12); color: #FF9AA0; border: 1px solid rgba(229,72,77,0.36); }
QPushButton#danger:disabled { color: #6B4145; border-color: #3A2A2C; background: #1A1416; }
QPushButton#nav { text-align: left; background: transparent; border: 0; color: #9AA4B2; padding: 9px 12px; }
QPushButton#nav:checked { background: #1E2229; color: #E9ECF1; }
QPushButton#newprofile { text-align: left; border-style: dashed; color: #9AA4B2; }

QLineEdit, QComboBox, QSpinBox, QPlainTextEdit, QTreeWidget { background: #15181D; color: #E9ECF1; border: 1px solid #2C313A; border-radius: 8px; padding: 7px 10px; selection-background-color: #2A5A52; }
QLineEdit:focus, QComboBox:focus, QSpinBox:focus { border-color: #3DD6B5; }
QComboBox::drop-down { border: 0; width: 20px; }
QComboBox QAbstractItemView { background: #15181D; color: #E9ECF1; border: 1px solid #2C313A; selection-background-color: #1E2229; }
QPlainTextEdit { font-family: 'Consolas', 'Cascadia Mono', monospace; font-size: 12px; }

QTabWidget::pane { border: 0; border-top: 1px solid #24282F; top: -1px; }
QTabBar::tab { background: transparent; color: #98A1AE; padding: 8px 14px; border: 0; margin-right: 2px; }
QTabBar::tab:selected { color: #E9ECF1; border-bottom: 2px solid #3DD6B5; }
QTabBar::tab:hover { color: #C6CCD5; }

QCheckBox { color: #C6CCD5; spacing: 8px; }
QCheckBox::indicator { width: 16px; height: 16px; border-radius: 4px; border: 1px solid #3A414C; background: #15181D; }
QCheckBox::indicator:checked { background: #3DD6B5; border-color: #3DD6B5; }

QTreeWidget::item { padding: 4px 2px; color: #C6CCD5; }
QTreeWidget::item:selected { background: #1E2229; color: #E9ECF1; }
QHeaderView::section { background: #15181D; color: #7E8896; border: 0; padding: 6px; }
QSplitter::handle { background: #24282F; }

QScrollBar:vertical { background: transparent; width: 10px; margin: 2px; }
QScrollBar::handle:vertical { background: #2C313A; border-radius: 5px; min-height: 24px; }
QScrollBar::handle:vertical:hover { background: #3A414C; }
QScrollBar:horizontal { background: transparent; height: 10px; margin: 2px; }
QScrollBar::handle:horizontal { background: #2C313A; border-radius: 5px; min-width: 24px; }
QScrollBar::add-line, QScrollBar::sub-line { height: 0; width: 0; }
QMenu { background: #15181D; color: #E9ECF1; border: 1px solid #2C313A; }
QMenu::item:selected { background: #1E2229; }
QToolTip { background: #1E2229; color: #E9ECF1; border: 1px solid #333944; }
"""


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
        self.resize(1240, 860)
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
            self.profile_list.setCurrentRow(0)
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

    # ---------------------------------------------------------------- UI build

    def build_ui(self):
        root = QWidget(); self.setCentralWidget(root)
        outer = QHBoxLayout(root); outer.setContentsMargins(0, 0, 0, 0); outer.setSpacing(0)
        outer.addWidget(self.build_sidebar())

        content = QWidget(); cv = QVBoxLayout(content); cv.setContentsMargins(0, 0, 0, 0); cv.setSpacing(0)
        cv.addWidget(self.build_header())

        body = QWidget(); bl = QVBoxLayout(body); bl.setContentsMargins(24, 16, 24, 20); bl.setSpacing(10)

        self.status_label = QLabel(); self.status_label.setWordWrap(True)
        bl.addWidget(self.status_label)
        self.step_label = QLabel(""); self.step_label.setObjectName("hint"); self.step_label.setWordWrap(True)
        bl.addWidget(self.step_label)

        self.stack = QStackedWidget()
        self.stack.addWidget(self.build_config_page())
        self.stack.addWidget(self.build_archive_page())
        bl.addWidget(self.stack, 1)

        cv.addWidget(body, 1)
        outer.addWidget(content, 1)

        self.set_status("idle", "Sesja nieznana — zacznij od „1. Zaloguj się”.")
        self.set_running(False)

    def build_sidebar(self):
        bar = QWidget(); bar.setObjectName("sidebar"); bar.setFixedWidth(244)
        v = QVBoxLayout(bar); v.setContentsMargins(12, 16, 12, 12); v.setSpacing(8)

        brand = QHBoxLayout(); brand.setSpacing(10)
        mark = QLabel("◆"); mark.setObjectName("brandMark"); mark.setFixedSize(26, 26); mark.setAlignment(Qt.AlignCenter)
        names = QVBoxLayout(); names.setSpacing(0)
        n1 = QLabel("Course Archiver"); n1.setObjectName("brand")
        n2 = QLabel("4.6"); n2.setObjectName("brandVer")
        names.addWidget(n1); names.addWidget(n2)
        brand.addWidget(mark); brand.addLayout(names); brand.addStretch(1)
        v.addLayout(brand)

        cap = QLabel("PORTALE"); cap.setObjectName("caption"); v.addWidget(cap)

        self.profile_list = QListWidget(); self.profile_list.setObjectName("profiles")
        self.profile_list.currentItemChanged.connect(lambda *a: self.load_selected_profile())
        v.addWidget(self.profile_list, 1)

        b_new = QPushButton("＋  Nowy profil portalu"); b_new.setObjectName("newprofile"); b_new.clicked.connect(self.new_profile)
        v.addWidget(b_new)

        sep = QFrame(); sep.setFrameShape(QFrame.HLine); sep.setStyleSheet("color:#24282F;"); v.addWidget(sep)

        self.nav_config = QPushButton("Konfiguracja"); self.nav_config.setObjectName("nav"); self.nav_config.setCheckable(True); self.nav_config.setChecked(True)
        self.nav_archive = QPushButton("Archiwum lokalne"); self.nav_archive.setObjectName("nav"); self.nav_archive.setCheckable(True)
        self.nav_config.clicked.connect(lambda: self.switch_view(0))
        self.nav_archive.clicked.connect(lambda: self.switch_view(1))
        v.addWidget(self.nav_config); v.addWidget(self.nav_archive)
        return bar

    def build_header(self):
        head = QWidget(); head.setObjectName("header"); head.setFixedHeight(64)
        h = QHBoxLayout(head); h.setContentsMargins(24, 0, 24, 0); h.setSpacing(12)
        self.title_label = QLabel("Course Archiver"); self.title_label.setObjectName("title")
        self.status_chip = QLabel(); self.status_chip.setObjectName("chip")
        h.addWidget(self.title_label); h.addWidget(self.status_chip); h.addStretch(1)
        b_save = QPushButton("Zapisz profil"); b_save.clicked.connect(self.save_profile)
        self.b_all = QPushButton("▶  Zrób wszystko"); self.b_all.setObjectName("primary")
        self.b_all.setToolTip("ZRÓB WSZYSTKO — logowanie → skan → pobieranie → transkrypcja")
        self.b_all.clicked.connect(lambda: self.start_agent("run"))
        h.addWidget(b_save); h.addWidget(self.b_all)
        return head

    def build_config_page(self):
        page = QWidget(); v = QVBoxLayout(page); v.setContentsMargins(0, 0, 0, 0); v.setSpacing(10)

        tabs = QTabWidget()

        basic = QWidget(); tabs.addTab(basic, "Podstawowe")
        form = QFormLayout(basic)
        self.portal_name = QLineEdit(); self.start_url = QLineEdit(); self.output_dir = QLineEdit(); self.browser_profile_dir = QLineEdit()
        self.portal_name.textChanged.connect(lambda t: self.title_label.setText(t or "Portal"))
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
        note.setWordWrap(True); note.setObjectName("hint"); form.addRow("Logowanie:", note)

        tr = QWidget(); tabs.addTab(tr, "Transkrypcja")
        trf = QFormLayout(tr)
        self.whisper_model = QComboBox(); self.whisper_model.addItems(["large-v3", "medium", "small", "base"])
        self.whisper_language = QComboBox(); self.whisper_language.setEditable(True); self.whisper_language.addItems(["pl", "en", "de", "auto"])
        trf.addRow("Model Whisper:", self.whisper_model); trf.addRow("Język:", self.whisper_language)
        trnote = QLabel("large-v3 = najwyższa jakość, ale większe wymagania. Transkrypcja odbywa się lokalnie.")
        trnote.setWordWrap(True); trnote.setObjectName("hint"); trf.addRow("", trnote)

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
        auto.setWordWrap(True); auto.setObjectName("hint"); df.addRow("Tryb AUTO:", auto)

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
            "Nagrywany jest wyłącznie wybrany monitor, więc na drugim możesz pracować. Nie zostawiaj na nagrywanym "
            "monitorze poczty, Teams ani innych poufnych okien. Najlepsza izolacja audio: osobne wyjście dla Chromium "
            "(np. HDMI monitora 2) i inne wyjście do Twojej pracy."
        )
        recnote.setWordWrap(True); recnote.setObjectName("warn"); rf.addRow("Ważne:", recnote)

        adv = QWidget(); tabs.addTab(adv, "Zaawansowane")
        af = QFormLayout(adv)
        self.debug = QCheckBox("Zapisuj diagnostykę wykrywania"); af.addRow("", self.debug)
        ext_note = QLabel("Rozszerzenie Chrome może przekazać bieżącą kartę do tej aplikacji przez lokalny Native Messaging Host. Nie przesyła loginów ani haseł.")
        ext_note.setWordWrap(True); ext_note.setObjectName("hint"); af.addRow("Chrome addon:", ext_note)
        self.b_addon = QPushButton("Otwórz instalację dodatku Chrome"); self.b_addon.clicked.connect(self.open_chrome_addon)
        af.addRow("", self.b_addon)

        v.addWidget(tabs)

        oneclick = QHBoxLayout()
        self.auto_scan_after_login = QCheckBox("Po udanym logowaniu automatycznie skanuj kurs")
        self.auto_scan_after_login.setChecked(True)
        oneclick.addWidget(self.auto_scan_after_login); oneclick.addStretch(1)
        v.addLayout(oneclick)

        actions = QHBoxLayout()
        self.b_login = QPushButton("1. Zaloguj się")
        self.b_scan = QPushButton("2. Skanuj strukturę")
        self.b_run = QPushButton("3. Pobierz i transkrybuj")
        self.b_stop = QPushButton("Zatrzymaj"); self.b_stop.setObjectName("danger")
        self.b_open = QPushButton("Otwórz katalog")
        self.b_delete = QPushButton("Usuń profil")
        self.b_login.clicked.connect(lambda: self.start_agent("login")); self.b_scan.clicked.connect(lambda: self.start_agent("discover")); self.b_run.clicked.connect(lambda: self.start_agent("run"))
        self.b_stop.clicked.connect(self.stop_agent); self.b_open.clicked.connect(self.open_output); self.b_delete.clicked.connect(self.delete_profile)
        for b in (self.b_login, self.b_scan, self.b_run, self.b_stop):
            actions.addWidget(b)
        actions.addStretch(1); actions.addWidget(self.b_open); actions.addWidget(self.b_delete)
        v.addLayout(actions)

        lower = QSplitter()
        matw = QWidget(); mv = QVBoxLayout(matw); mv.setContentsMargins(0, 0, 0, 0); mv.setSpacing(6)
        mcap = QLabel("MATERIAŁY"); mcap.setObjectName("caption"); mv.addWidget(mcap)
        self.material_list = QListWidget(); self.material_list.setObjectName("materials"); mv.addWidget(self.material_list, 1)
        logw = QWidget(); lv = QVBoxLayout(logw); lv.setContentsMargins(0, 0, 0, 0); lv.setSpacing(6)
        lcap = QLabel("DZIENNIK"); lcap.setObjectName("caption"); lv.addWidget(lcap)
        self.log = QPlainTextEdit(); self.log.setReadOnly(True); self.log.setMaximumBlockCount(5000); lv.addWidget(self.log, 1)
        lower.addWidget(matw); lower.addWidget(logw); lower.setStretchFactor(0, 3); lower.setStretchFactor(1, 4)
        v.addWidget(lower, 1)
        return page

    def build_archive_page(self):
        page = QWidget(); v = QVBoxLayout(page); v.setContentsMargins(0, 0, 0, 0); v.setSpacing(10)
        bar = QHBoxLayout()
        cap = QLabel("STRUKTURA ARCHIWUM"); cap.setObjectName("caption")
        b_ref = QPushButton("Odśwież"); b_ref.clicked.connect(self.refresh_archive)
        b_openf = QPushButton("Otwórz w eksploratorze"); b_openf.clicked.connect(self.open_output)
        b_idx = QPushButton("index.html"); b_idx.setObjectName("primary"); b_idx.clicked.connect(self.open_index_html)
        bar.addWidget(cap); bar.addStretch(1); bar.addWidget(b_ref); bar.addWidget(b_openf); bar.addWidget(b_idx)
        v.addLayout(bar)

        split = QSplitter()
        self.archive_tree = QTreeWidget(); self.archive_tree.setHeaderLabels(["Materiał", "Status"]); self.archive_tree.setColumnWidth(0, 300)
        self.archive_tree.currentItemChanged.connect(lambda *a: self.on_archive_select())
        self.archive_preview = QPlainTextEdit(); self.archive_preview.setReadOnly(True)
        split.addWidget(self.archive_tree); split.addWidget(self.archive_preview)
        split.setStretchFactor(0, 4); split.setStretchFactor(1, 5)
        v.addWidget(split, 1)
        return page

    def switch_view(self, index):
        self.stack.setCurrentIndex(index)
        self.nav_config.setChecked(index == 0)
        self.nav_archive.setChecked(index == 1)
        if index == 1:
            self.refresh_archive()

    # ---------------------------------------------------------------- helpers

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
        w = QWidget(); l = QHBoxLayout(w); l.setContentsMargins(0, 0, 0, 0); b = QPushButton("Wybierz…")
        def pick():
            d = QFileDialog.getExistingDirectory(self, "Wybierz katalog", line.text() or str(Path.home()))
            if d: line.setText(d)
        b.clicked.connect(pick); l.addWidget(line, 1); l.addWidget(b); return w

    def _dot_icon(self, color):
        pm = QPixmap(14, 14); pm.fill(Qt.transparent)
        p = QPainter(pm); p.setRenderHint(QPainter.Antialiasing); p.setPen(Qt.NoPen)
        p.setBrush(QColor(color)); p.drawEllipse(3, 3, 8, 8); p.end()
        return QIcon(pm)

    def _profile_dot(self, name):
        marker = ev.read_session_marker(ev.session_marker_path(PROFILES_DIR, slugify(name)))
        return self._dot_icon("#55C57A" if (marker and marker.get("logged_in")) else "#6E7784")

    def current_profile_name(self):
        it = self.profile_list.currentItem()
        return it.data(Qt.UserRole) if it else ""

    def select_profile(self, name):
        for i in range(self.profile_list.count()):
            if self.profile_list.item(i).data(Qt.UserRole) == name:
                self.profile_list.setCurrentRow(i); return

    def refresh_profiles(self, select=None):
        self.profile_list.blockSignals(True)
        self.profile_list.clear()
        for name in sorted(self.profiles):
            it = QListWidgetItem(self._profile_dot(name), name)
            it.setData(Qt.UserRole, name)
            self.profile_list.addItem(it)
        self.profile_list.blockSignals(False)
        if select:
            self.select_profile(select)

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
        self.title_label.setText(p.get("portal_name", "") or "Portal")
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
        name = self.current_profile_name()
        if name in self.profiles: self.apply_profile(self.profiles[name])

    def save_profile(self):
        p = self.collect_profile(); name = p["portal_name"]
        if not p["start_url"]:
            QMessageBox.warning(self,"Brak URL","Podaj URL startowy portalu/kursu."); return False
        if not p["browser_profile_dir"]:
            p["browser_profile_dir"] = str(PROFILES_DIR/"browser_profiles"/slugify(name)); self.browser_profile_dir.setText(p["browser_profile_dir"])
        self.profiles[name] = p; self.save_profiles_file(); self.refresh_profiles(name); self.log.appendPlainText(f"Zapisano profil: {name}"); return True

    def delete_profile(self):
        name = self.current_profile_name()
        if name and name in self.profiles and QMessageBox.question(self,"Usuń profil",f"Usunąć ustawienia profilu '{name}'?\nSesja przeglądarki i pobrane pliki pozostaną na dysku.") == QMessageBox.Yes:
            del self.profiles[name]; self.save_profiles_file(); self.refresh_profiles()
            if self.profiles: self.profile_list.setCurrentRow(0)

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
            "font-size:15px; font-weight:600; padding:12px 16px; border-radius:10px;" + STATUS_STYLES.get(kind, STATUS_STYLES["idle"])
        )
        self.status_label.setText(text)
        chip_text, chip_css = CHIP_STYLES.get(kind, CHIP_STYLES["idle"])
        if kind == "ok" and not self.login_confirmed:
            chip_text = "GOTOWE"
        self.status_chip.setText(chip_text)
        self.status_chip.setStyleSheet("padding:3px 10px; border-radius:9px; font-size:11px; font-weight:600;" + chip_css)

    def set_step(self, text):
        self.step_label.setText(text)

    # ---------------------------------------------------------------- material list (live)

    def _status_short(self, status):
        return MATERIAL_LABELS.get(status, (status or "").upper())

    def _status_color(self, status):
        return MATERIAL_COLORS.get(status, "#C6CCD5")

    def material_reset(self, total):
        self.material_list.clear()

    def material_add(self, evt):
        st = evt.get("status", "")
        item = QListWidgetItem(f"{int(evt.get('index', 0)):03d} · {evt.get('title') or ''}   —   {self._status_short(st)}")
        item.setForeground(QColor(self._status_color(st)))
        self.material_list.addItem(item); self.material_list.scrollToBottom()

    # ---------------------------------------------------------------- agent

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
        self.material_list.clear()
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
            self.material_reset(evt.get("total", 0))
        elif name == ev.EVENT_LESSON_DONE:
            self.set_step(f"Materiał {evt.get('index', 0)}/{evt.get('total', 0)}: {evt.get('title') or ''}")
            self.material_add(evt)
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

    def open_index_html(self):
        p = Path(os.path.expandvars(self.output_dir.text())).expanduser() / "index.html"
        if p.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(p.resolve())))
        else:
            QMessageBox.information(self, "Brak indeksu", "index.html jeszcze nie istnieje — uruchom pełny proces, aby go zbudować.")

    # ---------------------------------------------------------------- archive view

    def refresh_archive(self):
        self.archive_tree.clear(); self.archive_preview.setPlainText("")
        out = Path(os.path.expandvars(self.output_dir.text())).expanduser()
        index = out / "index.json"
        if not index.exists():
            self.archive_preview.setPlainText(
                "Brak zarchiwizowanych materiałów w tym katalogu.\n\n"
                "Zaloguj się i uruchom pełny proces („Zrób wszystko”), aby zbudować archiwum."
            )
            return
        try:
            lessons = json.loads(index.read_text(encoding="utf-8"))
        except Exception as e:
            self.archive_preview.setPlainText(f"Nie udało się odczytać index.json: {e}")
            return
        cats = {}
        for l in lessons:
            if isinstance(l, dict):
                cats.setdefault(l.get("category") or "Bez kategorii", []).append(l)
        for cat, items in cats.items():
            parent = QTreeWidgetItem([cat, f"{len(items)}"])
            for l in items:
                leaf = QTreeWidgetItem([f"{int(l.get('order', 0)):03d} · {l.get('title', '')}", self._status_short(l.get("status"))])
                leaf.setData(0, Qt.UserRole, l)
                leaf.setForeground(1, QColor(self._status_color(l.get("status"))))
                parent.addChild(leaf)
            self.archive_tree.addTopLevelItem(parent); parent.setExpanded(True)

    def on_archive_select(self):
        it = self.archive_tree.currentItem()
        if not it: return
        l = it.data(0, Qt.UserRole)
        if not isinstance(l, dict): return
        out = Path(os.path.expandvars(self.output_dir.text())).expanduser()
        lines = [l.get("title", ""), "",
                 f"Status:    {self._status_short(l.get('status'))}",
                 f"Kategoria: {l.get('category', '')}"]
        if l.get("media_file"): lines.append(f"Plik:      {l['media_file']}")
        if l.get("note"): lines.append(f"Uwaga:     {l['note']}")
        lines += ["", "─" * 52, ""]
        tpath = l.get("transcript_md") or l.get("transcript_txt")
        if tpath:
            f = out / tpath
            try:
                lines.append(f.read_text(encoding="utf-8"))
            except Exception as e:
                lines.append(f"(nie udało się wczytać transkrypcji: {e})")
        else:
            lines.append("(brak transkrypcji dla tego materiału)")
        self.archive_preview.setPlainText("\n".join(lines))

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
            self.select_profile(a.profile)
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
    app.setStyleSheet(DARK_QSS)
    win = MainWindow(args); win.show(); sys.exit(app.exec())


if __name__ == "__main__": main()
