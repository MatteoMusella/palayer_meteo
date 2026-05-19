# -*- coding: utf-8 -*-
"""
ecmwf_upload.py

Upload FTPS robusto per progetto meteo ECMWF.

Compatibile con:
- GitHub Codespace
- GitHub Actions
- PC locale

Logica cartelle:
PROJECT_DIR
└── output
    ├── interactive
    │   ├── export_summary.json
    │   ├── manifest.json
    │   ├── meteo_data.json
    │   └── meteo_data.json.gz
    │
    └── ecmwf
        ├── animations
        │   ├── wind.webp
        │   ├── gusts.webp
        │   ├── precipitation.webp
        │   ├── cloud_cover.webp
        │   ├── temperature.webp
        │   ├── pressure.webp
        │   └── wave_height.webp
        │
        └── eventuali altri file/cartelle

Upload remoto:
DATA:
  /www.igest.eu/wp-content/plugins/meteo/data/

FORECAST:
  /www.igest.eu/wp-content/plugins/meteo/forecast_png/ecmwf/**
  /www.igest.eu/wp-content/plugins/meteo/forecast_png/interactive/**
"""

import os
import json
import argparse
import socket
import time
from pathlib import Path
from datetime import datetime
from ftplib import FTP_TLS, error_perm


# ==========================================================
# BASE PROJECT
# ==========================================================

SCRIPT_DIR = Path(__file__).resolve().parent

# Se PROJECT_DIR esiste, lo usa.
# Altrimenti usa la cartella dove sta questo file.
# In Codespace puoi mettere:
# export PROJECT_DIR=/workspaces/palayer_meteo
#
# In GitHub Actions:
# PROJECT_DIR=${{ github.workspace }}
PROJECT_DIR = Path(os.getenv("PROJECT_DIR", SCRIPT_DIR)).resolve()

OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", PROJECT_DIR / "output")).resolve()
OUTPUT_INTERACTIVE_DIR = Path(
    os.getenv("OUTPUT_INTERACTIVE_DIR", OUTPUT_DIR / "interactive")
).resolve()

ECMWF_DIR = Path(os.getenv("ECMWF_DIR", OUTPUT_DIR / "ecmwf")).resolve()
ECMWF_ANIMATIONS_DIR = Path(
    os.getenv("ECMWF_ANIMATIONS_DIR", ECMWF_DIR / "animations")
).resolve()
ECMWF_FORECAST_PNG_DIR = Path(
    os.getenv("ECMWF_FORECAST_PNG_DIR", ECMWF_DIR / "forecast_png")
).resolve()
ECMWF_DATA_DIR = Path(
    os.getenv("ECMWF_DATA_DIR", ECMWF_DIR / "data")
).resolve()


CONFIG_PATH = PROJECT_DIR / "config.json"
LOG_PATH = PROJECT_DIR / "scheduler_log.txt"

STATE_DIR = PROJECT_DIR / "upload_state"


# ==========================================================
# CONFIG DEFAULT
# ==========================================================

