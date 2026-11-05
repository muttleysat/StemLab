# Crea la cartella "StemLab_Portable": Python, librerie, ffmpeg e (facoltativo) modelli, tutto dentro.
# Si lancia con Crea_portable.bat. Solo caratteri ASCII, per evitare problemi di codifica su Windows.
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$env:PIP_DISABLE_PIP_VERSION_CHECK = "1"

$PY_VER   = "3.12.10"   # ultima 3.12 con file binari per Windows
$PY_URL   = "https://www.python.org/ftp/python/$PY_VER/python-$PY_VER-embed-amd64.zip"
$PIP_URL  = "https://bootstrap.pypa.io/get-pip.py"
$FF_URL   = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
$WV2_URL  = "https://go.microsoft.com/fwlink/p/?LinkId=2124703"
$src      = $PSScriptRoot

function Ask($question, $default) {
    $a = Read-Host "$question [$default]"
    if ([string]::IsNullOrWhiteSpace($a)) { return $default }
    return $a.Trim()
}
function Step($text) { Write-Host ""; Write-Host "== $text" -ForegroundColor Cyan }
function Run($exe, $arguments) {
    & $exe @arguments
    if ($LASTEXITCODE -ne 0) { throw "Comando non riuscito (codice $LASTEXITCODE): $exe $($arguments -join ' ')" }
}

Write-Host ""
Write-Host "StemLab: creazione della versione portable" -ForegroundColor Green
Write-Host "Serve internet solo adesso. Poi la cartella funziona da sola, anche su altri PC."
Write-Host ""
Write-Host "Che versione vuoi?"
Write-Host "  1) Completa: usa la GPU NVIDIA se c'e', altrimenti la CPU (circa 5-6 GB)"
Write-Host "  2) Solo CPU: piu' leggera (circa 1-2 GB), per PC senza scheda NVIDIA"
$variant = Ask "Scelta" "1"
if ($variant -ne "1" -and $variant -ne "2") { throw "Scelta non valida: scrivi 1 oppure 2." }

$torchIndex = "https://download.pytorch.org/whl/cpu"
$asExtra = "cpu"
if ($variant -eq "1") {
    Write-Host ""
    Write-Host "Versione CUDA di PyTorch. Con i driver NVIDIA piu' vecchi usa cu126."
    Write-Host "Con driver recenti (580 o superiore) va bene anche cu130."
    $cuda = Ask "CUDA" "cu128"
    $torchIndex = "https://download.pytorch.org/whl/$cuda"
    $asExtra = "gpu"
}

$dest = Ask "Dove creo la cartella? (percorso corto, meglio evitare cartelle annidate)" (Join-Path $src "StemLab_Portable")
if ($dest.Length -gt 60) {
    Write-Host "Attenzione: il percorso e' lungo. Windows puo' dare errori con i file di PyTorch." -ForegroundColor Yellow
    if ((Ask "Continuo lo stesso? (s/n)" "n") -ne "s") { throw "Interrotto: scegli un percorso piu' corto, per esempio C:\StemLab_Portable" }
}
if (Test-Path $dest) {
    if ((Ask "La cartella esiste gia'. La cancello e riparto da zero? (s/n)" "n") -ne "s") { throw "Interrotto." }
    Remove-Item -Recurse -Force $dest
}
$tmp = Join-Path $env:TEMP "stemlab_portable_dl"
New-Item -ItemType Directory -Force $dest, $tmp | Out-Null
$py = Join-Path $dest "python\python.exe"

Step "Scarico Python $PY_VER"
Invoke-WebRequest $PY_URL -OutFile (Join-Path $tmp "py.zip")
Expand-Archive (Join-Path $tmp "py.zip") (Join-Path $dest "python") -Force

