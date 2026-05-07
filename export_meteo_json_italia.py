import json
import re
import gzip
import traceback
from pathlib import Path
from datetime import datetime, timezone, timedelta

import numpy as np
import xarray as xr

# Interpolazione opzionale per creare una griglia più fitta.
# Se scipy non c'è, uso un fallback numpy.
try:
    from scipy.interpolate import RegularGridInterpolator
    HAS_SCIPY_INTERP = True
except Exception:
    HAS_SCIPY_INTERP = False


# ============================================================
# ARDEA METEO PLAYER INTERATTIVO
# export_meteo_json.py
#
# Legge i GRIB già scaricati in:
#   input/ecmwf/
#
# Crea JSON per player interattivo:
#   output/interactive/manifest.json
#   output/interactive/meteo_data.json
#   output/interactive/meteo_data.json.gz
#   output/interactive/export_summary.json
#   output/interactive/ESITI_EXPORT_JSON.txt
#
# Compatibile con:
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
OUTPUT_DIR = BASE_DIR / "output" / "interactive"

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


# ============================================================
# AREA LAZIO CENTRALE / ARDEA
# ============================================================

BBOX = {
    "west": 6.0,
    "south": 35.3,
    "east": 19.2,
    "north": 47.6,
}

ARDEA = {
    "name": "Ardea",
    "lat": 41.612,
    "lon": 12.541,
}

ARDEA_SEA = {
    "name": "Mare davanti Ardea",
    "lat": 41.585,
    "lon": 12.425,
}


# ============================================================
# CONFIG
# ============================================================

# Arrotondamento valori per ridurre il peso del JSON
ROUND_DECIMALS = {
    "u10": 2,
    "v10": 2,
    "wind_kmh": 1,
    "wind_dir_deg": 0,
    "gust_kmh": 1,
    "temperature_c": 1,
    "precipitation_mm": 2,
    "cloud_cover_pct": 0,
    "pressure_hpa": 1,
    "wave_height_cm": 0,
}

# Fattore di interpolazione spaziale.
# 1 = griglia originale ECMWF
# 3/4 = molto meno effetto "quadrati" nel player
# 5/6 = più smooth ma JSON più pesante
UPSAMPLE_FACTOR = 2

# Se True, crea anche meteo_data.json.gz
CREATE_GZIP = True

# Se True, prova a continuare anche se mancano raffiche o onde
ALLOW_OPTIONAL_MISSING = True


# ============================================================
# FILE ALIAS
# ============================================================

FILE_ALIASES = {
    "u10": [
        "u10_h{step:03d}.grib",
        "10u_h{step:03d}.grib",
    ],
    "v10": [
        "v10_h{step:03d}.grib",
        "10v_h{step:03d}.grib",
    ],
    "gust": [
        "gust_h{step:03d}.grib",
        "10fg_h{step:03d}.grib",
        "gusts_h{step:03d}.grib",
    ],
    "temperature": [
        "temperature_h{step:03d}.grib",
        "t2m_h{step:03d}.grib",
        "2t_h{step:03d}.grib",
    ],
    "precipitation": [
        "precipitation_h{step:03d}.grib",
        "tp_h{step:03d}.grib",
    ],
    "cloud_cover": [
        "cloud_cover_h{step:03d}.grib",
        "tcc_h{step:03d}.grib",
    ],
    "pressure": [
        "pressure_h{step:03d}.grib",
        "msl_h{step:03d}.grib",
        "mslp_h{step:03d}.grib",
    ],
    "wave_height": [
        "wave_height_h{step:03d}.grib",
        "swh_h{step:03d}.grib",
    ],
}


# ============================================================
# SUMMARY
# ============================================================

SUMMARY = {
    "ok": True,
    "created_at": datetime.now().isoformat(),
    "input_dir": str(INPUT_DIR),
    "output_dir": str(OUTPUT_DIR),
    "layers_ok": [],
    "layers_optional_missing": [],
    "errors": [],
    "steps": [],
    "files_created": [],
    "upsample_factor": UPSAMPLE_FACTOR,
    "has_scipy_interp": HAS_SCIPY_INTERP,
}


# ============================================================
# LOG
# ============================================================

