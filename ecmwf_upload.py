# -*- coding: utf-8 -*-
"""
upload_meteo.py (robust FTPS upload + resume)

Upload FTPS:
DATA:
  /www.igest.eu/wp-content/plugins/meteo/data/
    - export_summary.json
    - manifest.json
    - meteo_data.json
    - meteo_data.json.gz

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


BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "config.json"
LOG_PATH = BASE_DIR / "scheduler_log.txt"

STATE_DIR = BASE_DIR / "upload_state"
STATE_DIR.mkdir(parents=True, exist_ok=True)


DEFAULT_CONFIG = {
    "FTP_ENABLED": True,

    "FTP_HOST": "ftp.igest.eu",
    "FTP_PORT": 21,
    "FTP_USER": "1220347@aruba.it",
    "FTP_PASS": "Asroma1927!",
    "FTP_REMOTE_DATA_DIR": "/www.igest.eu/wp-content/plugins/meteo/data",
    "FTP_REMOTE_FORECAST_DIR": "/www.igest.eu/wp-content/plugins/meteo/forecast_png",

    # LOCAL PATHS (Codespace reali)
    "LOCAL_DATA_DIR": "/workspaces/palayer_meteo/output/interactive",
    "LOCAL_FORECAST_ROOT": "/workspaces/palayer_meteo/output",

    "DATA_FILES": [
        "export_summary.json",
        "manifest.json",
        "meteo_data.json",
        "meteo_data.json.gz",
    ],

    "FTP_TIMEOUT_SECONDS": 60,
    "FTP_RETRIES": 6,
    "FTP_RETRY_SLEEP_SECONDS": 4,
    "FTP_BATCH_SIZE": 40,
    "FTP_FILE_RETRIES": 3,
    "FTP_FILE_RETRY_SLEEP_SECONDS": 2,
    "LOG_ENABLED": True,
}


def log(msg: str):
    line = f"[{datetime.now().replace(microsecond=0).isoformat()}] {msg}"
    print(line)
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def load_config() -> dict:
    cfg = dict(DEFAULT_CONFIG)
    if CONFIG_PATH.exists():
        try:
            loaded = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                cfg.update(loaded)
        except Exception as e:
            log(f"Config non letto, uso default: {e}")

    env_map = {
        "FTP_ENABLED": "FTP_ENABLED",
        "FTP_HOST": "FTP_HOST",
        "FTP_PORT": "FTP_PORT",
        "FTP_USER": "FTP_USER",
        "FTP_PASS": "FTP_PASS",
        "FTP_REMOTE_DATA_DIR": "FTP_REMOTE_DATA_DIR",
        "FTP_REMOTE_FORECAST_DIR": "FTP_REMOTE_FORECAST_DIR",
        "LOCAL_DATA_DIR": "LOCAL_DATA_DIR",
        "LOCAL_FORECAST_ROOT": "LOCAL_FORECAST_ROOT",
        "FTP_TIMEOUT_SECONDS": "FTP_TIMEOUT_SECONDS",
        "FTP_RETRIES": "FTP_RETRIES",
        "FTP_RETRY_SLEEP_SECONDS": "FTP_RETRY_SLEEP_SECONDS",
        "FTP_BATCH_SIZE": "FTP_BATCH_SIZE",
        "FTP_FILE_RETRIES": "FTP_FILE_RETRIES",
        "FTP_FILE_RETRY_SLEEP_SECONDS": "FTP_FILE_RETRY_SLEEP_SECONDS",
    }
    for k, envk in env_map.items():
        if envk in os.environ and str(os.environ[envk]).strip() != "":
            v = os.environ[envk].strip()
            if k in ("FTP_ENABLED",):
                cfg[k] = v.lower() in ("1", "true", "yes", "on")
            elif k in ("FTP_PORT", "FTP_TIMEOUT_SECONDS", "FTP_RETRIES", "FTP_RETRY_SLEEP_SECONDS",
                       "FTP_BATCH_SIZE", "FTP_FILE_RETRIES", "FTP_FILE_RETRY_SLEEP_SECONDS"):
                try:
                    cfg[k] = int(v)
                except Exception:
                    pass
            else:
                cfg[k] = v
    return cfg


CFG = load_config()


def _require_ftp_config():
    if not CFG.get("FTP_ENABLED", True):
        return
    missing = []
    for k in ("FTP_HOST", "FTP_USER", "FTP_PASS", "FTP_REMOTE_DATA_DIR", "FTP_REMOTE_FORECAST_DIR"):
        if not str(CFG.get(k, "")).strip():
            missing.append(k)
    if missing:
        raise RuntimeError("Configurazione FTP mancante: " + ", ".join(missing))


def ftp_connect() -> FTP_TLS:
    host = str(CFG["FTP_HOST"]).strip()
    port = int(CFG["FTP_PORT"])
    timeout = int(CFG.get("FTP_TIMEOUT_SECONDS", 60))

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


def ensure_remote_dir(ftp: FTP_TLS, remote_dir: str):
    parts = [p for p in remote_dir.strip("/").split("/") if p]
    current = ""
    for part in parts:
        current += "/" + part
        try:
            ftp.mkd(current)
            log(f"Creata dir remota: {current}")
        except error_perm:
            pass


def ftp_upload_file(ftp: FTP_TLS, local_path: Path, remote_path: str):
    remote_folder = remote_path.rsplit("/", 1)[0]
    ensure_remote_dir(ftp, remote_folder)
    with local_path.open("rb") as f:
        ftp.storbinary(f"STOR {remote_path}", f)
    log(f"Upload OK: {remote_path}")


def state_path_for(mode: str) -> Path:
    return STATE_DIR / f"upload_state_{mode}.json"


def load_state(mode: str) -> dict:
    p = state_path_for(mode)
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_state(mode: str, st: dict):
    p = state_path_for(mode)
    p.write_text(json.dumps(st, indent=2, ensure_ascii=False), encoding="utf-8")


def reset_state(mode: str):
    p = state_path_for(mode)
    if p.exists():
        p.unlink()


def list_data_files() -> list[Path]:
    data_dir = Path(CFG["LOCAL_DATA_DIR"])
    return [data_dir / name for name in CFG.get("DATA_FILES", [])]


def list_forecast_files(subdir_name: str) -> list[Path]:
    root = Path(CFG["LOCAL_FORECAST_ROOT"])
    subdir = root / subdir_name
    if not subdir.exists():
        return []
    return sorted([p for p in subdir.rglob("*") if p.is_file()])


def upload_files_with_resume(mode: str, files: list[tuple[Path, str]], dry_run: bool = False):
    if not CFG.get("FTP_ENABLED", True):
        log("FTP disabilitato (FTP_ENABLED=false).")
        return

    _require_ftp_config()

    if not files:
        log("Nessun file da caricare.")
        return

    st = load_state(mode)
    done = set(st.get("done", []))
    remaining = [(lp, rp) for (lp, rp) in files if rp not in done]

    total = len(files)
    rem = len(remaining)
    log(f"Upload mode={mode} total={total} remaining={rem} done={total - rem} dry_run={dry_run}")

    if not remaining:
        log(f"Upload mode={mode}: GIA' COMPLETATO (niente da fare).")
        return

    batch_size = int(CFG.get("FTP_BATCH_SIZE", 40))
    retries = int(CFG.get("FTP_RETRIES", 6))
    sleep_s = int(CFG.get("FTP_RETRY_SLEEP_SECONDS", 4))
    file_retries = int(CFG.get("FTP_FILE_RETRIES", 3))
    file_sleep_s = int(CFG.get("FTP_FILE_RETRY_SLEEP_SECONDS", 2))

    idx = 0
    while idx < len(remaining):
        batch = remaining[idx: idx + batch_size]
        last_err = None
        for attempt in range(1, retries + 1):
            ftp = None
            try:
                if not dry_run:
                    ftp = ftp_connect()

                for local_path, remote_path in batch:
                    if not local_path.exists():
                        log(f"ERRORE: manca in locale, non posso caricare: {local_path}")
                        continue

                    if dry_run:
                        log(f"[DRY-RUN] Caricherei: {local_path} -> {remote_path}")
                        continue

                    last_file_err = None
                    for fa in range(1, file_retries + 1):
                        try:
                            ftp_upload_file(ftp, local_path, remote_path)
                            done.add(remote_path)
                            st["done"] = sorted(done)
                            st["updated_at"] = datetime.now().isoformat()
                            save_state(mode, st)
                            last_file_err = None
                            break
                        except Exception as e:
                            last_file_err = e
                            log(f"File upload fallito {fa}/{file_retries}: {remote_path} err={e}")
                            if fa < file_retries:
                                time.sleep(file_sleep_s)
                    if last_file_err is not None:
                        raise RuntimeError(f"File non caricato dopo retry: {remote_path} err={last_file_err}")

                idx += batch_size
                last_err = None
                break

            except Exception as e:
                last_err = e
                log(f"Batch upload fallito tentativo {attempt}/{retries}: {e}")
                if attempt < retries:
                    time.sleep(sleep_s)
                    continue
                raise RuntimeError(f"Batch upload fallito dopo {retries} tentativi. Ultimo errore: {last_err}")

            finally:
                if ftp is not None:
                    try:
                        ftp.quit()
                    except Exception:
                        pass
                    log("Connessione FTPS chiusa")

    log(f"Upload mode={mode}: COMPLETATO (files={total}).")


def build_file_plan(mode: str) -> list[tuple[Path, str]]:
    data_base = str(CFG["FTP_REMOTE_DATA_DIR"]).rstrip("/")
    forecast_base = str(CFG["FTP_REMOTE_FORECAST_DIR"]).rstrip("/")

    files: list[tuple[Path, str]] = []

    if mode in ("data", "all"):
        for p in list_data_files():
            files.append((p, f"{data_base}/{p.name}"))

    if mode in ("forecast", "all"):
        # ecmwf -> /forecast_png/ecmwf/**
        for p in list_forecast_files("ecmwf"):
            rel = p.relative_to(Path(CFG["LOCAL_FORECAST_ROOT"]) / "ecmwf").as_posix()
            files.append((p, f"{forecast_base}/ecmwf/{rel}"))

        # interactive -> /forecast_png/interactive/**
        for p in list_forecast_files("interactive"):
            rel = p.relative_to(Path(CFG["LOCAL_FORECAST_ROOT"]) / "interactive").as_posix()
            files.append((p, f"{forecast_base}/interactive/{rel}"))

    return files


def upload(mode: str, dry_run: bool = False):
    files = build_file_plan(mode)
    upload_files_with_resume(mode, files, dry_run=dry_run)


def parse_args():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--only-data", action="store_true", help="Carica solo i 4 file data/*.json(.gz)")
    g.add_argument("--only-forecast", action="store_true", help="Carica solo forecast_png/ecmwf + interactive")
    g.add_argument("--all", action="store_true", help="Carica tutto (default)")

    ap.add_argument("--reset-state", action="store_true", help="Reset checkpoint (riparti da zero per la modalità scelta)")
    ap.add_argument("--dry-run", action="store_true", help="Stampa cosa caricherebbe senza connettersi all'FTP")
    return ap.parse_args()


def main():
    args = parse_args()

    if args.only_data:
        mode = "data"
    elif args.only_forecast:
        mode = "forecast"
    else:
        mode = "all"

    if args.reset_state:
        reset_state(mode)
        log(f"State reset per mode={mode}")

    upload(mode, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
