#!/usr/bin/env python3
# -*- coding: utf-8 -*-

r"""
render.py - METEO ITALIA SMOOTH / WINDY-LIKE

Legge i GRIB ECMWF già scaricati in:
    C:/Users/PC_Matteo/Desktop/meteo/input/ecmwf/

Crea:
    output/ecmwf/manifest.json
    output/ecmwf/render_summary.json
    output/ecmwf/ESITI_RENDER.txt
    output/ecmwf/animations/wind.webp
    output/ecmwf/animations/gusts.webp
    output/ecmwf/animations/precipitation.webp
    output/ecmwf/animations/cloud_cover.webp
    output/ecmwf/animations/temperature.webp
    output/ecmwf/animations/pressure.webp
    output/ecmwf/animations/wave_height.webp

Migliorie:
- Italia intera
- campi interpolati/upscalati e smussati
- vento/raffiche con flussi a strisce
- pioggia più leggibile
- temperatura smooth
- mare/onde più morbidi
- nuvole stile satellite sintetico partendo da cloud_cover ECMWF

NOTA:
La copertura nuvolosa NON è un vero satellite Meteosat:
è una resa grafica costruita dal campo ECMWF cloud_cover.
"""

import json
import math
import re
import traceback
from pathlib import Path
from datetime import datetime, timezone, timedelta

import numpy as np
import xarray as xr
from PIL import Image

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap
from matplotlib.collections import LineCollection
import matplotlib.patheffects as pe

try:
    from scipy.ndimage import gaussian_filter, zoom
    HAS_SCIPY = True
except Exception:
    HAS_SCIPY = False

import cartopy
import cartopy.crs as ccrs
import cartopy.feature as cfeature


BASE_DIR = Path(__file__).resolve().parent
INPUT_DIR = BASE_DIR / "input" / "ecmwf"
OUTPUT_DIR = BASE_DIR / "output" / "ecmwf"
FRAMES_DIR = OUTPUT_DIR / "frames"
ANIM_DIR = OUTPUT_DIR / "animations"

CARTOPY_DATA_DIR = BASE_DIR / "cartopy_data"
cartopy.config["data_dir"] = str(CARTOPY_DATA_DIR)

BBOX = {
    "west": 6.0,
    "south": 35.3,
    "east": 19.2,
    "north": 47.6,
}

ARDEA = {"name": "Ardea", "lat": 41.612, "lon": 12.541}
ARDEA_SEA = {"name": "Mare davanti Ardea", "lat": 41.585, "lon": 12.425}

UPSCALE_FACTOR = 4
SMOOTH_SIGMA = 1.15
COASTAL_FILL_RADIUS = 4
FIG_W = 13.2
FIG_H = 8.2
DPI = 150

FLOW_COUNT_WIND = 950
FLOW_COUNT_GUSTS = 850
FLOW_COUNT_RAIN = 520
FLOW_COUNT_WAVES = 480
FLOW_COUNT_CLOUDS = 360

FRAME_DURATION_MS = {
    "wind": 90,
    "gusts": 80,
    "precipitation": 120,
    "cloud_cover": 140,
    "temperature": 140,
    "pressure": 150,
    "wave_height": 130,
}

LAYERS = [
    "wind",
    "gusts",
    "precipitation",
    "cloud_cover",
    "temperature",
    "pressure",
    "wave_height",
]

FILE_ALIASES = {
    "u10": ["u10_h{step:03d}.grib", "10u_h{step:03d}.grib"],
    "v10": ["v10_h{step:03d}.grib", "10v_h{step:03d}.grib"],
    "gust": ["gust_h{step:03d}.grib", "10fg_h{step:03d}.grib", "gusts_h{step:03d}.grib"],
    "temperature": ["temperature_h{step:03d}.grib", "t2m_h{step:03d}.grib", "2t_h{step:03d}.grib"],
    "precipitation": ["precipitation_h{step:03d}.grib", "tp_h{step:03d}.grib"],
    "cloud_cover": ["cloud_cover_h{step:03d}.grib", "tcc_h{step:03d}.grib"],
    "pressure": ["pressure_h{step:03d}.grib", "msl_h{step:03d}.grib", "mslp_h{step:03d}.grib"],
    "wave_height": ["wave_height_h{step:03d}.grib", "swh_h{step:03d}.grib"],
}

SUMMARY = {
    "ok": True,
    "created_at": datetime.now().isoformat(),
    "input_dir": str(INPUT_DIR),
    "output_dir": str(OUTPUT_DIR),
    "bbox": BBOX,
    "upscale_factor": UPSCALE_FACTOR,
    "smooth_sigma": SMOOTH_SIGMA,
    "has_scipy": HAS_SCIPY,
    "frames": {},
    "files_created": [],
    "errors": [],
    "warnings": [],
}


def log(msg):
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}", flush=True)


def add_error(layer, step, error):
    SUMMARY["ok"] = False
    SUMMARY["errors"].append({
        "layer": layer,
        "step": step,
        "error": str(error),
        "traceback": traceback.format_exc(),
    })


def add_warning(msg):
    SUMMARY["warnings"].append(str(msg))
    log(f"ATTENZIONE: {msg}")


def ensure_dirs():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    FRAMES_DIR.mkdir(parents=True, exist_ok=True)
    ANIM_DIR.mkdir(parents=True, exist_ok=True)
    CARTOPY_DATA_DIR.mkdir(parents=True, exist_ok=True)
    for layer in LAYERS:
        (FRAMES_DIR / layer).mkdir(parents=True, exist_ok=True)


def clean_old_frames():
    for layer in LAYERS:
        d = FRAMES_DIR / layer
        if d.exists():
            for fp in d.glob("*.png"):
                try:
                    fp.unlink()
                except Exception:
                    pass


def load_run_meta():
    fp = INPUT_DIR / "run_meta.json"
    if fp.exists():
        try:
            return json.loads(fp.read_text(encoding="utf-8"))
        except Exception as e:
            add_warning(f"run_meta.json non leggibile, uso fallback: {e}")
    now = datetime.now(timezone.utc)
    return {"run_date": now.strftime("%Y-%m-%d"), "run_hour_utc": 0, "created_at": now.isoformat()}


