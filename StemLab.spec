# -*- mode: python ; coding: utf-8 -*-
# Configurazione PyInstaller di StemLab. Si usa con Crea_exe.bat.
# Risultato: dist\StemLab\ con
#   StemLab.exe        il programma, senza finestra nera
#   StemLab-debug.exe  lo stesso programma con la console, per vedere gli errori
import ast
import os
import sys
import sysconfig
from pathlib import Path
from PyInstaller.utils.hooks import collect_all, copy_metadata

sys.setrecursionlimit(5000)  # l'analisi di PyTorch e' profonda

datas = [("static", "static")]
binaries = []
hiddenimports = []

if os.path.isdir("ffmpeg"):
    datas.append(("ffmpeg", "ffmpeg"))
else:
    print("[StemLab] ATTENZIONE: cartella ffmpeg non trovata, l'exe non potra' leggere gli mp3")

# Pacchetti con file di dati, DLL o moduli caricati al volo che PyInstaller da solo non vede.
# (PyTorch ha gia' le sue regole in pyinstaller-hooks-contrib.)
for pkg in [
    "audio_separator",   # carica le architetture con importlib e legge models.json
    "webview",           # finestra: file js e DLL di WebView2
    "clr_loader",        # ponte .NET usato da pywebview su Windows
    "librosa", "resampy", "samplerate", "soundfile",
    "onnxruntime",
    "rotary_embedding_torch", "beartype", "einops", "julius", "ml_collections",
    "uvicorn",
]:
    try:
        d, b, h = collect_all(pkg)
        datas += d
        binaries += b
        hiddenimports += h
    except Exception as e:
        print(f"[StemLab] salto {pkg}: {e}")

# Metadati dei pacchetti: audio-separator li legge all'avvio e senza si blocca.
for dist in ["audio-separator", "torch", "torchaudio", "onnxruntime", "onnxruntime-gpu",
             "librosa", "numpy", "scipy", "pywebview", "fastapi", "uvicorn", "starlette", "pydantic"]:
    try:
        datas += copy_metadata(dist)
    except Exception:
        pass


def modules_needing_source():
    """Con alcune versioni di Python (es. 3.12.0) le comprehension a livello di modulo che chiamano
    dir()/locals()/vars() senza argomenti, una volta impacchettate, restituiscono un elenco vuoto
    (scipy.stats: "NameError: name 'obj' is not defined"). Quei moduli si includono come sorgente,
    cosi' vengono compilati all'avvio come con Python normale."""
    found = {}
    paths = sysconfig.get_paths()
    for base in {Path(paths["purelib"]), Path(paths["platlib"])}:
        for p in base.rglob("*.py"):
            parts = p.relative_to(base).with_suffix("").parts
            if not all(x.isidentifier() for x in parts) or any(x in ("tests", "test") for x in parts):
                continue
            try:
                src = p.read_text(encoding="utf-8")
            except Exception:
                continue
            if "dir()" not in src and "locals()" not in src and "vars()" not in src:
                continue
            try:
                tree = ast.parse(src)
            except Exception:
                continue
            hit = False
            for node in tree.body:
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    continue
                for sub in ast.walk(node):
                    if isinstance(sub, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
                        for c in ast.walk(sub):
                            if (isinstance(c, ast.Call) and isinstance(c.func, ast.Name)
                                    and c.func.id in ("dir", "locals", "vars") and not c.args):
                                hit = True
            if hit:
                name = ".".join(parts[:-1] if parts[-1] == "__init__" else parts)
                if name:
                    found[name] = "py"
    return found


collection_mode = modules_needing_source()
print(f"[StemLab] moduli inclusi come sorgente per compatibilita': {len(collection_mode)}")
collection_mode.update({
    # "py": solo sorgenti su disco (servono alla cache di numba usata da librosa/resampy).
    # "pyz+py": anche i sorgenti, per le librerie che li leggono durante l'esecuzione.
    "librosa": "py",
    "resampy": "py",
    "audio_separator": "pyz+py",
    "beartype": "pyz+py",
    "rotary_embedding_torch": "pyz+py",
    "einops": "pyz+py",
    "julius": "pyz+py",
})

a = Analysis(
    ["app.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "IPython", "pytest", "notebook", "matplotlib"],
    module_collection_mode=collection_mode,
    noarchive=False,
)
pyz = PYZ(a.pure)

exe_gui = EXE(pyz, a.scripts, [], exclude_binaries=True, name="StemLab",
              console=False, icon="stemlab.ico", upx=False)
exe_dbg = EXE(pyz, a.scripts, [], exclude_binaries=True, name="StemLab-debug",
              console=True, icon="stemlab.ico", upx=False)

coll = COLLECT(exe_gui, exe_dbg, a.binaries, a.datas, strip=False, upx=False, name="StemLab")