def log(msg):
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}", flush=True)


def add_error(layer, error):
    SUMMARY["ok"] = False
    SUMMARY["errors"].append({
        "layer": layer,
        "error": str(error),
        "traceback": traceback.format_exc(),
    })


def add_optional_missing(layer, detail):
    SUMMARY["layers_optional_missing"].append({
        "layer": layer,
        "detail": detail,
    })


# ============================================================
# UTILITY
# ============================================================

def detect_steps():
    pattern = re.compile(r"_h(\d{3})\.grib$", re.IGNORECASE)
    found = set()

    for f in INPUT_DIR.glob("*.grib"):
        m = pattern.search(f.name)
        if m:
            found.add(int(m.group(1)))

    return sorted(found)


def find_file(varname, step):
    for pattern in FILE_ALIASES.get(varname, []):
        p = INPUT_DIR / pattern.format(step=int(step))
        if p.exists():
            return p
    return None


def load_run_meta():
    meta_path = INPUT_DIR / "run_meta.json"

    if meta_path.exists():
        try:
            return json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            pass

    now = datetime.now(timezone.utc)

    return {
        "run_date": now.strftime("%Y-%m-%d"),
        "run_hour_utc": 0,
        "created_at": now.isoformat(),
    }


def valid_time_from_step(run_meta, step):
    run_date = run_meta.get("run_date", datetime.now().strftime("%Y-%m-%d"))
    run_hour = int(run_meta.get("run_hour_utc", 0))

    run_dt = datetime.strptime(
        f"{run_date} {run_hour:02d}",
        "%Y-%m-%d %H"
    ).replace(tzinfo=timezone.utc)

    valid_utc = run_dt + timedelta(hours=int(step))

    try:
        from zoneinfo import ZoneInfo
        valid_it = valid_utc.astimezone(ZoneInfo("Europe/Rome"))
    except Exception:
        valid_it = valid_utc + timedelta(hours=2)

    return valid_utc, valid_it


def open_grib(path):
    ds = xr.open_dataset(
        path,
        engine="cfgrib",
        backend_kwargs={"indexpath": ""},
    )

    data_vars = list(ds.data_vars)

    if not data_vars:
        raise RuntimeError(f"Nessuna variabile trovata in {path.name}")

    var = data_vars[0]
    da = ds[var].squeeze()

    if "latitude" not in da.coords or "longitude" not in da.coords:
        raise RuntimeError(f"Coordinate latitude/longitude non trovate in {path.name}")

    lats = da["latitude"].values
    lons = da["longitude"].values
    data = da.values.astype(float)

    if data.ndim != 2:
        raise RuntimeError(f"Dato non 2D in {path.name}. Shape: {data.shape}")

    if lats.ndim != 1 or lons.ndim != 1:
        raise RuntimeError(f"Coordinate non 1D in {path.name}")

    # Longitudini 0/360 -> -180/180
    if np.nanmax(lons) > 180:
        lons = ((lons + 180) % 360) - 180
        order = np.argsort(lons)
        lons = lons[order]
        data = data[:, order]

    # Latitudini crescenti
    if lats[0] > lats[-1]:
        lats = lats[::-1]
        data = data[::-1, :]

    return lats, lons, data


def crop_bbox(lats, lons, data):
    lat_mask = (lats >= BBOX["south"]) & (lats <= BBOX["north"])
    lon_mask = (lons >= BBOX["west"]) & (lons <= BBOX["east"])

    if not lat_mask.any():
        raise RuntimeError("BBOX fuori dalle latitudini disponibili")

    if not lon_mask.any():
        raise RuntimeError("BBOX fuori dalle longitudini disponibili")

    return (
        lats[lat_mask],
        lons[lon_mask],
        data[np.ix_(lat_mask, lon_mask)],
    )


def build_upsampled_coords(lats, lons, factor):
    """
    Crea coordinate più fitte mantenendo gli estremi originali.
    Esempio: factor=4 trasforma circa 0.1° in circa 0.025°.
    """
    if factor <= 1:
        return lats, lons

    new_lat_count = max(len(lats), (len(lats) - 1) * factor + 1)
    new_lon_count = max(len(lons), (len(lons) - 1) * factor + 1)

    new_lats = np.linspace(float(lats[0]), float(lats[-1]), new_lat_count)
    new_lons = np.linspace(float(lons[0]), float(lons[-1]), new_lon_count)

    return new_lats, new_lons