def detect_steps():
    found = set()
    pattern = re.compile(r"_h(\d{3})\.grib$", re.IGNORECASE)
    for fp in INPUT_DIR.glob("*.grib"):
        m = pattern.search(fp.name)
        if m:
            found.add(int(m.group(1)))
    return sorted(found)


def get_steps(run_meta):
    steps = run_meta.get("steps")
    if isinstance(steps, list) and steps:
        return [int(x) for x in steps]
    steps = detect_steps()
    if not steps:
        raise RuntimeError(f"Nessun file GRIB trovato in {INPUT_DIR}")
    return steps


def parse_run_datetime(run_meta):
    nested = run_meta.get("run", {}) if isinstance(run_meta.get("run"), dict) else {}
    run_date = (
        run_meta.get("run_date")
        or run_meta.get("date")
        or run_meta.get("runDate")
        or nested.get("date")
        or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    )
    run_hour = run_meta.get("run_hour_utc")
    if run_hour is None:
        run_hour = run_meta.get("time")
    if run_hour is None:
        run_hour = run_meta.get("hour_utc")
    if run_hour is None:
        run_hour = nested.get("hour_utc")
    if run_hour is None:
        run_hour = 0
    run_hour = int(run_hour)
    return datetime.strptime(f"{run_date} {run_hour:02d}", "%Y-%m-%d %H").replace(tzinfo=timezone.utc)


def valid_time_labels(run_meta, step):
    run_dt = parse_run_datetime(run_meta)
    valid_utc = run_dt + timedelta(hours=int(step))
    try:
        from zoneinfo import ZoneInfo
        valid_it = valid_utc.astimezone(ZoneInfo("Europe/Rome"))
    except Exception:
        valid_it = valid_utc.astimezone(timezone(timedelta(hours=2)))
    return {
        "run_utc": run_dt,
        "valid_utc": valid_utc,
        "valid_it": valid_it,
        "run_label": run_dt.strftime("%Y-%m-%d %H UTC"),
        "valid_label": valid_it.strftime("%H:%M %d/%m/%Y"),
    }


def find_file(varname, step):
    for pattern in FILE_ALIASES.get(varname, []):
        fp = INPUT_DIR / pattern.format(step=int(step))
        if fp.exists():
            return fp
    return None


def open_grib(path):
    ds = xr.open_dataset(path, engine="cfgrib", backend_kwargs={"indexpath": ""})
    data_vars = list(ds.data_vars)
    if not data_vars:
        raise RuntimeError(f"Nessuna variabile trovata in {path.name}")
    var = data_vars[0]
    da = ds[var].squeeze()
    if "latitude" not in da.coords and "latitude" not in ds.coords:
        raise RuntimeError(f"Coordinate latitude non trovate in {path.name}")
    if "longitude" not in da.coords and "longitude" not in ds.coords:
        raise RuntimeError(f"Coordinate longitude non trovate in {path.name}")
    lat_coord = da.coords["latitude"] if "latitude" in da.coords else ds.coords["latitude"]
    lon_coord = da.coords["longitude"] if "longitude" in da.coords else ds.coords["longitude"]
    lats = np.asarray(lat_coord.values, dtype=float)
    lons = np.asarray(lon_coord.values, dtype=float)
    data = np.asarray(da.values, dtype=float)
    if data.ndim != 2:
        raise RuntimeError(f"Dato non 2D in {path.name}. Shape: {data.shape}")
    if lats.ndim == 2:
        lats = lats[:, 0]
    if lons.ndim == 2:
        lons = lons[0, :]
    if np.nanmax(lons) > 180:
        lons = ((lons + 180) % 360) - 180
        order = np.argsort(lons)
        lons = lons[order]
        data = data[:, order]
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
    return lats[lat_mask], lons[lon_mask], data[np.ix_(lat_mask, lon_mask)]


def upscale_field(lats, lons, data, factor=UPSCALE_FACTOR):
    if factor <= 1:
        return lats, lons, data
    if HAS_SCIPY:
        out = zoom(data, factor, order=1)
    else:
        y_old = np.arange(data.shape[0])
        x_old = np.arange(data.shape[1])
        y_new = np.linspace(0, data.shape[0] - 1, (data.shape[0] - 1) * factor + 1)
        x_new = np.linspace(0, data.shape[1] - 1, (data.shape[1] - 1) * factor + 1)
        temp = np.empty((data.shape[0], len(x_new)), dtype=float)
        for i in range(data.shape[0]):
            temp[i, :] = np.interp(x_new, x_old, data[i, :])
        out = np.empty((len(y_new), len(x_new)), dtype=float)
        for j in range(len(x_new)):
            out[:, j] = np.interp(y_new, y_old, temp[:, j])
    new_lats = np.linspace(float(lats[0]), float(lats[-1]), out.shape[0])
    new_lons = np.linspace(float(lons[0]), float(lons[-1]), out.shape[1])
    return new_lats, new_lons, out


def smooth_field(data, sigma=SMOOTH_SIGMA):
    arr = np.asarray(data, dtype=float)
    if not HAS_SCIPY or sigma <= 0:
        return arr
    mask = np.isfinite(arr)
    if not mask.any():
        return arr
    filled = arr.copy()
    filled[~mask] = np.nanmean(arr[mask])
    out = gaussian_filter(filled, sigma=sigma)
    return out


def read_field(varname, step, required=True):
    fp = find_file(varname, step)
    if fp is None:
        if required:
            raise FileNotFoundError(f"Manca file {varname} H+{step:03d}")
        return None
    lats, lons, data = open_grib(fp)
    lats, lons, data = crop_bbox(lats, lons, data)
    lats, lons, data = upscale_field(lats, lons, data, UPSCALE_FACTOR)
    data = smooth_field(data, SMOOTH_SIGMA)
    return {"file": fp.name, "lats": lats, "lons": lons, "data": data}


