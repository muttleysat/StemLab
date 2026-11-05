@echo off
cd /d "%~dp0"
echo === Python usato per costruire l'exe
".venv\Scripts\python.exe" -c "import sys;print(sys.version);print('cartella base:',sys.base_prefix);print('64 bit:',sys.maxsize>2**32)"
echo.
echo === File principali in dist\StemLab\_internal
for %%f in (python312.dll python3.dll vcruntime140.dll vcruntime140_1.dll base_library.zip) do (
  if exist "dist\StemLab\_internal\%%f" (echo   trovato:  %%f) else (echo   MANCANTE: %%f)
)
echo.
echo === DLL presenti nella cartella del Python di sistema
".venv\Scripts\python.exe" -c "import sys,os;d=sys.base_prefix;print('  ',[f for f in os.listdir(d) if f.lower().endswith('.dll')])"
echo.
echo === Avvio di StemLab-debug.exe
if exist "dist\StemLab\StemLab-debug.exe" ("dist\StemLab\StemLab-debug.exe") else (echo   MANCANTE: dist\StemLab\StemLab-debug.exe)
echo.
echo === Fine. Seleziona tutto il testo di questa finestra, copialo e mandamelo.
pause
