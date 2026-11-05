@echo off
cd /d "%~dp0"
echo Avvio di StemLab...
if not exist ".venv\Scripts\activate.bat" (
  echo.
  echo ERRORE: non trovo la cartella .venv dentro:
  echo %~dp0
  echo Questo file deve stare nella cartella stemlab, accanto ad app.py.
  echo.
  pause
  exit /b 1
)
call ".venv\Scripts\activate.bat"
python app.py
echo.
echo StemLab si e' chiuso. Se c'e' un errore qui sopra, copialo e mandamelo.
pause