def load_land_sea_mask():
    fp = INPUT_DIR / "lsm.grib"
    if not fp.exists():
        add_warning(f"LSM non trovato ({fp}): skip coastal fill immagini")
        return None
    lats, lons, data = open_grib(fp)
    lats, lons, data = crop_bbox(lats, lons, data)
    lats, lons, data = upscale_field(lats, lons, data, UPSCALE_FACTOR)
    data = np.clip(np.asarray(data, dtype=float), 0, 1)
    return {"file": fp.name, "lats": lats, "lons": lons, "data": data}


def map_lsm_to_target(lsm, target_lats, target_lons):
    if lsm is None:
        return None
    if len(lsm["lats"]) == len(target_lats) and len(lsm["lons"]) == len(target_lons):
        return np.asarray(lsm["data"], dtype=float)
    lsm_lats = np.asarray(lsm["lats"], dtype=float)
    lsm_lons = np.asarray(lsm["lons"], dtype=float)
    lat_idx = np.abs(lsm_lats[:, None] - np.asarray(target_lats, dtype=float)[None, :]).argmin(axis=0)
    lon_idx = np.abs(lsm_lons[:, None] - np.asarray(target_lons, dtype=float)[None, :]).argmin(axis=0)
    return np.asarray(lsm["data"], dtype=float)[np.ix_(lat_idx, lon_idx)]


def fill_nan_with_nearest_sea(data, lsm_mask, radius=COASTAL_FILL_RADIUS):
    if lsm_mask is None:
        return data
    arr = np.asarray(data, dtype=float)
    filled = arr.copy()
    sea_mask = np.asarray(lsm_mask, dtype=float) <= 0.5
    if arr.shape != sea_mask.shape:
        return filled
    if not np.isnan(arr).any():
        return filled
    nan_positions = np.argwhere(~np.isfinite(arr) & sea_mask)
    for (y, x) in nan_positions:
        r0 = max(0, y - radius)
        r1 = min(arr.shape[0], y + radius + 1)
        c0 = max(0, x - radius)
        c1 = min(arr.shape[1], x + radius + 1)
        window = arr[r0:r1, c0:c1]
        window_sea = sea_mask[r0:r1, c0:c1]
        valid = window[np.isfinite(window) & window_sea]
        if valid.size:
            filled[y, x] = float(valid[0])
    return filled


def wind_kmh_from_uv(u, v):
    return np.sqrt(u ** 2 + v ** 2) * 3.6


def wind_dir_from_uv(u, v):
    return (np.degrees(np.arctan2(-u, -v)) + 360) % 360


def celsius_from_kelvin(k):
    return k - 273.15 if np.nanmean(k) > 100 else k


def pressure_to_hpa(p):
    return p / 100.0 if np.nanmean(p) > 2000 else p


def cloud_to_pct(c):
    c = np.asarray(c, dtype=float)
    if np.nanmax(c) <= 1.5:
        c = c * 100.0
    return np.clip(c, 0, 100)


def precip_to_mm(p):
    p = np.asarray(p, dtype=float)
    return np.maximum(p * 1000.0, 0) if np.nanmax(p) < 10 else np.maximum(p, 0)


def wave_to_cm(w):
    w = np.asarray(w, dtype=float)
    return np.maximum(w * 100.0, 0) if np.nanmax(w) < 20 else np.maximum(w, 0)


def nearest_sample(lats, lons, data, lat, lon):
    ilat = int(np.argmin(np.abs(lats - lat)))
    ilon = int(np.argmin(np.abs(lons - lon)))
    value = float(data[ilat, ilon])
    return value if np.isfinite(value) else float("nan")


def bilinear_sample(lats, lons, data, lon, lat):
    if lon < lons[0] or lon > lons[-1] or lat < lats[0] or lat > lats[-1]:
        return np.nan
    xi = np.interp(lon, lons, np.arange(len(lons)))
    yi = np.interp(lat, lats, np.arange(len(lats)))
    x0 = int(np.floor(xi)); y0 = int(np.floor(yi))
    x1 = min(x0 + 1, len(lons) - 1); y1 = min(y0 + 1, len(lats) - 1)
    tx = xi - x0; ty = yi - y0
    vals = np.array([data[y0, x0], data[y0, x1], data[y1, x0], data[y1, x1]], dtype=float)
    if not np.isfinite(vals).all():
        return np.nan
    v00, v10, v01, v11 = vals
    a = v00 * (1 - tx) + v10 * tx
    b = v01 * (1 - tx) + v11 * tx
    return a * (1 - ty) + b * ty


def transparent_cmap(name, colors):
    return LinearSegmentedColormap.from_list(name, colors)


CMAP_WIND = transparent_cmap("wind_flow", [(0.00, "#173c94"), (0.15, "#2179e7"), (0.30, "#1ab8e8"), (0.45, "#2bd4b0"), (0.60, "#8de166"), (0.75, "#f1d04b"), (0.88, "#ff902c"), (1.00, "#ef4049")])
CMAP_GUSTS = transparent_cmap("gusts_flow", [(0.00, "#6930c3"), (0.22, "#ff8a2a"), (0.48, "#ff4c4c"), (0.72, "#ff1493"), (1.00, "#bd00ff")])
CMAP_TEMP = transparent_cmap("temperature_smooth", [(0.00, "#2044b8"), (0.16, "#2b87dd"), (0.32, "#3bbdcf"), (0.48, "#75cb6a"), (0.64, "#e1c942"), (0.80, "#f39d2d"), (1.00, "#d33b32")])
CMAP_RAIN = transparent_cmap("rain_radar", [(0.00, (0.0, 0.0, 0.0, 0.0)), (0.06, (0.67, 0.95, 1.00, 0.24)), (0.20, (0.27, 0.76, 1.00, 0.40)), (0.40, (0.06, 0.43, 1.00, 0.56)), (0.64, (0.08, 0.16, 0.82, 0.72)), (0.82, (0.46, 0.13, 0.70, 0.84)), (1.00, (0.85, 0.08, 0.34, 0.94))])
CMAP_PRESSURE = transparent_cmap("pressure_smooth", [(0.00, "#1a66d9"), (0.25, "#6db0ef"), (0.50, "#f1f1d0"), (0.75, "#f3a35a"), (1.00, "#cc4333")])
CMAP_WAVES = transparent_cmap("waves_smooth", [(0.00, (0.0, 0.0, 0.0, 0.0)), (0.15, "#55e7ff"), (0.38, "#1ca9db"), (0.62, "#0d79bf"), (0.82, "#0c4e96"), (1.00, "#d8fbff")])