DEFAULT_CONFIG = {
    "FTP_ENABLED": True,

    # Consigliato:
    # - in Codespace: usare variabili ambiente o config.json
    # - in GitHub Actions: usare Secrets
    "FTP_HOST": os.getenv("FTP_HOST", "ftp.igest.eu"),
    "FTP_PORT": int(os.getenv("FTP_PORT", "21")),
    "FTP_USER": os.getenv("FTP_USER", ""),
    "FTP_PASS": os.getenv("FTP_PASS", ""),

    "FTP_REMOTE_DATA_DIR": os.getenv(
        "FTP_REMOTE_DATA_DIR",
        "/www.igest.eu/wp-content/plugins/meteo/data"
    ),
    "FTP_REMOTE_FORECAST_DIR": os.getenv(
        "FTP_REMOTE_FORECAST_DIR",
        "/www.igest.eu/wp-content/plugins/meteo/forecast_png"
    ),

    # Local path coerenti con Codespace/GitHub Actions
    "LOCAL_DATA_DIR": os.getenv(
        "LOCAL_DATA_DIR",
        str(OUTPUT_INTERACTIVE_DIR)
    ),
    "LOCAL_FORECAST_ROOT": os.getenv(
        "LOCAL_FORECAST_ROOT",
        str(OUTPUT_DIR)
    ),

    "DATA_FILES": [
        "export_summary.json",
        "manifest.json",
        "meteo_data.json",
        "meteo_data.json.gz",
    ],

    "FTP_TIMEOUT_SECONDS": int(os.getenv("FTP_TIMEOUT_SECONDS", "60")),
    "FTP_RETRIES": int(os.getenv("FTP_RETRIES", "6")),
    "FTP_RETRY_SLEEP_SECONDS": int(os.getenv("FTP_RETRY_SLEEP_SECONDS", "4")),
    "FTP_BATCH_SIZE": int(os.getenv("FTP_BATCH_SIZE", "40")),
    "FTP_FILE_RETRIES": int(os.getenv("FTP_FILE_RETRIES", "3")),
    "FTP_FILE_RETRY_SLEEP_SECONDS": int(os.getenv("FTP_FILE_RETRY_SLEEP_SECONDS", "2")),

    # Se True, se manca un file locale lo salta e continua.
    # Se vuoi bloccare tutto quando manca un file, lancia:
    # python ecmwf_upload.py --all --fail-missing
    "SKIP_MISSING_FILES": True,

    "LOG_ENABLED": True,
}


# ==========================================================
# LOG
# ==========================================================

def log(msg: str):
    line = f"[{datetime.now().replace(microsecond=0).isoformat()}] {msg}"
    print(line, flush=True)

    try:
        if DEFAULT_CONFIG.get("LOG_ENABLED", True):
            LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
            with LOG_PATH.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
    except Exception:
        pass


# ==========================================================
# UTILS CONFIG
# ==========================================================

def as_bool(value, default=True) -> bool:
    if value is None:
        return default

    text = str(value).strip().lower()

    if text in ("1", "true", "yes", "on", "y", "si", "sì"):
        return True

    if text in ("0", "false", "no", "off", "n"):
        return False

    return default


def safe_int(value, default: int) -> int:
    try:
        return int(value)
    except Exception:
        return default


def load_config() -> dict:
    cfg = dict(DEFAULT_CONFIG)

    # config.json opzionale
    if CONFIG_PATH.exists():
        try:
            loaded = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                cfg.update(loaded)
        except Exception as e:
            log(f"Config non letto, uso default + env: {e}")

    # Override da variabili ambiente
    env_keys = [
        "FTP_ENABLED",
        "FTP_HOST",
        "FTP_PORT",
        "FTP_USER",
        "FTP_PASS",
        "FTP_REMOTE_DATA_DIR",
        "FTP_REMOTE_FORECAST_DIR",
        "LOCAL_DATA_DIR",
        "LOCAL_FORECAST_ROOT",
        "FTP_TIMEOUT_SECONDS",
        "FTP_RETRIES",
        "FTP_RETRY_SLEEP_SECONDS",
        "FTP_BATCH_SIZE",
        "FTP_FILE_RETRIES",
        "FTP_FILE_RETRY_SLEEP_SECONDS",
        "SKIP_MISSING_FILES",
        "LOG_ENABLED",
    ]

    int_keys = {
        "FTP_PORT",
        "FTP_TIMEOUT_SECONDS",
        "FTP_RETRIES",
        "FTP_RETRY_SLEEP_SECONDS",
        "FTP_BATCH_SIZE",
        "FTP_FILE_RETRIES",
        "FTP_FILE_RETRY_SLEEP_SECONDS",
    }

    bool_keys = {
        "FTP_ENABLED",
        "SKIP_MISSING_FILES",
        "LOG_ENABLED",
    }

    for key in env_keys:
        raw = os.getenv(key)

        if raw is None or str(raw).strip() == "":
            continue

        if key in int_keys:
            cfg[key] = safe_int(raw, int(cfg.get(key, 0)))
        elif key in bool_keys:
            cfg[key] = as_bool(raw, bool(cfg.get(key, True)))
        else:
            cfg[key] = str(raw).strip()

    return cfg