Step "Preparo Python"
$pth = Get-ChildItem (Join-Path $dest "python") -Filter "python*._pth" | Select-Object -First 1
$zipName = (Get-ChildItem (Join-Path $dest "python") -Filter "python*.zip" | Select-Object -First 1).Name
Set-Content -Path $pth.FullName -Value @($zipName, ".", "Lib\site-packages", "import site") -Encoding ASCII
Invoke-WebRequest $PIP_URL -OutFile (Join-Path $tmp "get-pip.py")
Run $py @((Join-Path $tmp "get-pip.py"), "--no-warn-script-location")

Step "Installo PyTorch (e' il pezzo piu' grosso, ci vuole un po')"
Run $py @("-m", "pip", "install", "--no-warn-script-location", "torch", "torchaudio", "--index-url", $torchIndex)

Step "Installo le altre librerie"
Run $py @("-m", "pip", "install", "--no-warn-script-location", "audio-separator[$asExtra]", "fastapi", "uvicorn", "pywebview", "audioread")

Step "Copio StemLab"
Copy-Item (Join-Path $src "app.py") $dest
Copy-Item (Join-Path $src "static") (Join-Path $dest "static") -Recurse
New-Item -ItemType Directory -Force (Join-Path $dest "data") | Out-Null   # la sua presenza attiva la modalita' portable

Step "ffmpeg"
$ffDest = Join-Path $dest "ffmpeg"
New-Item -ItemType Directory -Force $ffDest | Out-Null
if (Test-Path (Join-Path $src "ffmpeg\ffmpeg.exe")) {
    Write-Host "Uso quello che hai gia' nella cartella stemlab."
    Copy-Item (Join-Path $src "ffmpeg\*") $ffDest -Recurse -Force
} else {
    Invoke-WebRequest $FF_URL -OutFile (Join-Path $tmp "ff.zip")
    Expand-Archive (Join-Path $tmp "ff.zip") (Join-Path $tmp "ff") -Force
    foreach ($n in "ffmpeg.exe", "ffprobe.exe") {
        $f = Get-ChildItem (Join-Path $tmp "ff") -Recurse -Filter $n | Select-Object -First 1
        Copy-Item $f.FullName $ffDest
    }
}

Step "Creo l'avvio"
$launcher = @(
    "@echo off",
    "cd /d ""%~dp0""",
    """%~dp0python\python.exe"" app.py",
    "if errorlevel 1 (",
    "  echo.",
    "  echo StemLab si e' chiuso con un errore. Copia il testo qui sopra se vuoi chiedere aiuto.",
    "  pause",
    ")"
)
Set-Content -Path (Join-Path $dest "StemLab.bat") -Value $launcher -Encoding ASCII

# Componente di Microsoft che mostra la finestra: c'e' gia' su Windows 11, a volte manca su Windows 10.
try {
    $extra = Join-Path $dest "extra"
    New-Item -ItemType Directory -Force $extra | Out-Null
    Invoke-WebRequest $WV2_URL -OutFile (Join-Path $extra "Installa_WebView2.exe")
} catch { Write-Host "Non sono riuscito a scaricare WebView2 (non e' grave): scaricalo da Microsoft se serve." -ForegroundColor Yellow }

Write-Host ""
if ((Ask "Scarico ora i modelli di separazione, circa 1-3 GB? Servono per usare l'app senza internet. (s/n)" "s") -eq "s") {
    Step "Scarico i modelli"
    Push-Location $dest
    & $py app.py --download-models
    Pop-Location
}

Remove-Item -Recurse -Force $tmp -ErrorAction SilentlyContinue
$size = [math]::Round((Get-ChildItem $dest -Recurse -File | Measure-Object Length -Sum).Sum / 1GB, 1)
Write-Host ""
Write-Host "Fatto. Cartella: $dest  (circa $size GB)" -ForegroundColor Green
Write-Host "Per usarla: copia l'intera cartella dove vuoi e fai doppio clic su StemLab.bat."
Write-Host "Se su un altro PC la finestra non si apre, esegui prima extra\Installa_WebView2.exe."