def fbm_noise(shape, seed=0, octaves=5):
    rng = np.random.default_rng(seed)
    h, w = shape
    out = np.zeros((h, w), dtype=float)
    amp = 1.0
    for i in range(octaves):
        base = rng.random((h, w))
        if HAS_SCIPY:
            sigma = max(1.0, min(h, w) / (16 * (2 ** i)))
            base = gaussian_filter(base, sigma=sigma)
        out += base * amp
        amp *= 0.55
    out -= np.nanmin(out)
    maxv = np.nanmax(out)
    if maxv > 0:
        out /= maxv
    return out


def satellite_cloud_rgba(cloud_pct, seed):
    cloud = np.clip(np.asarray(cloud_pct, dtype=float) / 100.0, 0, 1)
    n1 = fbm_noise(cloud.shape, seed=seed, octaves=5)
    n2 = fbm_noise(cloud.shape, seed=seed + 31, octaves=4)
    texture = n1 * 0.72 + n2 * 0.28
    if HAS_SCIPY:
        texture = gaussian_filter(texture, sigma=0.85)
    texture -= np.nanmin(texture)
    maxv = np.nanmax(texture)
    if maxv > 0:
        texture /= maxv
    cloud_top = np.clip((cloud ** 1.25) * (0.45 + 0.90 * texture), 0, 1)
    if HAS_SCIPY:
        soft = gaussian_filter(cloud_top, sigma=2.0)
        detail = np.clip(cloud_top - soft, 0, 1)
        cloud_top = np.clip(cloud_top + detail * 1.2, 0, 1)
    rgba = np.zeros((cloud.shape[0], cloud.shape[1], 4), dtype=float)
    rgba[..., 0] = 0.95; rgba[..., 1] = 0.96; rgba[..., 2] = 0.98
    alpha = np.clip(cloud_top * 0.96, 0, 0.96)
    alpha = np.where(cloud < 0.08, 0, alpha)
    rgba[..., 3] = alpha
    return rgba


def generate_flow_lines(lons, lats, u, v, intensity, seed, n_lines=700, trail_steps=8, scale=0.04):
    rng = np.random.default_rng(seed)
    lines = []; colors = []; widths = []
    inten = np.nan_to_num(np.asarray(intensity, dtype=float), nan=0.0)
    weights = np.maximum(inten, 0).ravel()
    if weights.sum() <= 0:
        weights[:] = 1.0
    weights = weights / weights.sum()
    ny, nx = inten.shape
    total = ny * nx
    chosen = rng.choice(total, size=int(n_lines), replace=True, p=weights)
    for flat_idx in chosen:
        iy = flat_idx // nx; ix = flat_idx % nx
        lon = float(lons[ix]); lat = float(lats[iy])
        pts = [(lon, lat)]
        ok = True
        for _ in range(trail_steps):
            uu = bilinear_sample(lats, lons, u, lon, lat)
            vv = bilinear_sample(lats, lons, v, lon, lat)
            sp = bilinear_sample(lats, lons, inten, lon, lat)
            if not np.isfinite(uu) or not np.isfinite(vv) or not np.isfinite(sp):
                ok = False; break
            lon += uu * scale / max(0.45, math.cos(math.radians(lat)))
            lat += vv * scale
            if lon < lons[0] or lon > lons[-1] or lat < lats[0] or lat > lats[-1]:
                ok = False; break
            pts.append((lon, lat))
        if ok and len(pts) >= 2:
            val = bilinear_sample(lats, lons, inten, pts[0][0], pts[0][1])
            if np.isfinite(val):
                lines.append(pts); colors.append(float(val)); widths.append(float(val))
    return lines, np.asarray(colors), np.asarray(widths)


def add_flow_collection(ax, lines, colors, widths, cmap, vmin, vmax, min_w, max_w, alpha=0.78):
    if not lines:
        return
    normed = np.clip((widths - vmin) / max(vmax - vmin, 1e-6), 0, 1)
    lw = min_w + normed * (max_w - min_w)
    lc = LineCollection(lines, cmap=cmap, norm=plt.Normalize(vmin=vmin, vmax=vmax), linewidths=lw, alpha=alpha,
                        transform=ccrs.PlateCarree(), capstyle="round", joinstyle="round", zorder=30)
    lc.set_array(colors)
    ax.add_collection(lc)


def add_plain_lines(ax, lines, color, linewidth=0.7, alpha=0.3, zorder=31):
    if not lines:
        return
    lc = LineCollection(lines, linewidths=linewidth, colors=[color] * len(lines), alpha=alpha,
                        transform=ccrs.PlateCarree(), capstyle="round", joinstyle="round", zorder=zorder)
    ax.add_collection(lc)


def add_base_map(ax):
    ax.set_extent([BBOX["west"], BBOX["east"], BBOX["south"], BBOX["north"]], crs=ccrs.PlateCarree())
    ax.set_facecolor("#0c2f69")
    ocean = cfeature.NaturalEarthFeature("physical", "ocean", "50m", edgecolor="none", facecolor="#173e86")
    land = cfeature.NaturalEarthFeature("physical", "land", "50m", edgecolor="none", facecolor="#8f8d5d")
    lakes = cfeature.NaturalEarthFeature("physical", "lakes", "50m", edgecolor="none", facecolor="#1e559d")
    ax.add_feature(ocean, zorder=0)
    ax.add_feature(land, zorder=1)
    ax.add_feature(lakes, zorder=2)
    ax.add_feature(cfeature.COASTLINE.with_scale("50m"), linewidth=0.65, edgecolor="#1b1b1b", zorder=50)
    ax.add_feature(cfeature.BORDERS.with_scale("50m"), linewidth=0.45, edgecolor="#444", zorder=50)
    ax.gridlines(draw_labels=False, linewidth=0.25, color="white", alpha=0.10, linestyle="-")