CFG = load_config()


# ==========================================================
# CARTELLE LOCALI
# ==========================================================

def ensure_local_dirs():
    """
    Crea tutte le cartelle locali utili PRIMA di scaricare/renderizzare/uploadare.
    Anche se alcune non servono subito, tenerle pronte evita errori.
    """

    local_data_dir = Path(CFG["LOCAL_DATA_DIR"]).resolve()
    local_forecast_root = Path(CFG["LOCAL_FORECAST_ROOT"]).resolve()

    dirs = [
        PROJECT_DIR,
        OUTPUT_DIR,
        OUTPUT_INTERACTIVE_DIR,
        ECMWF_DIR,
        ECMWF_ANIMATIONS_DIR,
        ECMWF_FORECAST_PNG_DIR,
        ECMWF_DATA_DIR,
        local_data_dir,
        local_forecast_root,
        local_forecast_root / "ecmwf",
        local_forecast_root / "ecmwf" / "animations",
        local_forecast_root / "interactive",
        STATE_DIR,
    ]

    for folder in dirs:
        folder.mkdir(parents=True, exist_ok=True)

    log("Cartelle locali verificate/create:")
    for folder in dirs:
        log(f" - {folder}")


# ==========================================================
# DEBUG FILE
# ==========================================================

def print_debug_paths():
    log("==========================================")
    log("DEBUG PATH")
    log("==========================================")
    log(f"SCRIPT_DIR={SCRIPT_DIR}")
    log(f"PROJECT_DIR={PROJECT_DIR}")
    log(f"OUTPUT_DIR={OUTPUT_DIR}")
    log(f"OUTPUT_INTERACTIVE_DIR={OUTPUT_INTERACTIVE_DIR}")
    log(f"ECMWF_DIR={ECMWF_DIR}")
    log(f"ECMWF_ANIMATIONS_DIR={ECMWF_ANIMATIONS_DIR}")
    log(f"ECMWF_FORECAST_PNG_DIR={ECMWF_FORECAST_PNG_DIR}")
    log(f"ECMWF_DATA_DIR={ECMWF_DATA_DIR}")
    log(f"LOCAL_DATA_DIR={CFG['LOCAL_DATA_DIR']}")
    log(f"LOCAL_FORECAST_ROOT={CFG['LOCAL_FORECAST_ROOT']}")
    log("==========================================")


def print_debug_files():
    root = Path(CFG["LOCAL_FORECAST_ROOT"]).resolve()

    log("==========================================")
    log("DEBUG FILE PRESENTI IN OUTPUT")
    log("==========================================")

    if not root.exists():
        log(f"Nessun output trovato: {root}")
        return

    files = sorted([p for p in root.rglob("*") if p.is_file()])

    if not files:
        log("Nessun file trovato in output.")
        return

    for p in files:
        try:
            rel = p.relative_to(root)
        except Exception:
            rel = p

        try:
            size = p.stat().st_size
        except Exception:
            size = 0

        log(f" - {rel} ({size} bytes)")

    log("==========================================")


# ==========================================================
# FTP CONFIG
# ==========================================================

def require_ftp_config():
    if not CFG.get("FTP_ENABLED", True):
        return

    missing = []

    for key in [
        "FTP_HOST",
        "FTP_USER",
        "FTP_PASS",
        "FTP_REMOTE_DATA_DIR",
        "FTP_REMOTE_FORECAST_DIR",
    ]:
        if not str(CFG.get(key, "")).strip():
            missing.append(key)

    if missing:
        raise RuntimeError(
            "Configurazione FTP mancante: "
            + ", ".join(missing)
            + ". Imposta questi valori in config.json, variabili ambiente o GitHub Secrets."
        )


