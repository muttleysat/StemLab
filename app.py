"""StemLab - separazione stem locale: FastAPI + audio-separator, finestra con pywebview."""
import gc, os, queue, re, shutil, socket, sys, threading, time, traceback, uuid
from pathlib import Path

# --- Percorsi -------------------------------------------------------------------------------
# FROZEN: avviato come StemLab.exe (PyInstaller). RES_DIR contiene le risorse impacchettate
# (interfaccia, ffmpeg); APP_DIR e' la cartella dell'exe o di app.py.
FROZEN = getattr(sys, "frozen", False)
APP_DIR = Path(sys.executable).parent if FROZEN else Path(__file__).resolve().parent
RES_DIR = Path(getattr(sys, "_MEIPASS", APP_DIR))

# Dati (modelli, file temporanei, log): cartella "data" accanto all'app se esiste (versione portable),
# altrimenti ~/StemLab, cosi' i modelli gia' scaricati vengono riusati.
HOME = APP_DIR / "data" if (APP_DIR / "data").is_dir() else Path.home() / "StemLab"
MODELS, JOBS_DIR = HOME / "models", HOME / "jobs"
for d in (MODELS, JOBS_DIR):
    d.mkdir(parents=True, exist_ok=True)
LOG_FILE = HOME / "stemlab.log"

# Senza console (StemLab.exe) stdout/stderr non esistono: le barre di avanzamento andrebbero in errore.
# Si scrive tutto nel file di log.
if sys.stdout is None or sys.stderr is None:
    _log = open(LOG_FILE, "w", encoding="utf-8", buffering=1)
    sys.stdout = sys.stdout or _log
    sys.stderr = sys.stderr or _log
    sys.__stdout__ = sys.__stdout__ or _log  # alla chiusura Python prova a svuotare anche questi
    sys.__stderr__ = sys.__stderr__ or _log

# librosa usa una cache (numba) che deve stare in una cartella scrivibile.
os.environ.setdefault("NUMBA_CACHE_DIR", str(HOME / "numba_cache"))

# ffmpeg: prima la cartella "ffmpeg" accanto all'app, poi quella impacchettata, poi quella di sistema.
for _ff in (APP_DIR / "ffmpeg", RES_DIR / "ffmpeg"):
    if _ff.is_dir():
        os.environ["PATH"] = str(_ff) + os.pathsep + os.environ.get("PATH", "")
        break

# Nell'exe ogni chiamata a ffmpeg aprirebbe una finestra nera per un istante: la si nasconde.
if FROZEN and sys.platform == "win32":
    import subprocess

    class _NoWindowPopen(subprocess.Popen):
        def __init__(self, *args, **kwargs):
            kwargs["creationflags"] = kwargs.get("creationflags", 0) | 0x08000000  # CREATE_NO_WINDOW
            super().__init__(*args, **kwargs)

    subprocess.Popen = _NoWindowPopen

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel


def clean_old_jobs(max_age_h=24):
    """I brani vivono solo in memoria: le cartelle vecchie sono rimasugli e occupano spazio."""
    for d in JOBS_DIR.iterdir():
        try:
            if d.is_dir() and time.time() - d.stat().st_mtime > max_age_h * 3600:
                shutil.rmtree(d, ignore_errors=True)
        except OSError:
            pass

# overlap: piu' alto = qualita' migliore ma tempi proporzionalmente piu' lunghi.
# batch_size: blocchi elaborati insieme (piu' veloce, usa piu' VRAM; scendi se vedi "out of memory").
PRESETS = {
    "veloce":     dict(overlap=2, batch_size=4),
    "bilanciata": dict(overlap=4, batch_size=4),
    "massima":    dict(overlap=8, batch_size=2),
}

# Stadi della pipeline. "out" rinomina gli stem del modello; None = tieni tutto.
# Verifica i nomi dei modelli con: audio-separator -l
STAGES = {
    "vox":  dict(model="model_bs_roformer_ep_317_sdr_12.9755.ckpt", src="mix",
                 out={"vocals": "vocals", "instrumental": "instrumental"}),
    "sw":   dict(model="BS-Roformer-SW.ckpt", src="mix",
                 out={"bass": "bass", "drums": "drums", "other": "other",
                      "guitar": "guitar", "piano": "piano"}),
    "kara": dict(model="mel_band_roformer_karaoke_aufr33_viperx_sdr_10.1956.ckpt", src="vocals",
                 out={"vocals": "lead_vocal", "instrumental": "backing_vocal"}),
    # DrumSep produce 6 parti: kick, snare, toms, hh, ride, crash
    "drum": dict(model="MDX23C-DrumSep-aufr33-jarredou.ckpt", src="drums",
                 out={"kick": "kick", "snare": "snare", "toms": "toms", "hh": "hihat",
                      "ride": "ride", "crash": "crash"}),
}
DEPS = {"kara": "vox", "drum": "sw"}  # stadio -> stadio che produce il suo input