def setup_figure():
    fig = plt.figure(figsize=(FIG_W, FIG_H), dpi=DPI, facecolor="#07111f")
    ax = plt.axes(projection=ccrs.PlateCarree())
    add_base_map(ax)
    return fig, ax


def add_titles(ax, title, valid_label, run_label, extra=None):
    ax.text(0.5, 1.035, title, transform=ax.transAxes, ha="center", va="bottom", fontsize=16, fontweight="bold", color="white",
            path_effects=[pe.withStroke(linewidth=3, foreground="black", alpha=0.55)], zorder=100)
    ax.text(0.5, 1.09, valid_label, transform=ax.transAxes, ha="center", va="bottom", fontsize=11, color="white",
            path_effects=[pe.withStroke(linewidth=3, foreground="black", alpha=0.55)], zorder=100)
    lines = [f"Run: {run_label}"]
    if extra:
        lines.extend(extra)
    ax.text(0.012, 0.02, "\n".join(lines), transform=ax.transAxes, ha="left", va="bottom", fontsize=9, color="white",
            bbox=dict(boxstyle="round,pad=0.35", fc=(0, 0, 0, 0.55), ec=(1, 1, 1, 0.18)), zorder=100)


def add_points(ax):
    ax.scatter([ARDEA["lon"]], [ARDEA["lat"]], s=28, c="#ffe42b", edgecolors="#222", linewidths=0.8,
               transform=ccrs.PlateCarree(), zorder=90)
    ax.text(ARDEA["lon"] + 0.16, ARDEA["lat"] + 0.08, "Ardea", fontsize=9, color="white",
            transform=ccrs.PlateCarree(), path_effects=[pe.withStroke(linewidth=3, foreground="black", alpha=0.7)], zorder=91)


def add_colorbar(fig, ax, cmap, vmin, vmax, label):
    sm = plt.cm.ScalarMappable(norm=plt.Normalize(vmin=vmin, vmax=vmax), cmap=cmap)
    sm.set_array([])
    cbar = fig.colorbar(sm, ax=ax, orientation="vertical", fraction=0.028, pad=0.02)
    cbar.set_label(label, color="white")
    cbar.ax.yaxis.set_tick_params(color="white")
    plt.setp(plt.getp(cbar.ax.axes, "yticklabels"), color="white")
    cbar.outline.set_edgecolor("white")


def add_raster(ax, lats, lons, data, cmap, alpha, zorder, vmin=None, vmax=None):
    extent = [lons[0], lons[-1], lats[0], lats[-1]]
    ax.imshow(data, extent=extent, origin="lower", transform=ccrs.PlateCarree(), cmap=cmap, alpha=alpha,
              interpolation="bicubic", zorder=zorder, vmin=vmin, vmax=vmax)


def load_step_data(step, lsm_mask=None):
    u10 = read_field("u10", step, required=True)
    v10 = read_field("v10", step, required=True)
    temperature = read_field("temperature", step, required=True)
    precipitation = read_field("precipitation", step, required=True)
    cloud_cover = read_field("cloud_cover", step, required=True)
    pressure = read_field("pressure", step, required=True)
    gust = read_field("gust", step, required=False)
    wave_height = read_field("wave_height", step, required=False)
    lats = u10["lats"]; lons = u10["lons"]
    u = u10["data"]; v = v10["data"]
    wind_kmh = wind_kmh_from_uv(u, v)
    wind_dir = wind_dir_from_uv(u, v)
    gust_kmh = gust["data"] * 3.6 if gust is not None else np.maximum(wind_kmh * 1.35, wind_kmh + 8.0)
    temp_c = celsius_from_kelvin(temperature["data"])
    rain_accum_mm = precip_to_mm(precipitation["data"])
    cloud_pct = cloud_to_pct(cloud_cover["data"])
    pressure_hpa = pressure_to_hpa(pressure["data"])
    wave_cm = wave_to_cm(wave_height["data"]) if wave_height is not None else None
    step_data = {
        "step": int(step),
        "lats": lats, "lons": lons,
        "u10": u, "v10": v,
        "wind_kmh": wind_kmh,
        "wind_dir_deg": wind_dir,
        "gust_kmh": gust_kmh,
        "temperature_c": temp_c,
        "precipitation_accum_mm": rain_accum_mm,
        "precipitation_mm": rain_accum_mm,
        "cloud_cover_pct": cloud_pct,
        "pressure_hpa": pressure_hpa,
        "wave_height_cm": wave_cm,
        "files": {"u10": u10["file"], "v10": v10["file"], "gust": gust["file"] if gust else None,
                  "temperature": temperature["file"], "precipitation": precipitation["file"],
                  "cloud_cover": cloud_cover["file"], "pressure": pressure["file"],
                  "wave_height": wave_height["file"] if wave_height else None}
    }
    return apply_coastal_fill_to_step_data(step_data, lsm_mask)


def apply_coastal_fill_to_step_data(data, lsm_mask):
    if lsm_mask is None:
        return data
    for key in [
        "u10",
        "v10",
        "wind_kmh",
        "wind_dir_deg",
        "gust_kmh",
        "temperature_c",
        "precipitation_accum_mm",
        "precipitation_mm",
        "cloud_cover_pct",
        "pressure_hpa",
        "wave_height_cm",
    ]:
        if data.get(key) is not None:
            data[key] = fill_nan_with_nearest_sea(data[key], lsm_mask)
    return data