def ftp_connect() -> FTP_TLS:
    host = str(CFG["FTP_HOST"]).strip()
    port = safe_int(CFG.get("FTP_PORT", 21), 21)
    timeout = safe_int(CFG.get("FTP_TIMEOUT_SECONDS", 60), 60)

    log(f"Tento connessione FTPS host={host} port={port} timeout={timeout}s")

    resolved = socket.gethostbyname(host)
    log(f"FTP host risolto: {host} -> {resolved}")

    ftp = FTP_TLS()
    ftp.connect(host, port, timeout=timeout)
    ftp.login(str(CFG["FTP_USER"]), str(CFG["FTP_PASS"]))
    ftp.prot_p()
    ftp.set_pasv(True)

    log("Connesso FTPS e login ok")
    return ftp


# ==========================================================
# FTP REMOTE DIR
# ==========================================================

def ensure_remote_dir(ftp: FTP_TLS, remote_dir: str):
    """
    Crea una cartella remota ricorsivamente.
    Se esiste già, continua.
    """

    remote_dir = str(remote_dir).replace("\\", "/").strip()

    if not remote_dir:
        return

    parts = [p for p in remote_dir.strip("/").split("/") if p]
    current = ""

    for part in parts:
        current += "/" + part

        try:
            ftp.cwd(current)
        except Exception:
            try:
                ftp.mkd(current)
                log(f"Creata dir remota: {current}")
            except error_perm:
                # Probabilmente esiste già oppure il server non permette MKD su path già presente.
                pass
            except Exception as e:
                log(f"ATTENZIONE: non riesco a creare dir remota {current}: {e}")

    try:
        ftp.cwd("/")
    except Exception:
        pass


def ftp_upload_file(ftp: FTP_TLS, local_path: Path, remote_path: str):
    remote_path = str(remote_path).replace("\\", "/")
    remote_folder = remote_path.rsplit("/", 1)[0]

    ensure_remote_dir(ftp, remote_folder)

    with local_path.open("rb") as f:
        ftp.storbinary(f"STOR {remote_path}", f)

    size = local_path.stat().st_size
    log(f"Upload OK: {local_path} -> {remote_path} ({size} bytes)")


# ==========================================================
# STATE / RESUME
# ==========================================================

def state_path_for(mode: str) -> Path:
    return STATE_DIR / f"upload_state_{mode}.json"


def load_state(mode: str) -> dict:
    path = state_path_for(mode)

    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    return {}


def save_state(mode: str, state: dict):
    path = state_path_for(mode)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(state, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )


def reset_state(mode: str):
    path = state_path_for(mode)

    if path.exists():
        path.unlink()


# ==========================================================
# LIST FILE LOCALI
# ==========================================================

def list_data_files() -> list[Path]:
    """
    I 4 file JSON principali vengono cercati in output/interactive.
    """

    data_dir = Path(CFG["LOCAL_DATA_DIR"]).resolve()
    data_dir.mkdir(parents=True, exist_ok=True)

    files = []

    for name in CFG.get("DATA_FILES", []):
        files.append(data_dir / name)

    return files


def list_forecast_files(subdir_name: str) -> list[Path]:
    """
    Cerca tutti i file in:
    output/ecmwf/**
    output/interactive/**
    """

    root = Path(CFG["LOCAL_FORECAST_ROOT"]).resolve()
    root.mkdir(parents=True, exist_ok=True)

    subdir = root / subdir_name
    subdir.mkdir(parents=True, exist_ok=True)

    files = sorted([p for p in subdir.rglob("*") if p.is_file()])

    return files


# ==========================================================
# BUILD UPLOAD PLAN
# ==========================================================