CATALOG = [  # id, etichetta, gruppo, stadio
    ("vocals", "Voce", "Voce", "vox"),
    ("lead_vocal", "Voce principale", "Voce", "kara"),
    ("backing_vocal", "Cori", "Voce", "kara"),
    ("instrumental", "Base strumentale", "Strumenti", "vox"),
    ("drums", "Batteria", "Strumenti", "sw"),
    ("bass", "Basso", "Strumenti", "sw"),
    ("guitar", "Chitarra", "Strumenti", "sw"),
    ("piano", "Piano e tastiere", "Strumenti", "sw"),
    ("other", "Altro", "Strumenti", "sw"),
    ("kick", "Cassa", "Batteria", "drum"),
    ("snare", "Rullante", "Batteria", "drum"),
    ("toms", "Tom", "Batteria", "drum"),
    ("hihat", "Hi-hat", "Batteria", "drum"),
    ("ride", "Ride", "Batteria", "drum"),
    ("crash", "Crash", "Batteria", "drum"),
]
STEM_STAGE = {c[0]: c[3] for c in CATALOG}

app = FastAPI()
JOBS, LOCK, Q = {}, threading.Lock(), queue.Queue()
SYSTEM = {"ready": False, "gpu": False, "name": ""}


def probe_gpu():
    """Controlla se c'e' una GPU NVIDIA utilizzabile (in un thread: importare torch richiede qualche secondo)."""
    try:
        import torch
        if torch.cuda.is_available():
            SYSTEM.update(gpu=True, name=torch.cuda.get_device_name(0))
    except Exception:
        pass
    SYSTEM["ready"] = True


def set_progress(job, stage, phase, frac=None):
    with LOCK:
        job["progress"][stage] = (phase, frac)


def progress_tqdm(report):
    """Barra di avanzamento di audio-separator (tqdm) che comunica anche la percentuale all'app."""
    from tqdm import tqdm as _tqdm

    class ProgressTqdm(_tqdm):
        def __init__(self, *args, **kwargs):
            kwargs["disable"] = False  # senza console tqdm si disattiverebbe e smetterebbe di contare
            super().__init__(*args, **kwargs)
            if self.total:
                report(0.0)

        def update(self, n=1):
            r = super().update(n)
            if self.total:
                report(min(1.0, self.n / self.total))
            return r

        def close(self):
            if self.total and not self.disable:
                report(min(1.0, self.n / self.total))
            super().close()

    return ProgressTqdm


def run_stage(job, stage, preset="bilanciata", device="auto"):
    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg non trovato: copia ffmpeg.exe e ffprobe.exe nella cartella ffmpeg accanto al programma")
    cfg = STAGES[stage]
    src = job["mix"] if cfg["src"] == "mix" else job["files"].get(cfg["src"])
    if not src or not Path(src).exists():
        raise RuntimeError("Manca lo stem di partenza: riprova prima lo stadio precedente.")
    out = job["dir"] / f"_{stage}"
    out.mkdir(exist_ok=True)
    inp = out / ("in" + Path(src).suffix)  # nome semplice: il parsing dei file resta affidabile
    shutil.copy(src, inp)
    set_progress(job, stage, "prepare")
    from audio_separator.separator import Separator
    # download dei modelli: la barra e' nel modulo separator di audio-separator
    sep_mod = sys.modules.get("audio_separator.separator.separator")
    if sep_mod is not None and hasattr(sep_mod, "tqdm"):
        sep_mod.tqdm = progress_tqdm(lambda f: set_progress(job, stage, "download", f))
    pr = PRESETS.get(preset, PRESETS["bilanciata"])
    kw = dict(output_dir=str(out), output_format="WAV", model_file_dir=str(MODELS), use_autocast=True,
              mdxc_params={"segment_size": 256, "batch_size": pr["batch_size"], "overlap": pr["overlap"],
                           "override_model_segment_size": False, "pitch_shift": 0})
    try:
        sep = Separator(**kw)
    except TypeError:  # versioni senza use_autocast
        kw.pop("use_autocast")
        sep = Separator(**kw)
    # dispositivo: "auto" lascia scegliere ad audio-separator (GPU se c'e'), "cpu" la forza, "gpu" la pretende
    if device == "cpu":
        sep.torch_device = sep.torch_device_cpu
        sep.onnx_execution_provider = ["CPUExecutionProvider"]
    elif device == "gpu" and getattr(sep.torch_device, "type", "") != "cuda":
        raise RuntimeError("Nessuna GPU NVIDIA disponibile su questo computer: scegli Automatico o CPU.")
    on_gpu = getattr(sep.torch_device, "type", "") == "cuda"
    sep.use_autocast = on_gpu  # la precisione ridotta aiuta solo sulla GPU
    with LOCK:
        job["on"] = "GPU" if on_gpu else "CPU"
    sep.load_model(cfg["model"])
    # separazione: le barre sono nei moduli delle architetture, importati da load_model
    for name, mod in list(sys.modules.items()):
        if name.startswith("audio_separator.separator.architectures.") and hasattr(mod, "tqdm"):
            mod.tqdm = progress_tqdm(lambda f: set_progress(job, stage, "separate", f))
    set_progress(job, stage, "separate", 0.0)
    names = sep.separate(str(inp))
    for n in names:
        p = Path(n) if Path(n).is_absolute() else out / Path(n).name
        m = re.search(r"\(([^)]+)\)", p.name)
        raw = (m.group(1) if m else p.stem).lower().replace(" ", "_")
        sid = (cfg["out"] or {}).get(raw, raw)
        if cfg["out"] is not None and raw not in cfg["out"] and sid not in STEM_STAGE:
            continue  # stem del modello che non ci serve
        dest = job["dir"] / f"{sid}.wav"
        shutil.move(str(p), dest)
        with LOCK:
            job["files"][sid] = str(dest)
    del sep
    gc.collect()
    try:
        import torch
        torch.cuda.empty_cache()
    except Exception:
        pass


