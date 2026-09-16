"""Protokół zdarzeń agent -> GUI oraz trwały znacznik stanu sesji logowania.

Moduł celowo nie ma żadnych zależności poza biblioteką standardową: jest
importowany zarówno przez GUI (app.pyw), jak i przez agenta (agent_generic.py),
a także przez testy statyczne uruchamiane bez pełnego środowiska aplikacji.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

EVENT_PREFIX = "@@CA_EVENT "

# Kolejne etapy pracy agenta. GUI używa ich do wyświetlenia stanu.
STAGE_LOGIN = "login"
STAGE_DISCOVER = "discover"
STAGE_PROCESS = "process"

EVENT_AGENT_START = "agent_start"
EVENT_BROWSER_READY = "browser_ready"
EVENT_LOGIN_REQUIRED = "login_required"
EVENT_LOGIN_OK = "login_ok"
EVENT_LOGIN_FAILED = "login_failed"
EVENT_SCAN_START = "scan_start"
EVENT_SCAN_DONE = "scan_done"
EVENT_PROCESS_START = "process_start"
EVENT_LESSON_DONE = "lesson_done"
EVENT_FINISHED = "finished"
EVENT_FAILED = "failed"


def format_event(event: str, **fields) -> str:
    """Zbuduj jedną linię zdarzenia do wypisania na stdout agenta."""
    payload = {"event": str(event)}
    payload.update(fields)
    return EVENT_PREFIX + json.dumps(payload, ensure_ascii=False, sort_keys=True)


def parse_event(line: str):
    """Zwróć słownik zdarzenia albo None, jeżeli linia to zwykły log."""
    if not isinstance(line, str):
        return None
    stripped = line.strip()
    if not stripped.startswith(EVENT_PREFIX.strip()):
        return None
    _, _, raw = stripped.partition(EVENT_PREFIX.strip())
    try:
        data = json.loads(raw.strip())
    except Exception:
        return None
    if not isinstance(data, dict) or not data.get("event"):
        return None
    return data


def describe(evt: dict) -> str:
    """Czytelny dla użytkownika opis zdarzenia (język polski)."""
    name = (evt or {}).get("event")
    if name == EVENT_AGENT_START:
        return "Uruchamiam przeglądarkę Chrome z lokalnym profilem…"
    if name == EVENT_BROWSER_READY:
        return "Chrome gotowy. Sprawdzam stan sesji na portalu…"
    if name == EVENT_LOGIN_REQUIRED:
        return "Wymagane logowanie. Zaloguj się w otwartym oknie Chrome (obsługiwane MFA/CAPTCHA)."
    if name == EVENT_LOGIN_OK:
        if evt.get("already_logged_in"):
            return "ZALOGOWANO — sesja z poprzedniego logowania jest nadal aktywna."
        return "ZALOGOWANO — logowanie zakończone, sesja zapisana lokalnie."
    if name == EVENT_LOGIN_FAILED:
        return "Logowanie nie powiodło się: " + str(evt.get("error") or "nieznany powód")
    if name == EVENT_SCAN_START:
        return "Skanuję strukturę kursu…"
    if name == EVENT_SCAN_DONE:
        return f"Skanowanie zakończone. Znaleziono materiałów: {evt.get('count', 0)}."
    if name == EVENT_PROCESS_START:
        return f"Pobieranie i transkrypcja: {evt.get('total', 0)} materiałów."
    if name == EVENT_LESSON_DONE:
        return f"Materiał {evt.get('index', 0)}/{evt.get('total', 0)}: {evt.get('title') or ''} [{evt.get('status') or ''}]"
    if name == EVENT_FINISHED:
        return "GOTOWE."
    if name == EVENT_FAILED:
        return "Błąd: " + str(evt.get("error") or "nieznany")
    return ""


class OutputSplitter:
    """Składa linie ze strumienia stdout agenta docierającego w dowolnych kawałkach.

    QProcess dostarcza dane fragmentami, które potrafią rozciąć linię zdarzenia
    w połowie. Bez buforowania GUI zgubiłoby status „ZALOGOWANO”.
    """

    def __init__(self):
        self.buffer = ""

    def feed(self, chunk: str):
        self.buffer += chunk or ""
        parts = self.buffer.split("\n")
        self.buffer = parts.pop()
        return [p.rstrip("\r") for p in parts]

    def flush(self):
        rest, self.buffer = self.buffer.rstrip("\r"), ""
        return [rest] if rest else []


def session_marker_path(profiles_dir, portal_slug: str) -> Path:
    return Path(profiles_dir) / "sessions" / f"{portal_slug}.json"


def write_session_marker(path, **fields) -> None:
    """Zapisz trwały znacznik 'zalogowano' dla profilu portalu."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    data = {"logged_in": True, "checked_at": time.strftime("%Y-%m-%d %H:%M:%S")}
    data.update(fields)
    target.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def read_session_marker(path):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return None
    return data if isinstance(data, dict) else None
