@echo off
rem Crea il collegamento "StemLab" nel menu Start (e sul desktop).
set "TARGET=%~dp0StemLab.bat"
set "WORKDIR=%~dp0"
powershell -NoProfile -Command "$w=New-Object -ComObject WScript.Shell; foreach($d in @([Environment]::GetFolderPath('Programs'),[Environment]::GetFolderPath('Desktop'))){ $s=$w.CreateShortcut($d+'\StemLab.lnk'); $s.TargetPath=$env:TARGET; $s.WorkingDirectory=$env:WORKDIR; $s.WindowStyle=7; $s.IconLocation='shell32.dll,40'; $s.Save() }"
echo.
echo Fatto: ora trovi StemLab nel menu Start e sul desktop.
pause
