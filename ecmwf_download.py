import json
import time
import traceback
from pathlib import Path
from datetime import datetime

from ecmwf.opendata import Client


# ============================================================
# ARDEA METEO PLAYER 1.0
# ECMWF OPEN DATA DOWNLOADER
#
# Scarica:
# - meteo IFS: vento, raffiche, temp, pioggia, nuvole, pressione
# - onde ECMWF Wave: swh
#
# Output compatibile con render.py:
#
# C:\Users\PC_Matteo\Desktop\meteo\input\ecmwf\
#   run_meta.json
#   u10_h003.grib
#   v10_h003.grib
#   gust_h003.grib
#   temperature_h003.grib
#   precipitation_h003.grib
#   cloud_cover_h003.grib
#   pressure_h003.grib
#   wave_height_h003.grib
# ============================================================


# ============================================================
# CARTELLE
# ============================================================

BASE_DIR = Path(__file__).resolve().parent
INPUT_DIR = BASE_DIR / "input" / "ecmwf"
INPUT_DIR.mkdir(parents=True, exist_ok=True)


# ============================================================
# CONFIG GENERALE
# ============================================================

# ECMWF Open Data.
# Puoi cambiare source in "aws", "azure" o "google" se ECMWF è lento.
CLIENT_SOURCE = "azure"
CLIENT_MODEL = "ifs"
CLIENT_RESOL = "0p25"

# Per evitare il problema della precipitazione H+000, partiamo da H+003.
STEPS = list(range(3, 73, 3))

# Per test rapido:
# STEPS = [3, 6, 9, 12]

CLEAN_OLD_FILES = True
REQUEST_PAUSE_SECONDS = 0.35

# Se le onde non ci sono, non blocca il meteo.
DOWNLOAD_WAVES = True

# Se vuoi forzare un run specifico, imposta ad esempio:
# FORCE_RUN_DATE = "20260517"
# FORCE_RUN_TIME = 6
FORCE_RUN_DATE = None
FORCE_RUN_TIME = None


# ============================================================
# PARAMETRI METEO IFS
# ============================================================

METEO_PARAMS = {
    "u10": {
        "output_prefix": "u10",
        "param": "10u",
        "required": True,
        "description": "10m U wind component",
    },
    "v10": {
        "output_prefix": "v10",
        "param": "10v",
        "required": True,
        "description": "10m V wind component",
    },
    "gust": {
        "output_prefix": "gust",
        "param": "10fg",
        "required": False,
        "description": "10m wind gust",
    },
    "temperature": {
        "output_prefix": "temperature",
        "param": "2t",
        "required": True,
        "description": "2m temperature",
    },
    "precipitation": {
        "output_prefix": "precipitation",
        "param": "tp",
        "required": True,
        "description": "Total precipitation",
    },
    "cloud_cover": {
        "output_prefix": "cloud_cover",
        "param": "tcc",
        "required": True,
        "description": "Total cloud cover",
    },
    "pressure": {
        "output_prefix": "pressure",
        "param": "msl",
        "required": True,
        "description": "Mean sea level pressure",
    },
}


# ============================================================
# PARAMETRI ONDE
# ============================================================

# swh = Significant height of combined wind waves and swell.
# Proviamo più combinazioni perché ECMWF ha struttura diversa per stream onda.
WAVE_PARAM = {
    "output_prefix": "wave_height",
    "param": "swh",
    "required": False,
    "description": "Significant wave height",
}

WAVE_ATTEMPTS = [
    {
        "name": "wave-stream",
        "kwargs": {
            "type": "fc",
            "stream": "wave",
        },
    },
    {
        "name": "oper-stream",
        "kwargs": {
            "type": "fc",
            "stream": "oper",
        },
    },
    {
        "name": "scwv-stream",
        "kwargs": {
            "type": "fc",
            "stream": "scwv",
        },
    },
]


# ============================================================
# LOG
# ============================================================

def log(msg):
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}")


# ============================================================
# UTILS
# ============================================================

def clean_old_files():
    if not CLEAN_OLD_FILES:
        return

    for pattern in ["*.grib", "*.idx", "*.json", "*.log", "__tmp_*"]:
        for f in INPUT_DIR.glob(pattern):
            try:
                f.unlink()
            except Exception:
                pass