def interpolate_grid(lats, lons, data, factor=UPSAMPLE_FACTOR):
    """
    Interpolazione bilineare della griglia.
    Serve per ridurre l'effetto reticolo/quadratoni nel player.
    """
    if factor <= 1:
        return lats, lons, data

    new_lats, new_lons = build_upsampled_coords(lats, lons, factor)

    # Dove il campo contiene NaN, li tengo come NaN.
    # round_nested poi li convertirà in null JSON-safe.
    if HAS_SCIPY_INTERP:
        interpolator = RegularGridInterpolator(
            (lats, lons),
            data,
            method="linear",
            bounds_error=False,
            fill_value=np.nan,
        )

        lon2d, lat2d = np.meshgrid(new_lons, new_lats)
        pts = np.column_stack([lat2d.ravel(), lon2d.ravel()])
        out = interpolator(pts).reshape(len(new_lats), len(new_lons))

        return new_lats, new_lons, out

    # Fallback numpy: prima interpolo ogni riga sulle longitudini,
    # poi interpolo ogni colonna sulle latitudini.
    temp = np.empty((data.shape[0], len(new_lons)), dtype=float)

    for i in range(data.shape[0]):
        row = data[i, :]
        valid = np.isfinite(row)

        if valid.sum() < 2:
            temp[i, :] = np.nan
        else:
            temp[i, :] = np.interp(new_lons, lons[valid], row[valid], left=np.nan, right=np.nan)

    out = np.empty((len(new_lats), len(new_lons)), dtype=float)

    for j in range(temp.shape[1]):
        col = temp[:, j]
        valid = np.isfinite(col)

        if valid.sum() < 2:
            out[:, j] = np.nan
        else:
            out[:, j] = np.interp(new_lats, lats[valid], col[valid], left=np.nan, right=np.nan)

    return new_lats, new_lons, out


def read_field(varname, step, required=True):
    fp = find_file(varname, step)

    if fp is None:
        if required:
            raise FileNotFoundError(f"Manca file {varname} H+{step:03d}")
        return None

    lats, lons, data = open_grib(fp)
    lats, lons, data = crop_bbox(lats, lons, data)
    lats, lons, data = interpolate_grid(lats, lons, data, UPSAMPLE_FACTOR)

    return {
        "step": int(step),
        "file": fp.name,
        "lats": lats,
        "lons": lons,
        "data": data,
    }


def round_nested(arr, decimals):
    """
    Converte array numpy in liste JSON-safe.
    Elimina NaN / Infinity perché JSON.parse in JavaScript non li accetta.
    """
    if arr is None:
        return None

    arr = np.asarray(arr, dtype=float)

    if decimals is not None:
        arr = np.round(arr, decimals)

    # Converte NaN, +inf, -inf in None
    out = arr.astype(object)
    mask = ~np.isfinite(arr)
    out[mask] = None

    return out.tolist()


def json_safe(obj):
    """
    Sanifica ricorsivamente qualsiasi struttura prima del json.dumps.
    Converte NaN, +inf, -inf in None.
    Converte numpy scalar in tipi Python standard.
    """
    if obj is None:
        return None

    if isinstance(obj, dict):
        return {str(k): json_safe(v) for k, v in obj.items()}

    if isinstance(obj, (list, tuple)):
        return [json_safe(v) for v in obj]

    if isinstance(obj, np.ndarray):
        return json_safe(obj.tolist())

    if isinstance(obj, (np.integer,)):
        return int(obj)

    if isinstance(obj, (np.floating, float)):
        value = float(obj)
        if not np.isfinite(value):
            return None
        return value

    if isinstance(obj, (np.bool_, bool)):
        return bool(obj)

    return obj