def build_file_plan(mode: str) -> list[tuple[Path, str]]:
    """
    mode=data:
      output/interactive/*.json -> /meteo/data

    mode=forecast:
      output/ecmwf/**       -> /forecast_png/ecmwf/**
      output/interactive/** -> /forecast_png/interactive/**

    mode=all:
      data + forecast
    """

    data_base = str(CFG["FTP_REMOTE_DATA_DIR"]).rstrip("/")
    forecast_base = str(CFG["FTP_REMOTE_FORECAST_DIR"]).rstrip("/")

    local_root = Path(CFG["LOCAL_FORECAST_ROOT"]).resolve()

    files: list[tuple[Path, str]] = []

    if mode in ("data", "all"):
        for local_file in list_data_files():
            remote_file = f"{data_base}/{local_file.name}"
            files.append((local_file, remote_file))

    if mode in ("forecast", "all"):
        # output/ecmwf/** -> remote forecast_png/ecmwf/**
        ecmwf_root = local_root / "ecmwf"
        ecmwf_root.mkdir(parents=True, exist_ok=True)

        for local_file in list_forecast_files("ecmwf"):
            try:
                rel = local_file.relative_to(ecmwf_root).as_posix()
            except Exception:
                rel = local_file.name

            remote_file = f"{forecast_base}/ecmwf/{rel}"
            files.append((local_file, remote_file))

        # output/interactive/** -> remote forecast_png/interactive/**
        interactive_root = local_root / "interactive"
        interactive_root.mkdir(parents=True, exist_ok=True)

        for local_file in list_forecast_files("interactive"):
            try:
                rel = local_file.relative_to(interactive_root).as_posix()
            except Exception:
                rel = local_file.name

            remote_file = f"{forecast_base}/interactive/{rel}"
            files.append((local_file, remote_file))

    # Rimuove duplicati mantenendo ordine.
    seen = set()
    unique_files = []

    for local_file, remote_file in files:
        key = (str(local_file), str(remote_file))

        if key in seen:
            continue

        seen.add(key)
        unique_files.append((local_file, remote_file))

    return unique_files


# ==========================================================
# UPLOAD CON RESUME
# ==========================================================

def upload_files_with_resume(
    mode: str,
    files: list[tuple[Path, str]],
    dry_run: bool = False,
):
    if not CFG.get("FTP_ENABLED", True):
        log("FTP disabilitato: FTP_ENABLED=false")
        return

    require_ftp_config()

    if not files:
        log("Nessun file da caricare.")
        return

    skip_missing = bool(CFG.get("SKIP_MISSING_FILES", True))

    valid_remote_paths = {remote for _, remote in files}

    state = load_state(mode)
    done = set(state.get("done", []))

    # Pulisce lo state da file che non fanno più parte del piano attuale.
    done = {remote for remote in done if remote in valid_remote_paths}

    remaining = [(local, remote) for local, remote in files if remote not in done]

    total = len(files)
    rem = len(remaining)

    log(
        f"Upload mode={mode} total={total} "
        f"remaining={rem} done={total - rem} dry_run={dry_run}"
    )

    if not remaining:
        log(f"Upload mode={mode}: GIA' COMPLETATO, niente da fare.")
        return

    batch_size = safe_int(CFG.get("FTP_BATCH_SIZE", 40), 40)
    retries = safe_int(CFG.get("FTP_RETRIES", 6), 6)
    sleep_s = safe_int(CFG.get("FTP_RETRY_SLEEP_SECONDS", 4), 4)
    file_retries = safe_int(CFG.get("FTP_FILE_RETRIES", 3), 3)
    file_sleep_s = safe_int(CFG.get("FTP_FILE_RETRY_SLEEP_SECONDS", 2), 2)

    idx = 0

    while idx < len(remaining):
        batch = remaining[idx: idx + batch_size]

        for attempt in range(1, retries + 1):
            ftp = None

            try:
                if not dry_run:
                    ftp = ftp_connect()

                for local_path, remote_path in batch:
                    local_path = Path(local_path)

                    if not local_path.exists():
                        msg = f"SKIP: manca in locale, non carico: {local_path}"

                        if skip_missing:
                            log(msg)
                            continue

                        raise FileNotFoundError(str(local_path))

                    if dry_run:
                        log(f"[DRY-RUN] Caricherei: {local_path} -> {remote_path}")
                        continue

                    last_file_err = None

                    for file_attempt in range(1, file_retries + 1):
                        try:
                            ftp_upload_file(ftp, local_path, remote_path)

                            done.add(remote_path)

                            state["done"] = sorted(done)
                            state["updated_at"] = datetime.now().isoformat()

                            save_state(mode, state)

                            last_file_err = None
                            break

                        except Exception as e:
                            last_file_err = e

                            log(
                                f"File upload fallito "
                                f"{file_attempt}/{file_retries}: "
                                f"{remote_path} err={e}"
                            )

                            if file_attempt < file_retries:
                                time.sleep(file_sleep_s)

                    if last_file_err is not None:
                        raise RuntimeError(
                            f"File non caricato dopo retry: "
                            f"{remote_path} err={last_file_err}"
                        )

                idx += batch_size
                break

            except Exception as e:
                log(f"Batch upload fallito tentativo {attempt}/{retries}: {e}")

                if attempt < retries:
                    time.sleep(sleep_s)
                    continue

                raise RuntimeError(
                    f"Batch upload fallito dopo {retries} tentativi. "
                    f"Ultimo errore: {e}"
                )

            finally:
                if ftp is not None:
                    try:
                        ftp.quit()
                    except Exception:
                        pass

                    log("Connessione FTPS chiusa")

    log(f"Upload mode={mode}: COMPLETATO. File nel piano={total}.")