def file_is_valid(path: Path) -> bool:
    """
    Un GRIB valido di solito pesa più di pochi KB.
    Per H+003 in poi evitiamo i file vuoti.
    """
    return path.exists() and path.stat().st_size > 1024


def create_client():
    return Client(
        source=CLIENT_SOURCE,
        model=CLIENT_MODEL,
        resol=CLIENT_RESOL,
    )


def get_latest_run(client: Client):
    if FORCE_RUN_DATE and FORCE_RUN_TIME is not None:
        return FORCE_RUN_DATE, int(FORCE_RUN_TIME)

    latest_dt = client.latest(
        type="fc",
        step=3,
        param="2t",
    )

    if latest_dt is None:
        raise RuntimeError("Impossibile individuare l'ultimo run ECMWF Open Data.")

    run_date = latest_dt.strftime("%Y%m%d")
    run_time = int(latest_dt.strftime("%H"))

    return run_date, run_time


def format_run_date_for_meta(run_date_yyyymmdd):
    return f"{run_date_yyyymmdd[0:4]}-{run_date_yyyymmdd[4:6]}-{run_date_yyyymmdd[6:8]}"


def write_run_meta(run_date, run_time):
    meta = {
        "run_date": format_run_date_for_meta(run_date),
        "run_hour_utc": int(run_time),
        "created_at": datetime.now().isoformat(),
        "source": "ECMWF Open Data",
        "model": CLIENT_MODEL,
        "resolution": CLIENT_RESOL,
        "steps": STEPS,
        "created_by": "ecmwf_download.py",
        "note": "Meteo IFS e onde Wave scaricati separatamente. Render crop su Ardea eseguito da render.py.",
    }

    path = INPUT_DIR / "run_meta.json"
    path.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")

    log(f"Creato run_meta.json: {path}")

    return meta


def safe_unlink(path):
    try:
        if path.exists():
            path.unlink()
    except Exception:
        pass


# ============================================================
# DOWNLOAD METEO
# ============================================================

def retrieve_meteo_one(client, param_key, param_info, run_date, run_time, step):
    output_prefix = param_info["output_prefix"]
    target = INPUT_DIR / f"{output_prefix}_h{int(step):03d}.grib"
    tmp = INPUT_DIR / f"__tmp_{output_prefix}_h{int(step):03d}.grib"

    safe_unlink(target)
    safe_unlink(tmp)

    try:
        log(
            f"Scarico METEO {param_key} H+{step:03d} "
            f"param={param_info['param']} "
            f"({param_info['description']})"
        )

        client.retrieve(
            date=run_date,
            time=run_time,
            type="fc",
            step=int(step),
            param=param_info["param"],
            target=str(tmp),
        )

        if file_is_valid(tmp):
            tmp.rename(target)
            log(f"OK METEO: {target.name} ({target.stat().st_size / 1024:.1f} KB)")
            return True

        raise RuntimeError(f"File non valido o troppo piccolo: {tmp}")

    except Exception as e:
        safe_unlink(tmp)

        if param_info["required"]:
            raise RuntimeError(f"Parametro meteo obbligatorio fallito: {param_key} H+{step:03d}: {e}")

        log(f"Parametro meteo opzionale non disponibile: {param_key} H+{step:03d}: {e}")
        return False


def download_meteo(client, run_date, run_time, summary):
    log("==========================================")
    log("DOWNLOAD METEO IFS")
    log("==========================================")

    for step in STEPS:
        log("------------------------------------------")
        log(f"METEO STEP H+{step:03d}")
        log("------------------------------------------")

        for param_key, param_info in METEO_PARAMS.items():
            try:
                ok = retrieve_meteo_one(
                    client=client,
                    param_key=param_key,
                    param_info=param_info,
                    run_date=run_date,
                    run_time=run_time,
                    step=step,
                )

                if ok:
                    summary["downloaded"].setdefault(param_key, []).append(step)
                else:
                    summary["missing_optional"].setdefault(param_key, []).append(step)

            except Exception as e:
                err = str(e)
                summary["ok"] = False
                summary["errors"].append(err)

                log(f"ERRORE METEO: {err}")
                log(traceback.format_exc())

                if param_info["required"]:
                    raise

            time.sleep(REQUEST_PAUSE_SECONDS)


