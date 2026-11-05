# StemLab

App desktop locale per separare stem con modelli Roformer / MDX23C (via `audio-separator`).

## Installazione (Windows/Linux, Python 3.10-3.12)
1. Installa ffmpeg e mettilo nel PATH (serve per mp3/m4a/flac).
2. `python -m venv .venv` e attivalo.
3. `pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu124`
4. `pip install -r requirements.txt`
5. `python app.py`

I modelli si scaricano al primo utilizzo in `~/StemLab/models` (serve internet solo allora).

## Come funziona
Ogni stem e' prodotto da una pipeline a stadi, eseguita solo quando serve:
- `vox`: BS-Roformer -> voce + strumentale
- `sw`: BS-Roformer-SW -> batteria, basso, chitarra, piano, altro
- `kara`: Mel-Roformer karaoke (su voce) -> voce principale + cori
- `drum`: MDX23C DrumSep (su batteria) -> cassa, rullante, tom, hi-hat, ride, crash

Per cambiare modello modifica il dizionario `STAGES` in `app.py`
(elenco nomi validi: `audio-separator -l`). La qualita'/velocita' si sceglie dal menu nell'app (`PRESETS` in `app.py`).

## Scelta CPU / GPU
Nell'app, sotto il titolo del brano: **Automatico** (GPU NVIDIA se c'e', altrimenti CPU), **GPU** o **CPU**.
Sulla CPU la separazione e' molto piu' lenta: per brani lunghi usa il livello "Veloce".
Schede AMD e Intel non sono supportate: in quel caso l'app usa la CPU.

## Versione portable (si copia su altri PC)
1. Su questo PC (con internet) fai doppio clic su `Crea_portable.bat` e rispondi alle domande
   (versione completa GPU+CPU oppure solo CPU, versione di CUDA, dove creare la cartella).
2. Si crea `StemLab_Portable` con Python, librerie, ffmpeg e, se vuoi, i modelli.
3. Copia l'intera cartella dove vuoi (disco esterno, altro PC) e fai doppio clic su `StemLab.bat`.
   Modelli e file temporanei restano nella sottocartella `data`.
Sul PC di destinazione servono: Windows a 64 bit, driver NVIDIA aggiornato (non serve installare CUDA)
e il componente WebView2 (gia' presente su Windows 11; altrimenti esegui `extra\Installa_WebView2.exe`).
Tieni il percorso della cartella corto (es. `C:\StemLab_Portable`).

## Versione eseguibile (StemLab.exe)
1. Nella cartella stemlab, con l'ambiente `.venv` funzionante e la cartella `ffmpeg`, fai doppio clic su `Crea_exe.bat`.
2. Dopo 5-15 minuti trovi il programma in `dist\StemLab\`:
   - `StemLab.exe`: il programma, senza finestra nera
   - `StemLab-debug.exe`: lo stesso con la console, per vedere eventuali errori
3. La cartella `dist\StemLab` e' autonoma: non serve Python per usarla.
   Modelli e log restano in `C:\Users\<nome>\StemLab` (log: `stemlab.log`).
   Se accanto a StemLab.exe crei una cartella `data`, l'app usa quella (modalita' portable).
