@echo off
cd /d "%~dp0"
echo Creazione di StemLab.exe
echo Usa l'ambiente .venv di questa cartella: deve essere quello con cui StemLab gia' funziona.
echo Ci vogliono 5-15 minuti e servono circa 10 GB liberi sul disco.
echo.
if not exist ".venv\Scripts\python.exe" (
  echo ERRORE: non trovo .venv in questa cartella.
  pause
  exit /b 1
)
if not exist "ffmpeg\ffmpeg.exe" (
  echo ATTENZIONE: manca ffmpeg\ffmpeg.exe. L'exe funzionera' solo se ffmpeg e' installato nel sistema.
  echo.
)
".venv\Scripts\python.exe" -m pip install --upgrade pyinstaller pyinstaller-hooks-contrib
if errorlevel 1 goto :errore
".venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean StemLab.spec
if errorlevel 1 goto :errore
rem la cartella build contiene solo file intermedi (e un exe che non funziona da solo): la tolgo
if exist "build" rmdir /s /q "build"
echo.
echo Fatto. Il programma e' in: %~dp0dist\StemLab\StemLab.exe
echo Se non si apre, avvia StemLab-debug.exe nella stessa cartella e copia il testo che compare.
explorer "%~dp0dist\StemLab"
pause
exit /b 0

:errore
echo.
echo La creazione non e' riuscita. Copia le ultime righe qui sopra e mandamele.
pause
exit /b 1