def worker():  # una sola GPU: gli stadi vanno in fila
    while True:
        jid, stage, preset, device = Q.get()
        job = JOBS[jid]
        try:
            with LOCK:
                job["stages"][stage] = "running"
            run_stage(job, stage, preset, device)
            with LOCK:
                job["stages"][stage] = "done"
                job["on"] = ""
                job["progress"].pop(stage, None)
        except Exception as e:
            # traceback completo nella console (StemLab-debug.exe) e nel log; nell'interfaccia anche file e riga
            print(f"\n--- Errore nello stadio '{stage}' ---", file=sys.stderr)
            traceback.print_exc()
            sys.stderr.flush()
            tb = traceback.extract_tb(e.__traceback__)
            where = f" [{Path(tb[-1].filename).name}:{tb[-1].lineno}]" if tb else ""
            with LOCK:
                job["stages"][stage] = "error"
                job["errors"][stage] = (f"{type(e).__name__}: {e}{where}")[:300]
                job["on"] = ""
                job["progress"].pop(stage, None)


def view(job):
    stems = []
    for sid, label, group, stage in CATALOG:
        st = job["stages"].get(stage)
        if st is None:
            status, err = "idle", ""
        elif st == "done":
            ok = sid in job["files"]
            status, err = ("ready", "") if ok else ("error", "Il modello non ha prodotto questo stem.")
        elif sid not in job["wanted"]:
            status, err = "idle", ""  # lo stadio e' attivo, ma questo stem non e' stato richiesto
        elif st == "error":
            status, err = "error", job["errors"].get(stage, "Errore")
        else:
            status, err = st, ""
        phase, frac = job["progress"].get(stage, (None, None)) if status == "running" else (None, None)
        stems.append(dict(id=sid, label=label, group=group, status=status, error=err,
                          on=job.get("on", "") if status == "running" else "",
                          phase=phase, progress=None if frac is None else int(frac * 100)))
    return dict(id=job["id"], name=job["name"], stems=stems)


def new_job(name):
    jid = uuid.uuid4().hex[:10]
    d = JOBS_DIR / jid
    d.mkdir()
    mix = d / ("mix" + (Path(name).suffix.lower() or ".wav"))
    JOBS[jid] = dict(id=jid, name=Path(name).stem, dir=d, mix=str(mix),
                     files={}, stages={}, errors={}, wanted=set(), on="", progress={})
    return JOBS[jid], mix


@app.post("/api/upload")
async def upload(request: Request, name: str = "brano.wav"):
    job, mix = new_job(name)
    with open(mix, "wb") as f:
        async for chunk in request.stream():
            f.write(chunk)
    if mix.stat().st_size == 0:
        raise HTTPException(400, "File vuoto")
    return view(job)


@app.get("/api/system")
def system():
    return SYSTEM


@app.get("/api/jobs/{jid}")
def get_job(jid: str):
    if jid not in JOBS:
        raise HTTPException(404, "Brano non trovato")
    with LOCK:
        return view(JOBS[jid])