def render_wind(data, meta, frame_idx):
    fig, ax = setup_figure(); lats = data["lats"]; lons = data["lons"]; speed = data["wind_kmh"]
    add_raster(ax, lats, lons, speed, CMAP_WIND, alpha=0.18, zorder=10, vmin=0, vmax=110)
    lines, colors, widths = generate_flow_lines(lons, lats, data["u10"], data["v10"], speed, seed=1000 + frame_idx,
                                                n_lines=FLOW_COUNT_WIND, trail_steps=9, scale=0.040)
    add_flow_collection(ax, lines, colors, widths, CMAP_WIND, vmin=0, vmax=110, min_w=0.55, max_w=2.4, alpha=0.86)
    lines_g, colors_g, widths_g = generate_flow_lines(lons, lats, data["u10"], data["v10"], data["gust_kmh"], seed=1600 + frame_idx,
                                                      n_lines=260, trail_steps=6, scale=0.048)
    add_flow_collection(ax, lines_g, colors_g, widths_g, CMAP_GUSTS, vmin=0, vmax=130, min_w=0.8, max_w=3.2, alpha=0.45)
    ar_w = nearest_sample(lats, lons, speed, ARDEA["lat"], ARDEA["lon"])
    ar_g = nearest_sample(lats, lons, data["gust_kmh"], ARDEA["lat"], ARDEA["lon"])
    add_points(ax)
    add_titles(ax, "Vento 10m + raffiche", meta["valid_label"], meta["run_label"], [f"Ardea vento: {ar_w:.1f} km/h", f"Ardea raffica: {ar_g:.1f} km/h"])
    add_colorbar(fig, ax, CMAP_WIND, 0, 110, "km/h")
    return fig


def render_gusts(data, meta, frame_idx):
    fig, ax = setup_figure(); lats = data["lats"]; lons = data["lons"]; gust = data["gust_kmh"]
    add_raster(ax, lats, lons, gust, CMAP_GUSTS, alpha=0.18, zorder=10, vmin=0, vmax=130)
    lines, colors, widths = generate_flow_lines(lons, lats, data["u10"], data["v10"], gust, seed=2000 + frame_idx,
                                                n_lines=FLOW_COUNT_GUSTS, trail_steps=8, scale=0.050)
    add_flow_collection(ax, lines, colors, widths, CMAP_GUSTS, vmin=0, vmax=130, min_w=0.80, max_w=3.8, alpha=0.90)
    ar_g = nearest_sample(lats, lons, gust, ARDEA["lat"], ARDEA["lon"])
    add_points(ax)
    add_titles(ax, "Raffiche di vento", meta["valid_label"], meta["run_label"], [f"Ardea raffica: {ar_g:.1f} km/h"])
    add_colorbar(fig, ax, CMAP_GUSTS, 0, 130, "km/h")
    return fig


def render_precipitation(data, meta, frame_idx):
    fig, ax = setup_figure(); lats = data["lats"]; lons = data["lons"]; rain = data["precipitation_mm"]
    vmax = max(8, float(np.nanpercentile(rain, 98)))
    add_raster(ax, lats, lons, rain, CMAP_RAIN, alpha=0.95, zorder=20, vmin=0, vmax=vmax)
    lines, _, widths = generate_flow_lines(lons, lats, data["u10"], data["v10"], np.maximum(rain, 0), seed=3000 + frame_idx,
                                           n_lines=FLOW_COUNT_RAIN, trail_steps=3, scale=0.026)
    if len(lines):
        lw = 0.45 + np.clip(widths / max(vmax, 1), 0, 1) * 1.8
        lc = LineCollection(lines, linewidths=lw, colors=[(0.90, 0.98, 1.00, 0.42)] * len(lines),
                            transform=ccrs.PlateCarree(), capstyle="round", joinstyle="round", zorder=31)
        ax.add_collection(lc)
    ar_r = nearest_sample(lats, lons, rain, ARDEA["lat"], ARDEA["lon"])
    add_points(ax)
    add_titles(ax, "Pioggia / precipitazioni", meta["valid_label"], meta["run_label"], [f"Ardea pioggia: {ar_r:.2f} mm"])
    add_colorbar(fig, ax, CMAP_RAIN, 0, vmax, "mm/step")
    return fig


def render_cloud_cover(data, meta, frame_idx):
    fig, ax = setup_figure(); lats = data["lats"]; lons = data["lons"]; clouds = data["cloud_cover_pct"]
    extent = [lons[0], lons[-1], lats[0], lats[-1]]
    rgba = satellite_cloud_rgba(clouds, seed=4000 + frame_idx)
    ax.imshow(rgba, extent=extent, origin="lower", transform=ccrs.PlateCarree(), interpolation="bicubic", zorder=25)
    lines, _, _ = generate_flow_lines(lons, lats, data["u10"], data["v10"], np.maximum(clouds, 0), seed=4300 + frame_idx,
                                      n_lines=FLOW_COUNT_CLOUDS, trail_steps=4, scale=0.020)
    add_plain_lines(ax, lines, color=(1, 1, 1, 0.14), linewidth=0.42, alpha=0.55, zorder=32)
    ar_c = nearest_sample(lats, lons, clouds, ARDEA["lat"], ARDEA["lon"])
    add_points(ax)
    add_titles(ax, "Copertura nuvolosa - stile satellite", meta["valid_label"], meta["run_label"], [f"Ardea nuvolosità: {ar_c:.0f} %"])
    add_colorbar(fig, ax, plt.cm.Greys_r, 0, 100, "%")
    return fig


def render_temperature(data, meta, frame_idx):
    fig, ax = setup_figure(); lats = data["lats"]; lons = data["lons"]; temp = data["temperature_c"]
    vmin = min(-5, float(np.nanpercentile(temp, 2))); vmax = max(35, float(np.nanpercentile(temp, 98)))
    add_raster(ax, lats, lons, temp, CMAP_TEMP, alpha=0.62, zorder=12, vmin=vmin, vmax=vmax)
    lines, _, _ = generate_flow_lines(lons, lats, data["u10"], data["v10"], np.maximum(data["wind_kmh"], 1), seed=5000 + frame_idx,
                                      n_lines=300, trail_steps=5, scale=0.030)
    add_plain_lines(ax, lines, color=(1, 1, 1, 0.16), linewidth=0.55, alpha=0.60, zorder=31)
    ar_t = nearest_sample(lats, lons, temp, ARDEA["lat"], ARDEA["lon"])
    add_points(ax)
    add_titles(ax, "Temperatura 2 metri", meta["valid_label"], meta["run_label"], [f"Ardea temperatura: {ar_t:.1f} °C"])
    add_colorbar(fig, ax, CMAP_TEMP, vmin, vmax, "°C")
    return fig


