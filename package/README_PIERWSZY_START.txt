COURSE ARCHIVER & TRANSCRIBER 4.6
================================

DLA UZYTKOWNIKA BEZ WIEDZY TECHNICZNEJ

CO MASZ ZROBIC
--------------
1. Rozpakuj caly ZIP do zwyklego folderu, np. Pobrane.
2. Kliknij dwa razy:

   01_INSTALUJ.cmd

3. Niczego nie wpisuj w CMD ani PowerShell.
4. Poczekaj. Pierwsza instalacja moze trwac kilkanascie lub kilkadziesiat minut.
5. Jezeli Windows wyswietli pytanie UAC, kliknij TAK.

Instalator sam sprawdza i w razie potrzeby instaluje:
- Python 3.11/3.12 potrzebny tylko do zbudowania programu,
- Google Chrome,
- Microsoft Visual C++ Runtime,
- Inno Setup,
- wszystkie biblioteki aplikacji,
- FFmpeg i komponenty transkrypcji dostarczane przez biblioteki aplikacji.

LOG
---
Log powstaje OD PIERWSZEJ SEKUNDY, jeszcze zanim instalator zacznie
sprawdzac Python.

Glowny log jest zawsze zapisywany tutaj:

%LOCALAPPDATA%\CourseArchiverInstaller\INSTALL_LOG.txt

Instalator dodatkowo probuje utworzyc kopie w folderze paczki:

INSTALL_LOG.txt

Jesli instalacja sie nie powiedzie:
- log otworzy sie automatycznie w Notatniku,
- jego kopia zostanie utworzona na Pulpicie jako:
  CourseArchiver_INSTALL_LOG.txt

Mozesz tez w dowolnej chwili kliknac:

02_OTWORZ_LOG.cmd

Jesli mimo wszystko cos zachowa sie nietypowo, kliknij:

DIAGNOSTYKA.cmd

i wyslij plik DIAGNOSTYKA_LOG.txt.

JAK UZYWAC APLIKACJI PO INSTALACJI
----------------------------------
Najprosciej: kliknij duzy przycisk

   ZROB WSZYSTKO

Aplikacja otworzy Chrome, poprosi Cie o zalogowanie (jesli trzeba),
a potem sama zeskanuje kurs, pobierze materialy i zrobi transkrypcje.

Jesli wolisz krok po kroku, uzyj przyciskow 1, 2, 3.
Po kliknieciu "1. Zaloguj sie":
- otworzy sie zwykle okno Google Chrome,
- zaloguj sie recznie (obslugiwane sa MFA i CAPTCHA),
- aplikacja sama wykryje koniec logowania,
- pasek u gory okna zmieni sie na zielony napis ZALOGOWANO,
- jesli opcja "Po udanym logowaniu automatycznie skanuj kurs" jest
  wlaczona, skanowanie ruszy od razu; jesli nie, aplikacja zapyta,
  czy je uruchomic.

Zielony status ZALOGOWANO jest zapamietywany. Po ponownym otwarciu
aplikacji od razu widzisz, kiedy sesja byla ostatnio potwierdzona,
i nie musisz logowac sie ponownie, dopoki portal nie wylogowal Cie sam.

SMART APP CONTROL
-----------------
Paczka nie jest podpisana komercyjnym certyfikatem code-signing.
Jezeli Windows zablokuje pierwszy plik tylko dlatego, ze ZIP pochodzi
z Internetu:
- prawy przycisk na pobranym ZIP -> Wlasciwosci,
- zaznacz Odblokuj -> Zastosuj,
- rozpakuj ZIP ponownie.

GDZIE ZNAJDE FINALNY INSTALATOR?
--------------------------------
Po udanej budowie:

GOTOWY_INSTALATOR\CourseArchiver_Setup_4.6.0.exe

Nie musisz zachowywac plikow budowy po poprawnym zainstalowaniu aplikacji.