# ============================================================
# DOWNLOAD ONDE
# ============================================================

def retrieve_wave_one(client, run_date, run_time, step):
    output_prefix = WAVE_PARAM["output_prefix"]
    target = INPUT_DIR / f"{output_prefix}_h{int(step):03d}.grib"

    safe_unlink(target)

    last_error = None

    for attempt in WAVE_ATTEMPTS:
        tmp = INPUT_DIR / f"__tmp_{output_prefix}_h{int(step):03d}_{attempt['name']}.grib"
        safe_unlink(tmp)

        try:
            log(
                f"Scarico ONDE H+{step:03d} "
                f"param={WAVE_PARAM['param']} "
                f"tentativo={attempt['name']}"
            )

            kwargs = dict(attempt["kwargs"])

            client.retrieve(
                date=run_date,
                time=run_time,
                step=int(step),
                param=WAVE_PARAM["param"],
                target=str(tmp),
                **kwargs,
            )

            if file_is_valid(tmp):
                tmp.rename(target)
                log(f"OK ONDE: {target.name} ({target.stat().st_size / 1024:.1f} KB)")
                return True

            last_error = RuntimeError(f"File onda non valido o troppo piccolo: {tmp}")
            log(f"Tentativo onde non valido: {attempt['name']} H+{step:03d}")

        except Exception as e:
            last_error = e
            log(f"Tentativo onde fallito: {attempt['name']} H+{step:03d}: {e}")

        finally:
            safe_unlink(tmp)

        time.sleep(REQUEST_PAUSE_SECONDS)

    log(f"ONDE non disponibili H+{step:03d}. Ultimo errore: {last_error}")
    return False


def download_waves(client, run_date, run_time, summary):
    if not DOWNLOAD_WAVES:
        log("DOWNLOAD ONDE disattivato.")
        return

    log("==========================================")
    log("DOWNLOAD ONDE ECMWF WAVE")
    log("==========================================")

    for step in STEPS:
        try:
            ok = retrieve_wave_one(
                client=client,
                run_date=run_date,
                run_time=run_time,
                step=step,
            )

            if ok:
                summary["downloaded"].setdefault("wave_height", []).append(step)
            else:
                summary["missing_optional"].setdefault("wave_height", []).append(step)

        except Exception as e:
            err = f"wave_height H+{step:03d}: {e}"
            summary["errors"].append(err)
            log(f"ERRORE ONDE: {err}")
            log(traceback.format_exc())

        time.sleep(REQUEST_PAUSE_SECONDS)


# ============================================================
# MAIN
# ============================================================

def main():
    log("==========================================")
    log("ARDEA METEO PLAYER 1.0 - ECMWF OPEN DATA")
    log("==========================================")
    log(f"Cartella progetto: {BASE_DIR}")
    log(f"Cartella input: {INPUT_DIR}")
    log(f"Source: {CLIENT_SOURCE}")
    log(f"Model: {CLIENT_MODEL}")
    log(f"Resol: {CLIENT_RESOL}")
    log(f"Steps: {STEPS}")
    log("==========================================")

    clean_old_files()

    client = create_client()

    run_date, run_time = get_latest_run(client)

    log(f"Run selezionato ECMWF Open Data: {run_date} {run_time:02d} UTC")

    meta = write_run_meta(run_date, run_time)

    summary = {
        "ok": True,
        "run_date": meta["run_date"],
        "run_hour_utc": meta["run_hour_utc"],
        "source": "ECMWF Open Data",
        "client_source": CLIENT_SOURCE,
        "model": CLIENT_MODEL,
        "resolution": CLIENT_RESOL,
        "steps": STEPS,
        "downloaded": {},
        "missing_optional": {},
        "errors": [],
    }

    download_meteo(client, run_date, run_time, summary)
    download_waves(client, run_date, run_time, summary)

    summary_path = INPUT_DIR / "download_summary.json"
    summary_path.write_text(
        json.dumps(summary, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )

    log("==========================================")
    log("DOWNLOAD COMPLETATO")
    log(f"Summary: {summary_path}")
    log("Ora lancia: python render.py")
    log("==========================================")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log("ERRORE FATALE")
        log(str(e))
        log(traceback.format_exc())
        raise