def render_pressure(data, meta, frame_idx):
    fig, ax = setup_figure(); lats = data["lats"]; lons = data["lons"]; press = data["pressure_hpa"]
    vmin = float(np.nanpercentile(press, 2)); vmax = float(np.nanpercentile(press, 98))
    add_raster(ax, lats, lons, press, CMAP_PRESSURE, alpha=0.38, zorder=10, vmin=vmin, vmax=vmax)
    try:
        start = math.floor(np.nanmin(press) / 2) * 2; stop = math.ceil(np.nanmax(press) / 2) * 2
        levels = np.arange(start, stop + 0.1, 2)
        cs = ax.contour(lons, lats, press, levels=levels, colors="white", linewidths=0.55, alpha=0.48,
                        transform=ccrs.PlateCarree(), zorder=35)
        ax.clabel(cs, inline=True, fmt="%d", fontsize=6, colors="white")
    except Exception:
        pass
    ar_p = nearest_sample(lats, lons, press, ARDEA["lat"], ARDEA["lon"])
    add_points(ax)
    add_titles(ax, "Pressione atmosferica", meta["valid_label"], meta["run_label"], [f"Ardea pressione: {ar_p:.1f} hPa"])
    add_colorbar(fig, ax, CMAP_PRESSURE, vmin, vmax, "hPa")
    return fig


def render_wave_height(data, meta, frame_idx):
    fig, ax = setup_figure(); lats = data["lats"]; lons = data["lons"]; wave = data["wave_height_cm"]
    if wave is None:
        add_points(ax)
        add_titles(ax, "Mare / onde", meta["valid_label"], meta["run_label"], ["Dato onde non disponibile"])
        return fig
    vmax = max(120, float(np.nanpercentile(wave, 98)))
    add_raster(ax, lats, lons, wave, CMAP_WAVES, alpha=0.74, zorder=16, vmin=0, vmax=vmax)
    lines, _, widths = generate_flow_lines(lons, lats, data["u10"], data["v10"], np.maximum(wave, 0), seed=6000 + frame_idx,
                                           n_lines=FLOW_COUNT_WAVES, trail_steps=2, scale=0.018)
    if len(lines):
        lw = 0.45 + np.clip(widths / max(vmax, 1), 0, 1) * 1.8
        lc = LineCollection(lines, linewidths=lw, colors=[(0.92, 0.99, 1.00, 0.52)] * len(lines),
                            transform=ccrs.PlateCarree(), capstyle="round", joinstyle="round", zorder=32)
        ax.add_collection(lc)
    ar_w = nearest_sample(lats, lons, wave, ARDEA_SEA["lat"], ARDEA_SEA["lon"])
    add_points(ax)
    add_titles(ax, "Mare / altezza onde", meta["valid_label"], meta["run_label"], [f"Mare Ardea onda: {ar_w:.0f} cm"])
    add_colorbar(fig, ax, CMAP_WAVES, 0, vmax, "cm")
    return fig


RENDERERS = {
    "wind": render_wind,
    "gusts": render_gusts,
    "precipitation": render_precipitation,
    "cloud_cover": render_cloud_cover,
    "temperature": render_temperature,
    "pressure": render_pressure,
    "wave_height": render_wave_height,
}


def save_fig(fig, out_path):
    fig.savefig(out_path, dpi=DPI, bbox_inches="tight", pad_inches=0.08, facecolor=fig.get_facecolor())
    plt.close(fig)
    SUMMARY["files_created"].append(str(out_path))


def build_webp(frames, out_path, duration_ms):
    """
    Crea WEBP animata normalizzando le dimensioni di tutti i frame.

    Serve soprattutto per pressure, perché le etichette delle isobare/colorbar
    possono far salvare PNG con dimensioni leggermente diverse quando si usa
    bbox_inches="tight".
    """
    if not frames:
        raise RuntimeError(f"Nessun frame per {out_path}")

    imgs = []

    with Image.open(frames[0]) as first:
        first_rgb = first.convert("RGB")
        target_size = first_rgb.size
        imgs.append(first_rgb.copy())

    for fp in frames[1:]:
        with Image.open(fp) as im:
            img = im.convert("RGB")

            if img.size != target_size:
                fixed = Image.new("RGB", target_size, (7, 17, 31))

                # ridimensiona mantenendo proporzioni e centra
                ratio = min(target_size[0] / img.size[0], target_size[1] / img.size[1])
                new_size = (
                    max(1, int(img.size[0] * ratio)),
                    max(1, int(img.size[1] * ratio))
                )

                img_resized = img.resize(new_size, Image.Resampling.LANCZOS)
                x = (target_size[0] - new_size[0]) // 2
                y = (target_size[1] - new_size[1]) // 2
                fixed.paste(img_resized, (x, y))
                img = fixed

            imgs.append(img.copy())

    imgs[0].save(
        out_path,
        save_all=True,
        append_images=imgs[1:],
        duration=duration_ms,
        loop=0,
        optimize=True,
        format="WEBP"
    )

    SUMMARY["files_created"].append(str(out_path))


def make_json_safe(obj):
    if isinstance(obj, dict):
        return {str(k): make_json_safe(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [make_json_safe(v) for v in obj]
    if isinstance(obj, tuple):
        return [make_json_safe(v) for v in obj]
    if isinstance(obj, np.ndarray):
        return make_json_safe(obj.tolist())
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating, float)):
        v = float(obj)
        return None if not np.isfinite(v) else v
    if isinstance(obj, (datetime,)):
        return obj.isoformat()
    return obj


def write_json(path, data):
    safe = make_json_safe(data)
    path.write_text(json.dumps(safe, indent=2, ensure_ascii=False, allow_nan=False), encoding="utf-8")
    SUMMARY["files_created"].append(str(path))


