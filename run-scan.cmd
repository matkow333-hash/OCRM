@echo off
rem Jeden przebieg skanera z wysylka do aplikacji. Wolany przez Harmonogram zadan
rem co 45 minut. Loguje z data do data\scan.log, zeby dalo sie zobaczyc, co i kiedy
rem sie dzialo bez wchodzenia do bazy. Sciezki liczone od polozenia tego pliku,
rem wiec przeniesienie projektu nie psuje zadania.
setlocal
cd /d "%~dp0"
if not exist "data" mkdir "data"
set PYTHONIOENCODING=utf-8
echo. >> "data\scan.log"
echo ===== %DATE% %TIME% ===== >> "data\scan.log"
".venv\Scripts\python.exe" -m ocrm.cli scan --push >> "data\scan.log" 2>&1
echo koniec, kod wyjscia %ERRORLEVEL% >> "data\scan.log"
endlocal
