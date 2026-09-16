# NAJPROSTSZA INSTALACJA

Po rozpakowaniu pakietu **dwukrotnie kliknij `INSTALL.bat`**. Nie wpisuj `Set-ExecutionPolicy` w zwykłym `cmd.exe` — `INSTALL.bat` sam uruchomi PowerShell z właściwymi parametrami.

# Course Archiver & Transcriber — Windows + Chrome

Lokalna aplikacja desktopowa do porządkowania materiałów z portali szkoleniowych, do których użytkownik ma uprawniony dostęp. Wersja ta obsługuje **dwa lub więcej monitorów** oraz zawiera **rozszerzenie Google Chrome** będące drugim wejściem do aplikacji.

## Najważniejsze funkcje

- profile wielu portali,
- ręczne logowanie w Chromium z lokalnym zapisem sesji/cookies,
- skanowanie struktury kursu,
- tryb AUTO + opcjonalny regex URL / selektor CSS,
- pobieranie standardowo udostępnionych plików audio/video i niechronionych streamów,
- fallback: odtwarzanie + lokalne nagranie wybranego monitora i audio loopback,
- automatyczna transkrypcja Whisper,
- katalogi `moduł → lekcja`, `metadata.json`, `INDEX.md`, `index.html`,
- wznowienie po przerwaniu,
- wybór konkretnego monitora dla Chromium i nagrywania,
- wybór urządzenia audio loopback,
- Chrome addon: bieżąca karta → aplikacja → logowanie / skan / pełny proces,
- widoczny status sesji (**ZALOGOWANO**) oraz jednoklikowe uruchomienie całego procesu.

## Dwa monitory

W zakładce **Nagrywanie / 2 monitory** wybierz np. `Monitor 2`.

Aplikacja:

1. uruchomi sterowane Chromium na wskazanym monitorze,
2. ustawi okno na geometrii tego monitora,
3. w fallbacku będzie przechwytywać **wyłącznie ten monitor**,
4. pozostawi drugi monitor poza nagraniem, więc możesz na nim pracować.

Pozycja monitora jest zapisywana razem z indeksem i geometrią (`left/top/width/height`), dlatego konfiguracja poprawnie obsługuje układy, w których drugi monitor jest po lewej stronie i ma ujemne współrzędne.

### Audio podczas równoległej pracy

Obraz jest izolowany per-monitor. Windows loopback rejestruje natomiast dźwięk z wybranego **urządzenia wyjściowego**, a nie tylko z pojedynczego okna Chromium.

Najlepszy wariant do pracy równoległej:

- portal/Chromium → np. `HDMI Monitor 2`,
- Twoja bieżąca praca/Teams/YouTube → słuchawki lub inne wyjście,
- w aplikacji jako **Audio loopback do nagrania** wybierz urządzenie używane przez portal.

Jeżeli oba programy grają na tym samym urządzeniu, obcy dźwięk może trafić do nagrania/transkrypcji.

## Ograniczenie ochrony treści

Program **nie obchodzi DRM, EME ani ContentProtection**. Jeśli player lub manifest wskazuje ochronę/szyfrowanie, materiał zostaje oznaczony jako `protected`, a mechanizm nie próbuje łamać zabezpieczeń.

## Instalacja — Windows 10/11

1. Zainstaluj Python 3.11 lub 3.12 64-bit.
2. Rozpakuj ZIP do stałego katalogu, którego później nie będziesz przenosił.
3. Uruchom PowerShell w tym katalogu:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\setup_windows.ps1
```

Instalator:

- tworzy `.venv`,
- instaluje Chromium Playwright i biblioteki,
- buduje lokalny Native Messaging Host dla Chrome,
- rejestruje go tylko dla bieżącego użytkownika w `HKCU`,
- tworzy skrót aplikacji na pulpicie,
- uruchamia automatyczny test bridge.

Potem aplikację uruchamiasz ikoną **Course Archiver & Transcriber**.

## Chrome addon — instalacja

Po wykonaniu `setup_windows.ps1`:

1. uruchom `Install_Chrome_Addon.bat`,
2. w Chrome wejdź na `chrome://extensions`,
3. włącz **Tryb dewelopera**,
4. kliknij **Załaduj rozpakowane / Load unpacked**,
5. wskaż folder `chrome_extension` z pakietu.

Stały ID rozszerzenia:

```text
dfmedhencldblnhceamhppjklgomoffk
```

Native Messaging Host dopuszcza wyłącznie rozszerzenie o tym ID.

### Użycie dodatku

Na stronie portalu kliknij ikonę **Course Archiver Connector**. Dodatek pokaże URL bieżącej karty oraz zapisane profile i udostępni:

- **Otwórz w aplikacji** — przekazuje URL i otwiera GUI,
- **Zaloguj się** — uruchamia aplikację i procedurę logowania (status pokaże się w oknie aplikacji),
- **Skanuj strukturę** — przekazuje bieżący URL jako punkt startowy skanowania,
- **Uruchom pełny proces** — uruchamia cały workflow dla bieżącej strony i wybranego profilu.