def write_esiti():
    lines = [
        "==========================================",
        "METEO RENDER ITALIA SMOOTH",
        "==========================================",
        f"Creato: {SUMMARY['created_at']}",
        f"Input: {INPUT_DIR}",
        f"Output: {OUTPUT_DIR}",
        f"BBOX: {BBOX}",
        f"UPSCALE_FACTOR: {UPSCALE_FACTOR}",
        f"SMOOTH_SIGMA: {SMOOTH_SIGMA}",
        f"HAS_SCIPY: {HAS_SCIPY}",
        "",
        "FRAME",
        "------------------------------------------",
    ]
    for layer, count in SUMMARY["frames"].items():
        lines.append(f"{layer}: {count}")
    lines += ["", "WARNING", "------------------------------------------"]
    if SUMMARY["warnings"]:
        lines.extend(str(item) for item in SUMMARY["warnings"])
    else:
        lines.append("Nessun warning.")
    lines += ["", "ERRORI", "------------------------------------------"]
    if SUMMARY["errors"]:
        for err in SUMMARY["errors"]:
            lines.append(f"{err['layer']} H+{err['step']}: {err['error']}")
    else:
        lines.append("Nessun errore.")
    lines += ["", "FILE CREATI", "------------------------------------------"]
    for fp in SUMMARY["files_created"]:
        lines.append(fp)
    out = OUTPUT_DIR / "ESITI_RENDER.txt"
    out.write_text("\n".join(lines), encoding="utf-8")
    SUMMARY["files_created"].append(str(out))


def main():
    ensure_dirs(); clean_old_frames()
    log("==========================================")
    log("METEO RENDER ITALIA SMOOTH")
    log("==========================================")
    log(f"Base: {BASE_DIR}")
    log(f"Input: {INPUT_DIR}")
    log(f"Output: {OUTPUT_DIR}")
    log(f"BBOX: {BBOX}")
    log(f"UPSCALE_FACTOR: {UPSCALE_FACTOR}")
    log(f"SMOOTH_SIGMA: {SMOOTH_SIGMA}")
    log(f"HAS_SCIPY: {HAS_SCIPY}")
    if not INPUT_DIR.exists():
        raise RuntimeError(f"Cartella input non trovata: {INPUT_DIR}")
    run_meta = load_run_meta()
    steps = get_steps(run_meta)
    if not steps:
        raise RuntimeError("Nessuno step trovato.")
    log(f"Step trovati: {steps}")
    land_sea_mask = load_land_sea_mask()
    mapped_lsm = None
    manifest = {
        "ok": True,
        "project": "Meteo Italia Smooth Render",
        "version": "2.4-lsm-coastal-fill",
        "created_at": datetime.now().isoformat(),
        "source": "ECMWF Open Data / local GRIB render",
        "bbox": BBOX,
        "run_meta": run_meta,
        "steps": steps,
        "layers": LAYERS,
        "animations": {},
        "paths": {"frames": "frames", "animations": "animations"},
    }
    frames_by_layer = {layer: [] for layer in LAYERS}
    previous_rain_accum = None
    for frame_idx, step in enumerate(steps):
        log("------------------------------------------")
        log(f"STEP H+{step:03d}")
        log("------------------------------------------")
        try:
            data = load_step_data(step, lsm_mask=mapped_lsm)
            if mapped_lsm is None:
                mapped_lsm = map_lsm_to_target(land_sea_mask, data["lats"], data["lons"])
                if mapped_lsm is not None:
                    data = apply_coastal_fill_to_step_data(data, mapped_lsm)
            current_accum = np.asarray(data["precipitation_accum_mm"], dtype=float)
            if previous_rain_accum is None:
                rain_step = np.maximum(current_accum, 0)
            else:
                rain_step = np.maximum(current_accum - previous_rain_accum, 0)
            previous_rain_accum = current_accum.copy()
            data["precipitation_mm"] = rain_step
            meta = valid_time_labels(run_meta, step)
        except Exception as e:
            add_error("load_step_data", step, e)
            log(f"ERRORE caricamento dati H+{step:03d}: {e}")
            continue
        for layer in LAYERS:
            try:
                fig = RENDERERS[layer](data, meta, frame_idx)
                out_frame = FRAMES_DIR / layer / f"{layer}_{frame_idx:04d}.png"
                save_fig(fig, out_frame)
                frames_by_layer[layer].append(out_frame)
                log(f"OK {layer} frame {frame_idx + 1}/{len(steps)}")
            except Exception as e:
                add_error(layer, step, e)
                log(f"ERRORE {layer} H+{step:03d}: {e}")
    log("==========================================")
    log("CREO ANIMAZIONI WEBP")
    log("==========================================")
    for layer in LAYERS:
        try:
            frames = frames_by_layer[layer]
            out_webp = ANIM_DIR / f"{layer}.webp"
            build_webp(frames, out_webp, FRAME_DURATION_MS.get(layer, 120))
            SUMMARY["frames"][layer] = len(frames)
            manifest["animations"][layer] = {"file": f"animations/{layer}.webp", "frames": len(frames), "duration_ms": FRAME_DURATION_MS.get(layer, 120)}
            log(f"OK WEBP {layer}: {out_webp}")
        except Exception as e:
            add_error(f"webp_{layer}", "-", e)
            log(f"ERRORE WEBP {layer}: {e}")
    manifest["ok"] = len(SUMMARY["errors"]) == 0
    SUMMARY["ok"] = len(SUMMARY["errors"]) == 0
    write_json(OUTPUT_DIR / "manifest.json", manifest)
    write_json(OUTPUT_DIR / "render_summary.json", SUMMARY)
    write_esiti()
    log("==========================================")
    for layer in LAYERS:
        count = SUMMARY["frames"].get(layer, 0)
        if count:
            log(f"OK {layer} - frame {count} - animations/{layer}.webp")
    if SUMMARY["errors"]:
        log("Render completato con errori. Vedi ESITI_RENDER.txt")
    else:
        log("Render completato senza errori.")
    log("==========================================")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log("ERRORE FATALE")
        log(str(e))
        log(traceback.format_exc())
        raise
