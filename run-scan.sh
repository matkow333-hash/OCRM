#!/usr/bin/env bash
# Jeden przebieg skanera z wysylka do aplikacji. Wolany przez Harmonogram zadan co 45 minut.
# Loguje z data do data/scan.log. Sciezki liczone od polozenia pliku.
#
# PLAYWRIGHT_BROWSERS_PATH JEST TU KONIECZNY, NIE OZDOBNY. Zmierzone 7 wrzesnia 2026:
# przegladarki zainstalowane domyslnie trafily do %LOCALAPPDATA%\ms-playwright, ale ten
# katalog jest przekierowaniem do kontenera aplikacji Claude Desktop
# (AppData\Local\Packages\Claude_.../LocalCache\Local\). Procesy uruchomione z wnetrza
# tej aplikacji widza przegladarki normalnie; Harmonogram Zadan, dzialajacy poza
# kontenerem, dostawal "Executable doesn't exist" na plik, ktory z powloki istnial
# i uruchamial sie wprost. Sprawdzenie: os.listdir na katalogu przegladarki rzucal
# FileNotFoundError mimo poprawnych USERPROFILE i LOCALAPPDATA.
# Katalog .playwright w projekcie nie jest wirtualizowany i widza go oba swiaty.
set -u
cd "$(dirname "$0")"
mkdir -p data
export PYTHONIOENCODING=utf-8
export PLAYWRIGHT_BROWSERS_PATH="$(pwd -W 2>/dev/null || pwd)/.playwright"
{
  echo
  echo "===== $(date '+%Y-%m-%d %H:%M:%S') ====="
  ./.venv/Scripts/python.exe -m ocrm.cli scan --push 2>&1
  echo "koniec, kod wyjscia $?"
} >> data/scan.log