# ==========================================================
# PUBLIC UPLOAD
# ==========================================================

def upload(mode: str, dry_run: bool = False):
    ensure_local_dirs()
    print_debug_paths()
    print_debug_files()

    files = build_file_plan(mode)

    log("==========================================")
    log("PIANO UPLOAD")
    log("==========================================")

    for local_path, remote_path in files:
        status = "OK" if local_path.exists() else "MISSING"
        log(f" - [{status}] {local_path} -> {remote_path}")

    log("==========================================")

    upload_files_with_resume(mode, files, dry_run=dry_run)


# ==========================================================
# CLI
# ==========================================================

def parse_args():
    parser = argparse.ArgumentParser()

    group = parser.add_mutually_exclusive_group()

    group.add_argument(
        "--only-data",
        action="store_true",
        help="Carica solo i file JSON data"
    )

    group.add_argument(
        "--only-forecast",
        action="store_true",
        help="Carica solo output/ecmwf + output/interactive"
    )

    group.add_argument(
        "--all",
        action="store_true",
        help="Carica tutto, default"
    )

    parser.add_argument(
        "--reset-state",
        action="store_true",
        help="Reset checkpoint della modalità scelta"
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Mostra cosa caricherebbe senza connettersi al server"
    )

    parser.add_argument(
        "--fail-missing",
        action="store_true",
        help="Blocca l'upload se un file locale non esiste"
    )

    parser.add_argument(
        "--debug-only",
        action="store_true",
        help="Crea cartelle e mostra debug senza caricare"
    )

    return parser.parse_args()


def main():
    args = parse_args()

    ensure_local_dirs()

    if args.only_data:
        mode = "data"
    elif args.only_forecast:
        mode = "forecast"
    else:
        mode = "all"

    if args.fail_missing:
        CFG["SKIP_MISSING_FILES"] = False

    if args.reset_state:
        reset_state(mode)
        log(f"State reset per mode={mode}")

    if args.debug_only:
        print_debug_paths()
        print_debug_files()
        files = build_file_plan(mode)

        log("PIANO UPLOAD DEBUG:")
        for local_path, remote_path in files:
            status = "OK" if local_path.exists() else "MISSING"
            log(f" - [{status}] {local_path} -> {remote_path}")

        return

    upload(mode, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