class Req(BaseModel):
    ids: list[str]
    preset: str = "bilanciata"
    device: str = "auto"  # auto | gpu | cpu


@app.post("/api/jobs/{jid}/stems")
def request_stems(jid: str, req: Req):
    job = JOBS.get(jid)
    if not job:
        raise HTTPException(404, "Brano non trovato")
    with LOCK:
        for sid in req.ids:
            if sid not in STEM_STAGE:
                continue
            job["wanted"].add(sid)
            st = STEM_STAGE[sid]
            for s in ([DEPS[st]] if st in DEPS else []) + [st]:
                if job["stages"].get(s) in (None, "error"):
                    job["stages"][s] = "queued"
                    Q.put((jid, s, req.preset, req.device))
        return view(job)


def stem_path(jid, name):
    job = JOBS.get(jid)
    if not job:
        raise HTTPException(404)
    p = job["mix"] if name == "mix" else job["files"].get(name.removesuffix(".wav"))
    if not p or not Path(p).exists():
        raise HTTPException(404)
    return Path(p)


@app.get("/files/{jid}/{name}")
def files(jid: str, name: str):
    return FileResponse(stem_path(jid, name))


app.mount("/", StaticFiles(directory=RES_DIR / "static", html=True, check_dir=False))  # controllo in main()


class Api:  # esposta al JS: finestre native di apertura e salvataggio
    def pick(self):
        import webview
        kind = webview.FileDialog.OPEN if hasattr(webview, "FileDialog") else webview.OPEN_DIALOG
        r = WIN.create_file_dialog(kind, allow_multiple=False, file_types=(
            "Audio (*.mp3;*.wav;*.flac;*.m4a;*.ogg;*.aac;*.aiff;*.aif;*.opus;*.wma)", "Tutti i file (*.*)"))
        if not r:
            return None
        src = Path(r if isinstance(r, str) else r[0])
        job, mix = new_job(src.name)
        shutil.copy(src, mix)
        return view(job)

    def save(self, jid, sid):
        import webview
        job = JOBS[jid]
        label = next(c[1] for c in CATALOG if c[0] == sid)
        kind = webview.FileDialog.SAVE if hasattr(webview, "FileDialog") else webview.SAVE_DIALOG
        r = WIN.create_file_dialog(kind, save_filename=f"{job['name']} - {label}.wav",
                                   file_types=("WAV (*.wav)",))
        if not r:
            return {"cancelled": True}
        dest = r if isinstance(r, str) else r[0]
        shutil.copy(stem_path(jid, sid), dest)
        return {"ok": True, "path": str(dest)}


def download_models():
    """python app.py --download-models: scarica i modelli in anticipo (per usare l'app senza internet)."""
    from audio_separator.separator import Separator
    for stage, cfg in STAGES.items():
        print(f"Scarico il modello '{cfg['model']}'...", flush=True)
        try:
            Separator(model_file_dir=str(MODELS), output_dir=str(JOBS_DIR)).load_model(cfg["model"])
        except Exception as e:
            print(f"  non riuscito: {e}", flush=True)


def wait_for_port(port, timeout=20):
    end = time.time() + timeout
    while time.time() < end:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                return True
        except OSError:
            time.sleep(0.2)
    return False


def show_error(text):
    """Nell'exe senza console un errore all'avvio sarebbe invisibile: lo si mostra in una finestra."""
    print(text, file=sys.stderr, flush=True)
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(0, text, "StemLab", 0x10)
        except Exception:
            pass


def main():
    global WIN
    if "--download-models" in sys.argv:
        download_models()
        return
    if not (RES_DIR / "static" / "index.html").is_file():
        raise RuntimeError(f"Manca l'interfaccia ({RES_DIR / 'static'}): reinstalla o ricrea StemLab.")
    import webview
    clean_old_jobs()
    threading.Thread(target=probe_gpu, daemon=True).start()
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    threading.Thread(target=worker, daemon=True).start()
    threading.Thread(target=uvicorn.run, args=(app,), daemon=True,
                     kwargs=dict(host="127.0.0.1", port=port, log_level="warning")).start()
    if not wait_for_port(port):
        raise RuntimeError("Il server interno non e' partito.")
    WIN = webview.create_window("StemLab", f"http://127.0.0.1:{port}", width=980, height=800,
                                min_size=(640, 560), js_api=Api())
    webview.start()


if __name__ == "__main__":
    import multiprocessing
    multiprocessing.freeze_support()
    try:
        main()
    except Exception:
        show_error("StemLab non e' riuscito ad avviarsi.\n\n" + traceback.format_exc()[-1500:] +
                   f"\n\nDettagli nel file: {LOG_FILE}")
        sys.exit(1)
