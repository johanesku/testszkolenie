# Historia zmian — Course Archiver & Transcriber

## 4.7.0 — 2026-09-17

- Inkrementalna budowa: każdy komponent (GUI, agent, host) ma hash z kodu źródłowego, zależności i wersji; przy braku zmian jest przywracany z pamięci podręcznej zamiast budowany od nowa. Środowisko budowy i biblioteki odtwarzane tylko przy zmianie `requirements.txt`. Kolejne uruchomienia skracają się z kilkudziesięciu minut do sekund.
- Inkrementalne wdrożenie w trybie przenośnym: kopiowane są tylko komponenty, które się zmieniły; komponenty usunięte ze źródeł są kasowane z instalacji (`.install_manifest.json`).
- Obsługa blokady Smart App Control (WinError 4551): zamiast tracebacku instalator przechodzi w tryb przenośny i pokazuje jasną instrukcję.
- Wersjonowanie wydań: `tools/bump_version.py X.Y.Z "opis"` zmienia wersję we wszystkich plikach naraz i dopisuje wpis tutaj; `--check` pilnuje spójności.

## 4.6.x — 2026-09-16

- Widoczny status „ZALOGOWANO" po udanym logowaniu, event-owy protokół agent→GUI, opcja auto-skanu i przycisk „Zrób wszystko".
- Nowy ciemny interfejs z sidebarem profili, żywą listą materiałów i widokiem Archiwum.
- Poprawki: fałszywe „sesja wygasła" przy skanowaniu, mojibake polskich znaków (UTF-8), crash `_debug/page_*.json` przy wyłączonej diagnostyce.

