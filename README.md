# Course Archiver & Transcriber

Źródła i generator paczki instalacyjnej one-click dla Windows 10/11.

## Co tu jest

| Ścieżka | Zawartość |
| --- | --- |
| `package/` | Zawartość payloadu: `bootstrap.py`, `worker_install.cmd`, `installer/CourseArchiver.iss`, `src/` (GUI, agent, host Native Messaging, rozszerzenie Chrome), `tests/` |
| `tools/build_oneclick.py` | Buduje `01_INSTALUJ.cmd` z wbudowanym payloadem i pakuje gotowy ZIP |
| `tools/oneclick_launcher.cmd.tmpl` | Szablon launchera `.cmd` (placeholdery wersji i SHA256) |
| `tools/verify_package.py` | Weryfikuje gotową paczkę: dekoduje payload, sprawdza SHA256 i uruchamia testy na tym, co dostanie użytkownik |
| `dist/` | Gotowa paczka instalacyjna |

## Budowa i weryfikacja

```bash
python3 tools/build_oneclick.py     # -> dist/CourseArchiver_OneClick_<wersja>.zip
python3 tools/verify_package.py     # weryfikacja statyczna gotowej paczki
```

Testy paczki można uruchomić też osobno:

```bash
cd package
python3 tests/test_login_flow.py
python3 tests/test_package.py
python3 tests/test_installer_integrity.py
```

Testy nie wymagają Windows, PySide6 ani Playwright.

## Wersja 4.6.0 — widoczny status po zalogowaniu

W 4.5 przycisk „1. Zaloguj się” kończył pracę bez żadnego komunikatu w GUI
(`--login-only` zapisywał sesję i zamykał proces), więc wyglądało to, jakby
aplikacja nic nie zrobiła.

Zmiany:

- wspólny protokół zdarzeń agent → GUI (`package/src/session_events.py`),
- agent potwierdza sesję na stronie startowej i zapisuje trwały znacznik
  „zalogowano” dla profilu portalu,
- GUI pokazuje kolorowy pasek statusu (`ZALOGOWANO`, `LOGOWANIE`, błąd)
  oraz bieżący etap pracy,
- opcja automatycznego przejścia do skanowania zaraz po zalogowaniu
  (`--after-login`, bez ponownego otwierania Chrome),
- przycisk „ZRÓB WSZYSTKO” uruchamiający cały proces jednym kliknięciem,
- instalator 4.6 zawsze buduje EXE od nowa, żeby nie wgrać binariów
  zbudowanych ze starszych źródeł.

Szczegóły: `package/CO_ZMIENIONO_4_6.txt`.