Rozszerzenie przekazuje lokalnie tylko:

```text
URL bieżącej karty
nazwa profilu
wybrana akcja
```

Nie odczytuje pól formularzy, loginów ani haseł.

Jeżeli nie masz jeszcze żadnego profilu, addon pozwala tylko otworzyć stronę w aplikacji; profil utwórz najpierw w GUI.

## Obsługa aplikacji

### 1. Nowy portal

Kliknij **Nowy profil** i ustaw:

- nazwę portalu,
- URL startowy,
- katalog wynikowy,
- monitor do odtwarzania/nagrywania,
- opcjonalnie urządzenie audio.

### 2. Logowanie

Kliknij **1. Zaloguj się**. Otworzy się Chrome na wskazanym monitorze. Zaloguj się normalnie, także przy MFA/CAPTCHA.

Aplikacja nie zapisuje loginu ani hasła w konfiguracji.

Po wykryciu i **potwierdzeniu** sesji na stronie startowej pasek statusu u góry okna zmienia się na zielony napis **ZALOGOWANO**. Status jest zapisywany na dysku dla profilu portalu, więc po ponownym uruchomieniu aplikacji widać, kiedy sesja została ostatnio potwierdzona.

Jeśli sesja z poprzedniego uruchomienia jest nadal aktywna, aplikacja napisze to wprost zamiast kończyć pracę bez komunikatu.

Zaznaczona opcja **Po udanym logowaniu automatycznie skanuj kurs** sprawia, że agent przechodzi do skanowania w tym samym oknie Chrome, bez ponownego uruchamiania przeglądarki. Gdy opcja jest wyłączona, aplikacja po zalogowaniu pyta, czy uruchomić skanowanie.

### 3. Skanowanie

Kliknij **2. Skanuj strukturę**. Jeśli AUTO nie znajdzie materiałów, ustaw np.:

```text
Regex: /lessons/|/lecture/|/training/
```

lub:

```text
CSS selector: .lesson-list a
```

### 4. Pełny proces

Kliknij **▶ ZRÓB WSZYSTKO**, aby jednym kliknięciem wykonać logowanie, skanowanie, pobieranie i transkrypcję. Przycisk **3. Pobierz i transkrybuj** robi to samo, gdy wolisz iść krok po kroku.

Pasek pod statusem pokazuje bieżący etap, a przy pobieraniu — numer materiału (np. `Materiał 7/23`).

Dla każdego materiału aplikacja kolejno:

1. otwiera lekcję,
2. próbuje znaleźć standardowe źródło video/audio,
3. pobiera je, jeśli jest dostępne i niechronione,
4. jeśli nie — przy dozwolonym materiale uruchamia playback i nagrywa wybrany monitor + wybrane audio loopback,
5. wykrywa zakończenie standardowego playera,
6. uruchamia Whisper,
7. zapisuje `.mp4/.m4a`, `.txt`, `.md` i `metadata.json`,
8. przechodzi do następnego materiału.

## Struktura danych

```text
Katalog portalu\
  index.html
  INDEX.md
  index.json
  .state.json
  Moduł A\
    001_Lekcja\
      001_Lekcja.mp4
      001_Lekcja.txt
      001_Lekcja.md
      metadata.json
```

## Testy dołączone do pakietu

`self_test.py` sprawdza niezależnie od Windows:

- poprawność Manifest V3,
- zgodność stałego ID rozszerzenia z kluczem,
- framing protokołu Chrome Native Messaging,
- odpowiedź `status` lokalnego hosta.

`postinstall_test.py`, uruchamiany automatycznie przez instalator na Windows, dodatkowo sprawdza:

- manifest hosta Native Messaging,
- wpis w rejestrze Chrome,
- obecność EXE hosta,
- rzeczywistą wymianę wiadomości `status` z EXE.

`tests/test_login_flow.py` sprawdza poprawkę widocznego statusu logowania:

- protokół zdarzeń agent → GUI (format, parsowanie, opisy),
- odporność na podział strumienia stdout w dowolnym miejscu,
- trwały znacznik sesji,
- wybór etapu agenta dla `--after-login`,
- realne wykonanie maszyny stanów statusu GUI (bez PySide6),
- obecność dotychczasowych funkcji: dwa monitory, lokalna sesja Chrome, transkrypcja, dodatek Chrome.

Kod Pythona i JavaScript dodatku jest również sprawdzany składniowo przed spakowaniem wydania.

## Modele Whisper

- `large-v3` — najwyższa jakość,
- `medium` — dobry kompromis,
- `small` — szybszy na CPU.

Jeżeli CTranslate2 wykryje zgodne CUDA, Whisper użyje GPU automatycznie.