def sample_nearest(lats, lons, data, lat, lon):
    ilat = int(np.argmin(np.abs(lats - lat)))
    ilon = int(np.argmin(np.abs(lons - lon)))

    value = float(data[ilat, ilon])

    if np.isfinite(value):
        return value

    # Se il punto cade su un NaN generato dall'interpolazione ai bordi,
    # cerca il valore valido più vicino in una piccola finestra.
    arr = np.asarray(data, dtype=float)
    r0 = max(0, ilat - 2)
    r1 = min(arr.shape[0], ilat + 3)
    c0 = max(0, ilon - 2)
    c1 = min(arr.shape[1], ilon + 3)
    window = arr[r0:r1, c0:c1]
    valid = window[np.isfinite(window)]

    if valid.size:
        return float(valid[0])

    return float("nan")


def wind_direction_from_uv(u, v):
    """
    Direzione meteorologica: da dove viene il vento.
    u/v ECMWF indicano verso dove va il vento.
    Formula meteo:
      dir = atan2(-u, -v)
    """
    deg = (np.degrees(np.arctan2(-u, -v)) + 360) % 360
    return deg


def cardinal_from_deg(deg):
    dirs = [
        "N", "NNE", "NE", "ENE",
        "E", "ESE", "SE", "SSE",
        "S", "SSW", "SW", "WSW",
        "W", "WNW", "NW", "NNW"
    ]

    idx = int((deg + 11.25) // 22.5) % 16
    return dirs[idx]


def compute_tendency(current, next_value, unit, decimals=1):
    if next_value is None:
        return {
            "delta": None,
            "label": "n/d",
        }

    delta = round(float(next_value - current), decimals)

    if abs(delta) < 0.1:
        label = f"stabile"
    elif delta > 0:
        label = f"in aumento di {delta} {unit}"
    else:
        label = f"in diminuzione di {abs(delta)} {unit}"

    return {
        "delta": delta,
        "label": label,
    }


def flatten_grid_for_js(data):
    """
    Manteniamo array 2D per semplicità lato JS:
    data[lat_index][lon_index]
    """
    return data


# ============================================================
# STEP DATA
# ============================================================

def process_step(step):
    log(f"Elaboro step H+{step:03d} - upsample {UPSAMPLE_FACTOR}x")

    # obbligatori
    u10 = read_field("u10", step, required=True)
    v10 = read_field("v10", step, required=True)
    temperature = read_field("temperature", step, required=True)
    precipitation = read_field("precipitation", step, required=True)
    cloud_cover = read_field("cloud_cover", step, required=True)
    pressure = read_field("pressure", step, required=True)

    # opzionali
    gust = read_field("gust", step, required=False)
    wave_height = read_field("wave_height", step, required=False)

    lats = u10["lats"]
    lons = u10["lons"]

    u = u10["data"]
    v = v10["data"]

    wind_ms = np.sqrt(u ** 2 + v ** 2)
    wind_kmh = wind_ms * 3.6
    wind_dir_deg = wind_direction_from_uv(u, v)

    # raffiche
    if gust is not None:
        gust_kmh = gust["data"] * 3.6
        gust_estimated = False
    else:
        gust_kmh = np.maximum(wind_kmh * 1.35, wind_kmh + 8.0)
        gust_estimated = True

    # temperatura Kelvin -> °C
    temperature_c = temperature["data"] - 273.15

    # precipitazione m -> mm
    # Nota: qui per semplicità salviamo il valore accumulato/step così come da file.
    # Se vuoi mm/3h rigoroso, si calcola sottraendo lo step precedente.
    precipitation_mm_raw = np.maximum(precipitation["data"] * 1000.0, 0)

    # cloud 0-1 oppure 0-100
    cloud = cloud_cover["data"]
    if np.nanmax(cloud) <= 1.5:
        cloud_pct = cloud * 100.0
    else:
        cloud_pct = cloud
    cloud_pct = np.clip(cloud_pct, 0, 100)

    # pressione Pa -> hPa
    pressure_hpa = pressure["data"] / 100.0

    # onde m -> cm
    if wave_height is not None:
        wave_cm = np.maximum(wave_height["data"] * 100.0, 0)
    else:
        wave_cm = None

    step_data = {
        "step": int(step),
        "files": {
            "u10": u10["file"],
            "v10": v10["file"],
            "gust": gust["file"] if gust else None,
            "temperature": temperature["file"],
            "precipitation": precipitation["file"],
            "cloud_cover": cloud_cover["file"],
            "pressure": pressure["file"],
            "wave_height": wave_height["file"] if wave_height else None,
        },
        "gust_estimated": gust_estimated,
        "grid": {
            "u10": round_nested(u, ROUND_DECIMALS["u10"]),
            "v10": round_nested(v, ROUND_DECIMALS["v10"]),
            "wind_kmh": round_nested(wind_kmh, ROUND_DECIMALS["wind_kmh"]),
            "wind_dir_deg": round_nested(wind_dir_deg, ROUND_DECIMALS["wind_dir_deg"]),
            "gust_kmh": round_nested(gust_kmh, ROUND_DECIMALS["gust_kmh"]),
            "temperature_c": round_nested(temperature_c, ROUND_DECIMALS["temperature_c"]),
            "precipitation_mm": round_nested(precipitation_mm_raw, ROUND_DECIMALS["precipitation_mm"]),
            "cloud_cover_pct": round_nested(cloud_pct, ROUND_DECIMALS["cloud_cover_pct"]),
            "pressure_hpa": round_nested(pressure_hpa, ROUND_DECIMALS["pressure_hpa"]),
            "wave_height_cm": round_nested(wave_cm, ROUND_DECIMALS["wave_height_cm"]) if wave_cm is not None else None,
        },
        "_arrays": {
            "lats": lats,
            "lons": lons,
            "u10": u,
            "v10": v,
            "wind_kmh": wind_kmh,
            "wind_dir_deg": wind_dir_deg,
            "gust_kmh": gust_kmh,
            "temperature_c": temperature_c,
            "precipitation_mm": precipitation_mm_raw,
            "cloud_cover_pct": cloud_pct,
            "pressure_hpa": pressure_hpa,
            "wave_height_cm": wave_cm,
        }
    }

    if gust is None:
        add_optional_missing("gust", f"H+{step:03d}: file raffiche mancante, stima calcolata dal vento medio")

    if wave_height is None:
        add_optional_missing("wave_height", f"H+{step:03d}: file onde mancante")

    return lats, lons, step_data


def compute_precipitation_increment(steps_data):
    """
    Converte precipitation_mm da accumulata a incremento fra step.
    Serve per avere pioggia tipo mm/3h nel player.
    """
    previous = None

    for item in steps_data:
        current = np.array(item["grid"]["precipitation_mm"], dtype=float)

        if previous is None:
            inc = np.maximum(current, 0)
        else:
            inc = np.maximum(current - previous, 0)

        item["grid"]["precipitation_mm"] = round_nested(
            inc,
            ROUND_DECIMALS["precipitation_mm"]
        )

        item["_arrays"]["precipitation_mm"] = inc

        previous = current


def compute_point_values(steps_data, lats, lons, run_meta):
    """
    Crea valori puntuali Ardea e Mare Ardea per popup iniziali e debug.
    Il player potrà comunque interrogare qualunque punto della mappa.
    """
    point_series = {
        "ardea": [],
        "ardea_sea": [],
    }

    for idx, item in enumerate(steps_data):
        step = item["step"]
        valid_utc, valid_it = valid_time_from_step(run_meta, step)

        arr = item["_arrays"]

        # Ardea terra
        ardea_wind = sample_nearest(lats, lons, arr["wind_kmh"], ARDEA["lat"], ARDEA["lon"])
        ardea_dir = sample_nearest(lats, lons, arr["wind_dir_deg"], ARDEA["lat"], ARDEA["lon"])
        ardea_gust = sample_nearest(lats, lons, arr["gust_kmh"], ARDEA["lat"], ARDEA["lon"])
        ardea_temp = sample_nearest(lats, lons, arr["temperature_c"], ARDEA["lat"], ARDEA["lon"])
        ardea_rain = sample_nearest(lats, lons, arr["precipitation_mm"], ARDEA["lat"], ARDEA["lon"])
        ardea_cloud = sample_nearest(lats, lons, arr["cloud_cover_pct"], ARDEA["lat"], ARDEA["lon"])
        ardea_pressure = sample_nearest(lats, lons, arr["pressure_hpa"], ARDEA["lat"], ARDEA["lon"])

        # Mare Ardea
        sea_wind = sample_nearest(lats, lons, arr["wind_kmh"], ARDEA_SEA["lat"], ARDEA_SEA["lon"])
        sea_dir = sample_nearest(lats, lons, arr["wind_dir_deg"], ARDEA_SEA["lat"], ARDEA_SEA["lon"])
        sea_gust = sample_nearest(lats, lons, arr["gust_kmh"], ARDEA_SEA["lat"], ARDEA_SEA["lon"])
        sea_wave = None

        if arr["wave_height_cm"] is not None:
            sea_wave = sample_nearest(lats, lons, arr["wave_height_cm"], ARDEA_SEA["lat"], ARDEA_SEA["lon"])

        point_series["ardea"].append({
            "step": step,
            "valid_time_utc": valid_utc.isoformat(),
            "valid_time_it": valid_it.isoformat(),
            "valid_label": valid_it.strftime("%H:%M %d/%m/%Y"),
            "wind_kmh": round(ardea_wind, 1),
            "wind_dir_deg": round(ardea_dir, 0),
            "wind_dir_cardinal": cardinal_from_deg(ardea_dir),
            "gust_kmh": round(ardea_gust, 1),
            "temperature_c": round(ardea_temp, 1),
            "precipitation_mm": round(ardea_rain, 2),
            "cloud_cover_pct": round(ardea_cloud, 0),
            "pressure_hpa": round(ardea_pressure, 1),
        })

        point_series["ardea_sea"].append({
            "step": step,
            "valid_time_utc": valid_utc.isoformat(),
            "valid_time_it": valid_it.isoformat(),
            "valid_label": valid_it.strftime("%H:%M %d/%m/%Y"),
            "wind_kmh": round(sea_wind, 1),
            "wind_dir_deg": round(sea_dir, 0),
            "wind_dir_cardinal": cardinal_from_deg(sea_dir),
            "gust_kmh": round(sea_gust, 1),
            "wave_height_cm": round(sea_wave, 0) if sea_wave is not None else None,
        })

    # tendenze punto
    for point_name, series in point_series.items():
        for i, row in enumerate(series):
            next_row = series[i + 1] if i + 1 < len(series) else None

            if point_name == "ardea":
                row["tendency"] = {
                    "wind": compute_tendency(
                        row["wind_kmh"],
                        next_row["wind_kmh"] if next_row else None,
                        "km/h",
                        1
                    ),
                    "temperature": compute_tendency(
                        row["temperature_c"],
                        next_row["temperature_c"] if next_row else None,
                        "°C",
                        1
                    ),
                    "pressure": compute_tendency(
                        row["pressure_hpa"],
                        next_row["pressure_hpa"] if next_row else None,
                        "hPa",
                        1
                    ),
                    "precipitation": compute_tendency(
                        row["precipitation_mm"],
                        next_row["precipitation_mm"] if next_row else None,
                        "mm",
                        2
                    ),
                }
            else:
                row["tendency"] = {
                    "wind": compute_tendency(
                        row["wind_kmh"],
                        next_row["wind_kmh"] if next_row else None,
                        "km/h",
                        1
                    ),
                    "wave": compute_tendency(
                        row["wave_height_cm"] or 0,
                        next_row["wave_height_cm"] if next_row and next_row["wave_height_cm"] is not None else None,
                        "cm",
                        0
                    ),
                }

    return point_series


def strip_internal_arrays(steps_data):
    for item in steps_data:
        if "_arrays" in item:
            del item["_arrays"]


# ============================================================
# OUTPUT
# ============================================================

def write_json(path, data):
    safe_data = json_safe(data)

    path.write_text(
        json.dumps(
            safe_data,
            indent=2,
            ensure_ascii=False,
            allow_nan=False
        ),
        encoding="utf-8"
    )
    SUMMARY["files_created"].append(str(path))


def write_gzip_json(path, data):
    safe_data = json_safe(data)

    raw = json.dumps(
        safe_data,
        ensure_ascii=False,
        allow_nan=False
    ).encode("utf-8")

    with gzip.open(path, "wb") as f:
        f.write(raw)

    SUMMARY["files_created"].append(str(path))


def write_summary_and_esiti(manifest, meteo_data):
    manifest_path = OUTPUT_DIR / "manifest.json"
    data_path = OUTPUT_DIR / "meteo_data.json"
    data_gz_path = OUTPUT_DIR / "meteo_data.json.gz"
    summary_path = OUTPUT_DIR / "export_summary.json"
    esiti_path = OUTPUT_DIR / "ESITI_EXPORT_JSON.txt"

    write_json(manifest_path, manifest)
    write_json(data_path, meteo_data)

    if CREATE_GZIP:
        write_gzip_json(data_gz_path, meteo_data)

    write_json(summary_path, SUMMARY)

    lines = []
    lines.append("==========================================")
    lines.append("ARDEA METEO PLAYER - EXPORT JSON")
    lines.append("==========================================")
    lines.append(f"Creato: {SUMMARY['created_at']}")
    lines.append(f"Input: {INPUT_DIR}")
    lines.append(f"Output: {OUTPUT_DIR}")
    lines.append("")
    lines.append("STEP")
    lines.append("------------------------------------------")
    lines.append(", ".join([f"H+{s:03d}" for s in SUMMARY["steps"]]))
    lines.append("")
    lines.append("LAYER OK")
    lines.append("------------------------------------------")
    for layer in SUMMARY["layers_ok"]:
        lines.append(f"OK - {layer}")
    if not SUMMARY["layers_ok"]:
        lines.append("Nessun layer registrato.")
    lines.append("")
    lines.append("OPZIONALI MANCANTI")
    lines.append("------------------------------------------")
    if SUMMARY["layers_optional_missing"]:
        for item in SUMMARY["layers_optional_missing"]:
            lines.append(f"{item['layer']}: {item['detail']}")
    else:
        lines.append("Nessun opzionale mancante.")
    lines.append("")
    lines.append("ERRORI")
    lines.append("------------------------------------------")
    if SUMMARY["errors"]:
        for err in SUMMARY["errors"]:
            lines.append(f"{err['layer']}: {err['error']}")
    else:
        lines.append("Nessun errore.")
    lines.append("")
    lines.append("FILE CREATI")
    lines.append("------------------------------------------")
    for f in SUMMARY["files_created"]:
        lines.append(f)

    esiti_path.write_text("\n".join(lines), encoding="utf-8")
    SUMMARY["files_created"].append(str(esiti_path))

    log("==========================================")
    log("EXPORT COMPLETATO")
    log("==========================================")
    log(f"manifest: {manifest_path}")
    log(f"dati: {data_path}")
    if CREATE_GZIP:
        log(f"dati gzip: {data_gz_path}")
    log(f"summary: {summary_path}")
    log(f"esiti: {esiti_path}")

    if SUMMARY["errors"]:
        log("Completato con errori.")
    else:
        log("Completato senza errori.")


# ============================================================
# MAIN
# ============================================================

def main():
    log("==========================================")
    log("AVVIO EXPORT METEO JSON")
    log("==========================================")
    log(f"Input: {INPUT_DIR}")
    log(f"Output: {OUTPUT_DIR}")
    log(f"UPSAMPLE_FACTOR: {UPSAMPLE_FACTOR}")
    log(f"HAS_SCIPY_INTERP: {HAS_SCIPY_INTERP}")

    if not INPUT_DIR.exists():
        raise RuntimeError(f"Cartella input non trovata: {INPUT_DIR}")

    run_meta = load_run_meta()
    steps = detect_steps()

    if not steps:
        raise RuntimeError(f"Nessun GRIB trovato in {INPUT_DIR}")

    SUMMARY["steps"] = steps

    log(f"Run: {run_meta.get('run_date')} {int(run_meta.get('run_hour_utc', 0)):02d} UTC")
    log(f"Step trovati: {steps}")

    all_steps_data = []
    base_lats = None
    base_lons = None

    try:
        for step in steps:
            lats, lons, step_data = process_step(step)

            if base_lats is None:
                base_lats = lats
                base_lons = lons
            else:
                if len(base_lats) != len(lats) or len(base_lons) != len(lons):
                    raise RuntimeError(f"Griglia diversa allo step H+{step:03d}")

            all_steps_data.append(step_data)

    except Exception as e:
        add_error("process_step", e)
        raise

    # Trasforma precipitazione accumulata in mm/step
    try:
        compute_precipitation_increment(all_steps_data)
    except Exception as e:
        add_error("precipitation_increment", e)
        raise

    # Point values e tendenze
    try:
        point_series = compute_point_values(all_steps_data, base_lats, base_lons, run_meta)
    except Exception as e:
        add_error("point_values", e)
        raise

    # Rimuove array interni numpy prima di scrivere JSON
    strip_internal_arrays(all_steps_data)

    SUMMARY["layers_ok"] = [
        "u10",
        "v10",
        "wind_kmh",
        "wind_dir_deg",
        "gust_kmh",
        "temperature_c",
        "precipitation_mm",
        "cloud_cover_pct",
        "pressure_hpa",
        "wave_height_cm",
    ]

    valid_utc_first, valid_it_first = valid_time_from_step(run_meta, steps[0])
    valid_utc_last, valid_it_last = valid_time_from_step(run_meta, steps[-1])

    manifest = {
        "ok": len(SUMMARY["errors"]) == 0,
        "project": "Meteo Italia Interattivo",
        "version": "1.2-italia-wind-flow",
        "created_at": datetime.now().isoformat(),
        "source": "ECMWF Open Data / GRIB local export",
        "run": {
            "date": run_meta.get("run_date"),
            "hour_utc": int(run_meta.get("run_hour_utc", 0)),
        },
        "bbox": BBOX,
        "points": {
            "ardea": ARDEA,
            "ardea_sea": ARDEA_SEA,
        },
        "grid": {
            "lat_count": len(base_lats),
            "lon_count": len(base_lons),
            "lat_min": float(base_lats[0]),
            "lat_max": float(base_lats[-1]),
            "lon_min": float(base_lons[0]),
            "lon_max": float(base_lons[-1]),
            "upsample_factor": UPSAMPLE_FACTOR,
            "has_scipy_interp": HAS_SCIPY_INTERP,
        },
        "steps": steps,
        "valid_range": {
            "first_utc": valid_utc_first.isoformat(),
            "first_it": valid_it_first.isoformat(),
            "last_utc": valid_utc_last.isoformat(),
            "last_it": valid_it_last.isoformat(),
        },
        "data_files": {
            "json": "meteo_data.json",
            "gzip": "meteo_data.json.gz" if CREATE_GZIP else None,
        },
        "layers": {
            "wind": {
                "fields": ["u10", "v10", "wind_kmh", "wind_dir_deg", "gust_kmh"],
                "unit": "km/h",
                "interactive": True,
                "animated": True,
            },
            "gusts": {
                "fields": ["gust_kmh"],
                "unit": "km/h",
                "interactive": True,
                "animated": True,
            },
            "temperature": {
                "fields": ["temperature_c"],
                "unit": "°C",
                "interactive": True,
                "animated": True,
            },
            "precipitation": {
                "fields": ["precipitation_mm"],
                "unit": "mm/step",
                "interactive": True,
                "animated": True,
            },
            "cloud_cover": {
                "fields": ["cloud_cover_pct"],
                "unit": "%",
                "interactive": True,
                "animated": True,
            },
            "pressure": {
                "fields": ["pressure_hpa"],
                "unit": "hPa",
                "interactive": True,
                "animated": True,
            },
            "wave_height": {
                "fields": ["wave_height_cm"],
                "unit": "cm",
                "interactive": True,
                "animated": True,
            },
        }
    }

    meteo_data = {
        "project": "Meteo Italia Interattivo",
        "created_at": datetime.now().isoformat(),
        "run": manifest["run"],
        "bbox": BBOX,
        "points": manifest["points"],
        "grid": {
            "lats": round_nested(base_lats, 5),
            "lons": round_nested(base_lons, 5),
            "orientation": "data[lat_index][lon_index]",
        },
        "steps": all_steps_data,
        "point_series": point_series,
    }

    write_summary_and_esiti(manifest, meteo_data)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log("ERRORE FATALE")
        log(str(e))
        log(traceback.format_exc())
        raise