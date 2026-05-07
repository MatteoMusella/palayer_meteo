<?php
/**
 * Meteo Interactive Player - Italia / ECMWF
 * Pagina PHP diretta, senza plugin WordPress.
 *
 * Richiede:
 * /wp-content/plugins/meteo/data/manifest.json
 * /wp-content/plugins/meteo/data/meteo_data.json
 */

$baseUrl = 'https://www.igest.eu/wp-content/plugins/meteo';
$dataUrl = $baseUrl . '/data';

$manifestUrl = $dataUrl . '/manifest.json';
$meteoDataUrl = $dataUrl . '/meteo_data.json';
?>
<!doctype html>
<html lang="it">
<head>
    <meta charset="utf-8">
    <title>Meteo Interattivo Italia - ECMWF</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">

    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/ol@10.4.0/ol.css">
    <script src="https://cdn.jsdelivr.net/npm/ol@10.4.0/dist/ol.js"></script>

    <style>
        html, body {
            margin: 0;
            padding: 0;
            width: 100%;
            height: 100%;
            background: #07111f;
            color: #fff;
            font-family: Arial, Helvetica, sans-serif;
            overflow: hidden;
        }

        #app {
            position: fixed;
            inset: 0;
            display: flex;
            flex-direction: column;
            background: #07111f;
        }

        #topbar {
            height: 74px;
            background: rgba(6, 15, 28, 0.94);
            border-bottom: 1px solid rgba(255,255,255,0.14);
            display: flex;
            align-items: center;
            gap: 10px;
            padding: 10px 14px;
            z-index: 50;
            box-sizing: border-box;
        }

        .brand {
            min-width: 270px;
            margin-right: auto;
        }

        .brand-title {
            font-size: 20px;
            font-weight: 900;
            line-height: 1.1;
        }

        .brand-subtitle {
            font-size: 12px;
            color: rgba(255,255,255,0.68);
            margin-top: 3px;
        }

        select, button, input[type="range"] {
            accent-color: #ffb300;
        }

        select, button {
            background: rgba(255,255,255,0.09);
            border: 1px solid rgba(255,255,255,0.18);
            color: #fff;
            border-radius: 10px;
            padding: 9px 11px;
            font-size: 14px;
            outline: none;
        }

        select option {
            background: #0b1728;
            color: #fff;
        }

        button {
            cursor: pointer;
            font-weight: 800;
        }

        button:hover {
            background: rgba(255,255,255,0.16);
        }

        .primary {
            background: #f5a400;
            color: #111;
            border-color: rgba(255,255,255,0.25);
        }

        .primary:hover {
            background: #ffb820;
        }

        #mapWrap {
            position: relative;
            flex: 1;
            min-height: 0;
        }

        #map {
            position: absolute;
            inset: 0;
            z-index: 1;
            background: #06111f;
        }

        #meteoCanvas {
            position: absolute;
            inset: 0;
            width: 100%;
            height: 100%;
            z-index: 5;
            pointer-events: none;
        }

        #hud {
            position: absolute;
            top: 16px;
            left: 50%;
            transform: translateX(-50%);
            background: rgba(0,0,0,0.66);
            border: 1px solid rgba(255,255,255,0.18);
            border-radius: 16px;
            padding: 10px 18px;
            z-index: 20;
            min-width: 330px;
            text-align: center;
            backdrop-filter: blur(8px);
            box-shadow: 0 10px 28px rgba(0,0,0,0.35);
        }

        #hudTime {
            font-size: 22px;
            font-weight: 900;
        }

        #hudLayer {
            font-size: 13px;
            color: rgba(255,255,255,0.75);
            margin-top: 2px;
        }

        #sidePanel {
            position: absolute;
            right: 14px;
            top: 16px;
            width: 330px;
            max-height: calc(100% - 32px);
            z-index: 22;
            background: rgba(6, 15, 28, 0.88);
            border: 1px solid rgba(255,255,255,0.16);
            border-radius: 18px;
            padding: 14px;
            overflow: auto;
            backdrop-filter: blur(8px);
            box-shadow: 0 14px 38px rgba(0,0,0,0.42);
        }

        .panel-title {
            font-weight: 900;
            font-size: 17px;
            margin-bottom: 10px;
        }

        .info-line {
            display: flex;
            justify-content: space-between;
            gap: 12px;
            padding: 7px 0;
            border-bottom: 1px solid rgba(255,255,255,0.08);
            font-size: 13px;
        }

        .info-line:last-child {
            border-bottom: 0;
        }

        .info-label {
            color: rgba(255,255,255,0.68);
        }

        .info-value {
            font-weight: 800;
            text-align: right;
        }

        #timeline {
            position: absolute;
            left: 14px;
            right: 14px;
            bottom: 14px;
            z-index: 24;
            background: rgba(6, 15, 28, 0.90);
            border: 1px solid rgba(255,255,255,0.16);
            border-radius: 18px;
            padding: 12px 14px;
            backdrop-filter: blur(8px);
            box-shadow: 0 12px 32px rgba(0,0,0,0.4);
        }

        #timeRange {
            width: 100%;
        }

        .timeline-row {
            display: flex;
            gap: 10px;
            align-items: center;
        }

        .timeline-label {
            min-width: 110px;
            font-size: 13px;
            color: rgba(255,255,255,0.75);
        }

        #popup {
            position: absolute;
            min-width: 280px;
            max-width: 370px;
            background: rgba(35, 35, 35, 0.96);
            color: #fff;
            border-radius: 10px;
            border: 1px solid rgba(255,255,255,0.25);
            box-shadow: 0 12px 34px rgba(0,0,0,0.45);
            z-index: 30;
            display: none;
            overflow: hidden;
        }

        .popup-head {
            background: rgba(255,255,255,0.08);
            padding: 9px 12px;
            font-weight: 900;
            display: flex;
            justify-content: space-between;
            gap: 10px;
        }

        .popup-body {
            padding: 10px 12px;
        }

        .popup-big {
            font-size: 28px;
            font-weight: 900;
            margin-bottom: 3px;
        }

        .popup-small {
            font-size: 12px;
            color: rgba(255,255,255,0.72);
        }

        .popup-table {
            margin-top: 8px;
        }

        .popup-row {
            display: flex;
            justify-content: space-between;
            gap: 12px;
            border-top: 1px solid rgba(255,255,255,0.08);
            padding: 6px 0;
            font-size: 13px;
        }

        .popup-row strong {
            text-align: right;
        }

        #loading {
            position: absolute;
            inset: 0;
            z-index: 100;
            background: rgba(7, 17, 31, 0.94);
            display: flex;
            align-items: center;
            justify-content: center;
            text-align: center;
            line-height: 1.5;
            padding: 20px;
        }

        .loading-box {
            max-width: 660px;
            background: rgba(255,255,255,0.06);
            border: 1px solid rgba(255,255,255,0.14);
            border-radius: 18px;
            padding: 24px;
        }

        .loading-title {
            font-size: 22px;
            font-weight: 900;
            margin-bottom: 8px;
        }

        .muted {
            color: rgba(255,255,255,0.68);
        }

        .ol-zoom {
            top: 92px;
            left: 12px;
        }

        .ol-control button {
            background: rgba(0,0,0,0.65) !important;
            color: #fff !important;
        }

        @media (max-width: 900px) {
            #topbar {
                height: auto;
                flex-wrap: wrap;
            }

            .brand {
                width: 100%;
            }

            #sidePanel {
                width: 275px;
                right: 8px;
                top: 8px;
            }

            #hud {
                top: 8px;
                min-width: 240px;
            }

            #hudTime {
                font-size: 17px;
            }
        }

        @media (max-width: 640px) {
            #sidePanel {
                display: none;
            }

            #hud {
                left: 8px;
                right: 8px;
                transform: none;
                min-width: 0;
            }

            .timeline-row {
                flex-wrap: wrap;
            }

            .timeline-label {
                width: 100%;
            }

            select {
                width: 100%;
            }
        }
    </style>
</head>
<body>

<div id="app">
    <div id="topbar">
        <div class="brand">
            <div class="brand-title">Meteo Interattivo Italia</div>
            <div class="brand-subtitle">ECMWF · Italia · vento a flussi animati</div>
        </div>

        <select id="layerSelect">
            <option value="wind">Vento + raffiche</option>
            <option value="gusts">Raffiche</option>
            <option value="precipitation">Pioggia</option>
            <option value="cloud_cover">Copertura nuvolosa</option>
            <option value="temperature">Temperatura</option>
            <option value="pressure">Pressione</option>
            <option value="wave_height">Onde</option>
        </select>

        <select id="speedSelect">
            <option value="0.5">Velocità 0.5x</option>
            <option value="1" selected>Velocità 1x</option>
            <option value="1.5">Velocità 1.5x</option>
            <option value="2">Velocità 2x</option>
            <option value="3">Velocità 3x</option>
        </select>

        <button id="playBtn" class="primary">Pausa</button>
        <button id="italiaBtn">Italia</button>
        <button id="focusBtn">Focus Ardea</button>
        <button id="reloadBtn">Ricarica</button>
    </div>

    <div id="mapWrap">
        <div id="map"></div>
        <canvas id="meteoCanvas"></canvas>

        <div id="hud">
            <div id="hudTime">Caricamento...</div>
            <div id="hudLayer">lettura dati meteo</div>
        </div>

        <div id="sidePanel">
            <div class="panel-title">Dati previsione</div>

            <div class="info-line">
                <span class="info-label">Run</span>
                <span class="info-value" id="infoRun">-</span>
            </div>

            <div class="info-line">
                <span class="info-label">Step</span>
                <span class="info-value" id="infoStep">-</span>
            </div>

            <div class="info-line">
                <span class="info-label">Layer</span>
                <span class="info-value" id="infoLayer">-</span>
            </div>

            <div class="info-line">
                <span class="info-label">Ardea</span>
                <span class="info-value" id="infoArdea">-</span>
            </div>

            <div class="info-line">
                <span class="info-label">Mare Ardea</span>
                <span class="info-value" id="infoSea">-</span>
            </div>

            <div class="info-line">
                <span class="info-label">Griglia</span>
                <span class="info-value" id="infoGrid">-</span>
            </div>

            <div style="margin-top:12px;font-size:12px;color:rgba(255,255,255,0.68);line-height:1.45;">
                Clicca sulla mappa per leggere vento, direzione, raffiche, temperatura, pioggia, pressione, nuvolosità e onde nel punto selezionato.
            </div>
        </div>

        <div id="popup">
            <div class="popup-head">
                <span id="popupTitle">Punto meteo</span>
                <span style="cursor:pointer" onclick="hidePopup()">×</span>
            </div>
            <div class="popup-body" id="popupBody"></div>
        </div>

        <div id="timeline">
            <div class="timeline-row">
                <div class="timeline-label" id="timeLabel">Timeline</div>
                <input type="range" id="timeRange" min="0" max="0" value="0">
            </div>
        </div>

        <div id="loading">
            <div class="loading-box">
                <div class="loading-title">Caricamento meteo interattivo</div>
                <div class="muted">
                    Lettura manifest e griglie ECMWF.<br>
                    Il primo caricamento può richiedere qualche secondo.
                </div>
                <div style="margin-top:12px;font-size:12px;" id="loadingDetail">
                    Inizializzazione...
                </div>
            </div>
        </div>
    </div>
</div>

<script>
const DATA_URL = "<?php echo $dataUrl; ?>";
const MANIFEST_URL = "<?php echo $manifestUrl; ?>";
const METEO_DATA_URL = "<?php echo $meteoDataUrl; ?>";

const ARDEA = [12.541, 41.612];
const ARDEA_SEA = [12.425, 41.585];

const LAYER_LABELS = {
    wind: "Vento + raffiche",
    gusts: "Raffiche",
    precipitation: "Pioggia",
    cloud_cover: "Copertura nuvolosa",
    temperature: "Temperatura",
    pressure: "Pressione",
    wave_height: "Onde"
};

let manifest = null;
let meteo = null;

let activeLayer = "wind";
let currentIndex = 0;
let playing = true;
let speed = 1;

let map = null;
let canvas = document.getElementById("meteoCanvas");
let ctx = canvas.getContext("2d", { alpha: true });

let particles = [];
let gustParticles = [];
let rainParticles = [];
let cloudParticles = [];
let waveParticles = [];

let lastTs = 0;
let fractional = 0;

const loading = document.getElementById("loading");
const loadingDetail = document.getElementById("loadingDetail");

const layerSelect = document.getElementById("layerSelect");
const speedSelect = document.getElementById("speedSelect");
const playBtn = document.getElementById("playBtn");
const focusBtn = document.getElementById("focusBtn");
const italiaBtn = document.getElementById("italiaBtn");
const reloadBtn = document.getElementById("reloadBtn");
const timeRange = document.getElementById("timeRange");

const hudTime = document.getElementById("hudTime");
const hudLayer = document.getElementById("hudLayer");

const infoRun = document.getElementById("infoRun");
const infoStep = document.getElementById("infoStep");
const infoLayer = document.getElementById("infoLayer");
const infoArdea = document.getElementById("infoArdea");
const infoSea = document.getElementById("infoSea");
const infoGrid = document.getElementById("infoGrid");

const popup = document.getElementById("popup");
const popupTitle = document.getElementById("popupTitle");
const popupBody = document.getElementById("popupBody");

function cacheBuster() {
    return "v=" + Date.now();
}

function setLoading(msg) {
    loadingDetail.textContent = msg;
}

function hideLoading() {
    loading.style.display = "none";
}

function showLoading() {
    loading.style.display = "flex";
}

function hidePopup() {
    popup.style.display = "none";
}

function fmt(num, digits = 1) {
    if (num === null || num === undefined || Number.isNaN(num)) return "-";
    return Number(num).toFixed(digits);
}

function clamp(v, min, max) {
    return Math.max(min, Math.min(max, v));
}

function lerp(a, b, t) {
    return a + (b - a) * t;
}

function lonLatToPixel(lon, lat) {
    return map.getPixelFromCoordinate(ol.proj.fromLonLat([lon, lat]));
}

function getStep(index) {
    if (!meteo || !meteo.steps || !meteo.steps.length) return null;
    return meteo.steps[clamp(index, 0, meteo.steps.length - 1)];
}

function getNextStep(index) {
    if (!meteo || !meteo.steps || !meteo.steps.length) return null;
    return meteo.steps[clamp(index + 1, 0, meteo.steps.length - 1)];
}

function findGridPosition(lon, lat) {
    const lats = meteo.grid.lats;
    const lons = meteo.grid.lons;

    const latMin = lats[0];
    const latMax = lats[lats.length - 1];
    const lonMin = lons[0];
    const lonMax = lons[lons.length - 1];

    const x = (lon - lonMin) / (lonMax - lonMin) * (lons.length - 1);
    const y = (lat - latMin) / (latMax - latMin) * (lats.length - 1);

    return { x, y };
}

function bilinear(grid, lon, lat) {
    if (!grid) return null;

    const lats = meteo.grid.lats;
    const lons = meteo.grid.lons;

    const pos = findGridPosition(lon, lat);
    const x = pos.x;
    const y = pos.y;

    if (x < 0 || y < 0 || x > lons.length - 1 || y > lats.length - 1) {
        return null;
    }

    const x0 = Math.floor(x);
    const x1 = Math.min(x0 + 1, lons.length - 1);
    const y0 = Math.floor(y);
    const y1 = Math.min(y0 + 1, lats.length - 1);

    const tx = x - x0;
    const ty = y - y0;

    const v00 = grid[y0][x0];
    const v10 = grid[y0][x1];
    const v01 = grid[y1][x0];
    const v11 = grid[y1][x1];

    if (v00 === null || v10 === null || v01 === null || v11 === null) {
        return null;
    }

    const a = lerp(v00, v10, tx);
    const b = lerp(v01, v11, tx);

    return lerp(a, b, ty);
}

function bilinearStep(step, field, lon, lat) {
    if (!step || !step.grid || !step.grid[field]) return null;
    return bilinear(step.grid[field], lon, lat);
}

function interpolatedValue(field, lon, lat) {
    const s0 = getStep(currentIndex);
    const s1 = getNextStep(currentIndex);

    const v0 = bilinearStep(s0, field, lon, lat);
    const v1 = bilinearStep(s1, field, lon, lat);

    if (v0 === null) return null;
    if (v1 === null) return v0;

    return lerp(v0, v1, fractional);
}

function windDirectionCardinal(deg) {
    if (deg === null || deg === undefined || Number.isNaN(deg)) return "-";
    const dirs = ["N","NNE","NE","ENE","E","ESE","SE","SSE","S","SSW","SW","WSW","W","WNW","NW","NNW"];
    const idx = Math.floor((deg + 11.25) / 22.5) % 16;
    return dirs[idx];
}

function directionText(deg) {
    if (deg === null || deg === undefined || Number.isNaN(deg)) return "-";
    return `${fmt(deg, 0)}° ${windDirectionCardinal(deg)}`;
}

function colorWind(v) {
    const t = clamp(v / 100, 0, 1);

    if (t < 0.15) return `rgba(40,120,255,0.62)`;
    if (t < 0.35) return `rgba(0,190,255,0.72)`;
    if (t < 0.55) return `rgba(70,220,150,0.80)`;
    if (t < 0.72) return `rgba(230,220,70,0.88)`;
    if (t < 0.88) return `rgba(255,145,45,0.94)`;
    return `rgba(255,70,70,1)`;
}

function colorGust(v) {
    const t = clamp(v / 130, 0, 1);

    if (t < 0.25) return `rgba(255,120,40,0.68)`;
    if (t < 0.50) return `rgba(255,70,70,0.82)`;
    if (t < 0.75) return `rgba(255,30,140,0.92)`;
    return `rgba(210,50,255,1)`;
}

function colorTemp(v) {
    if (v < 0) return "rgba(35,80,210,0.34)";
    if (v < 8) return "rgba(30,160,220,0.38)";
    if (v < 15) return "rgba(80,190,120,0.42)";
    if (v < 22) return "rgba(230,205,35,0.48)";
    if (v < 30) return "rgba(245,150,25,0.56)";
    return "rgba(220,50,45,0.64)";
}

function colorRain(v) {
    if (v === null || v < 0.1) return "rgba(0,0,0,0)";
    if (v < 1) return "rgba(120,230,255,0.22)";
    if (v < 4) return "rgba(35,170,255,0.36)";
    if (v < 10) return "rgba(0,80,230,0.50)";
    if (v < 20) return "rgba(120,40,180,0.64)";
    return "rgba(220,30,90,0.76)";
}

function colorCloud(v) {
    const a = clamp((v || 0) / 100 * 0.58, 0, 0.58);
    return `rgba(235,235,235,${a})`;
}

function colorPressure(v) {
    if (v < 1000) return "rgba(25,95,220,0.42)";
    if (v < 1008) return "rgba(80,170,240,0.36)";
    if (v < 1015) return "rgba(250,245,190,0.28)";
    if (v < 1022) return "rgba(245,160,70,0.38)";
    return "rgba(220,55,45,0.48)";
}

function colorWave(v) {
    if (v === null || v < 2) return "rgba(0,0,0,0)";
    if (v < 30) return "rgba(35,170,210,0.26)";
    if (v < 70) return "rgba(0,145,190,0.38)";
    if (v < 130) return "rgba(0,105,175,0.52)";
    return "rgba(210,245,255,0.68)";
}

function resizeCanvas() {
    const rect = canvas.parentElement.getBoundingClientRect();
    const dpr = window.devicePixelRatio || 1;

    canvas.width = Math.floor(rect.width * dpr);
    canvas.height = Math.floor(rect.height * dpr);

    canvas.style.width = rect.width + "px";
    canvas.style.height = rect.height + "px";

    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
}

function initMap() {
    map = new ol.Map({
        target: "map",
        layers: [
            new ol.layer.Tile({
                source: new ol.source.OSM(),
                opacity: 0.94
            })
        ],
        view: new ol.View({
            center: ol.proj.fromLonLat([12.4, 42.1]),
            zoom: 5.9,
            minZoom: 4,
            maxZoom: 14
        }),
        controls: ol.control.defaults.defaults({
            attribution: false
        }).extend([
            new ol.control.Zoom()
        ])
    });

    map.on("click", function(evt) {
        const lonlat = ol.proj.toLonLat(evt.coordinate);
        showPopupAt(evt.pixel, lonlat[0], lonlat[1]);
    });

    map.on("moveend", function() {
        resetParticles();
        drawScene(performance.now());
    });

    window.addEventListener("resize", function() {
        resizeCanvas();
        resetParticles();
        drawScene(performance.now());
    });

    resizeCanvas();
}

function resetParticles() {
    particles = [];
    gustParticles = [];
    rainParticles = [];
    cloudParticles = [];
    waveParticles = [];

    for (let i = 0; i < 1200; i++) particles.push(makeParticle());
    for (let i = 0; i < 500; i++) gustParticles.push(makeParticle());

    for (let i = 0; i < 480; i++) rainParticles.push(makeParticle());
    for (let i = 0; i < 380; i++) cloudParticles.push(makeParticle());
    for (let i = 0; i < 420; i++) waveParticles.push(makeParticle());
}

function randomLonLat() {
    const bbox = meteo.bbox;

    return {
        lon: bbox.west + Math.random() * (bbox.east - bbox.west),
        lat: bbox.south + Math.random() * (bbox.north - bbox.south)
    };
}

function makeParticle() {
    const p = randomLonLat();

    return {
        lon: p.lon,
        lat: p.lat,
        age: Math.floor(Math.random() * 120),
        trail: []
    };
}

function resetParticle(p) {
    const n = randomLonLat();
    p.lon = n.lon;
    p.lat = n.lat;
    p.age = 0;
    p.trail = [];
}

function stepParticle(p, dt, multiplier = 1) {
    const u = interpolatedValue("u10", p.lon, p.lat);
    const v = interpolatedValue("v10", p.lon, p.lat);
    const sp = interpolatedValue("wind_kmh", p.lon, p.lat);

    if (u === null || v === null || sp === null) {
        resetParticle(p);
        return 0;
    }

    p.trail.unshift([p.lon, p.lat]);
    if (p.trail.length > 14) p.trail.pop();

    const moveScale = 0.000028 * dt * multiplier;

    p.lon += u * moveScale / Math.max(0.45, Math.cos(p.lat * Math.PI / 180));
    p.lat += v * moveScale;

    p.age++;

    const bbox = meteo.bbox;
    if (
        p.lon < bbox.west ||
        p.lon > bbox.east ||
        p.lat < bbox.south ||
        p.lat > bbox.north ||
        p.age > 160
    ) {
        resetParticle(p);
    }

    return sp;
}

function drawScalarField(fieldName, colorFn, options = {}) {
    const lats = meteo.grid.lats;
    const lons = meteo.grid.lons;

    const step0 = getStep(currentIndex);
    const step1 = getNextStep(currentIndex);

    if (!step0 || !step0.grid[fieldName]) return;

    const alpha = options.alpha ?? 0.45;
    const stride = options.stride ?? 2;

    ctx.save();
    ctx.globalAlpha = alpha;

    for (let yi = 0; yi < lats.length - 1; yi += stride) {
        for (let xi = 0; xi < lons.length - 1; xi += stride) {
            const lonA = lons[xi];
            const lonB = lons[Math.min(xi + stride, lons.length - 1)];
            const latA = lats[yi];
            const latB = lats[Math.min(yi + stride, lats.length - 1)];

            const lonC = (lonA + lonB) / 2;
            const latC = (latA + latB) / 2;

            let v0 = bilinearStep(step0, fieldName, lonC, latC);
            let v1 = bilinearStep(step1, fieldName, lonC, latC);

            if (v0 === null) continue;
            if (v1 === null) v1 = v0;

            const val = lerp(v0, v1, fractional);

            const p1 = lonLatToPixel(lonA, latA);
            const p2 = lonLatToPixel(lonB, latB);

            if (!p1 || !p2) continue;

            ctx.fillStyle = colorFn(val);

            const x = Math.min(p1[0], p2[0]);
            const y = Math.min(p1[1], p2[1]);
            const w = Math.abs(p2[0] - p1[0]) + 2;
            const h = Math.abs(p2[1] - p1[1]) + 2;

            ctx.fillRect(x, y, w, h);
        }
    }

    ctx.restore();
}

function drawWindLayer() {
    drawScalarField("wind_kmh", colorWind, {
        alpha: 0.16,
        stride: 3
    });

    drawWindParticles(false);
    drawWindParticles(true);
}

function drawGustLayer() {
    drawScalarField("gust_kmh", colorGust, {
        alpha: 0.14,
        stride: 3
    });

    drawWindParticles(true);
}

function drawWindParticles(gustMode) {
    const arr = gustMode ? gustParticles : particles;

    ctx.save();
    ctx.lineCap = "round";
    ctx.lineJoin = "round";

    for (const p of arr) {
        const sp = stepParticle(p, 1.7, gustMode ? 1.7 : 1.0);

        if (sp < (gustMode ? 10 : 3)) continue;

        const trail = p.trail;

        for (let i = 0; i < trail.length - 1; i++) {
            const a = lonLatToPixel(trail[i][0], trail[i][1]);
            const b = lonLatToPixel(trail[i + 1][0], trail[i + 1][1]);

            if (!a || !b) continue;

            const fade = 1 - i / trail.length;
            const opacity = fade * (gustMode ? 0.90 : 0.68);

            ctx.globalAlpha = opacity;
            ctx.strokeStyle = gustMode ? colorGust(sp) : colorWind(sp);
            ctx.lineWidth = gustMode
                ? clamp(1.4 + sp / 45, 1.4, 4.8)
                : clamp(0.9 + sp / 70, 0.9, 2.8);

            ctx.beginPath();
            ctx.moveTo(a[0], a[1]);
            ctx.lineTo(b[0], b[1]);
            ctx.stroke();
        }

        if (trail.length >= 2) {
            const h1 = lonLatToPixel(trail[0][0], trail[0][1]);
            const h2 = lonLatToPixel(trail[1][0], trail[1][1]);

            if (h1 && h2) {
                const dx = h1[0] - h2[0];
                const dy = h1[1] - h2[1];
                const ang = Math.atan2(dy, dx);
                const len = gustMode ? 5 : 4;

                ctx.globalAlpha = gustMode ? 0.95 : 0.78;
                ctx.strokeStyle = gustMode ? colorGust(sp) : colorWind(sp);
                ctx.lineWidth = gustMode ? 1.8 : 1.2;

                ctx.beginPath();
                ctx.moveTo(h1[0], h1[1]);
                ctx.lineTo(
                    h1[0] - len * Math.cos(ang - Math.PI / 6),
                    h1[1] - len * Math.sin(ang - Math.PI / 6)
                );
                ctx.moveTo(h1[0], h1[1]);
                ctx.lineTo(
                    h1[0] - len * Math.cos(ang + Math.PI / 6),
                    h1[1] - len * Math.sin(ang + Math.PI / 6)
                );
                ctx.stroke();
            }
        }
    }

    ctx.restore();
}

function drawTemperature() {
    drawScalarField("temperature_c", colorTemp, {
        alpha: 0.55,
        stride: 2
    });

    drawSoftFlow(130, "rgba(255,255,255,0.14)", 0.006);
}

function drawPressure() {
    drawScalarField("pressure_hpa", colorPressure, {
        alpha: 0.55,
        stride: 2
    });

    drawSoftFlow(150, "rgba(255,255,255,0.18)", 0.005);
}

function drawRain() {
    drawScalarField("precipitation_mm", colorRain, {
        alpha: 0.72,
        stride: 2
    });

    ctx.save();

    for (const p of rainParticles) {
        const rain = interpolatedValue("precipitation_mm", p.lon, p.lat);

        if (rain === null || rain < 0.08) {
            stepParticle(p, 1.7, 0.75);
            continue;
        }

        stepParticle(p, 2.1, 0.95);

        const pix = lonLatToPixel(p.lon, p.lat);
        if (!pix) continue;

        const len = clamp(6 + rain * 1.9, 6, 28);
        const opacity = clamp(rain / 10, 0.14, 0.70);

        ctx.globalAlpha = opacity;
        ctx.strokeStyle = `rgba(220,245,255,${opacity})`;
        ctx.lineWidth = clamp(0.8 + rain / 4, 0.8, 2.6);

        ctx.beginPath();
        ctx.moveTo(pix[0], pix[1]);
        ctx.lineTo(pix[0] - len * 0.35, pix[1] + len);
        ctx.stroke();
    }

    ctx.restore();
}

function drawClouds() {
    drawScalarField("cloud_cover_pct", colorCloud, {
        alpha: 0.72,
        stride: 2
    });

    ctx.save();
    ctx.globalCompositeOperation = "screen";

    for (const p of cloudParticles) {
        const cloud = interpolatedValue("cloud_cover_pct", p.lon, p.lat);

        if (cloud === null || cloud < 8) {
            stepParticle(p, 1.1, 0.30);
            continue;
        }

        stepParticle(p, 1.0, 0.26);

        const pix = lonLatToPixel(p.lon, p.lat);
        if (!pix) continue;

        const r = clamp(8 + cloud * 0.18, 8, 34);
        const g = ctx.createRadialGradient(pix[0], pix[1], 0, pix[0], pix[1], r);

        g.addColorStop(0, `rgba(255,255,255,${clamp(cloud / 220, 0.04, 0.22)})`);
        g.addColorStop(0.6, `rgba(240,240,240,${clamp(cloud / 320, 0.02, 0.12)})`);
        g.addColorStop(1, "rgba(255,255,255,0)");

        ctx.fillStyle = g;
        ctx.beginPath();
        ctx.arc(pix[0], pix[1], r, 0, Math.PI * 2);
        ctx.fill();
    }

    ctx.restore();
}

function drawWaves() {
    drawScalarField("wave_height_cm", colorWave, {
        alpha: 0.64,
        stride: 2
    });

    ctx.save();

    for (const p of waveParticles) {
        const wave = interpolatedValue("wave_height_cm", p.lon, p.lat);

        if (wave === null || wave < 2) {
            stepParticle(p, 1.2, 0.25);
            continue;
        }

        stepParticle(p, 1.2, 0.32);

        const pix = lonLatToPixel(p.lon, p.lat);
        if (!pix) continue;

        const len = clamp(8 + wave / 8, 8, 28);

        ctx.globalAlpha = clamp(wave / 180, 0.18, 0.72);
        ctx.strokeStyle = "rgba(235,250,255,0.75)";
        ctx.lineWidth = clamp(0.8 + wave / 90, 0.8, 2.3);

        ctx.beginPath();
        ctx.moveTo(pix[0] - len / 2, pix[1]);
        ctx.quadraticCurveTo(pix[0], pix[1] - len / 4, pix[0] + len / 2, pix[1]);
        ctx.stroke();
    }

    ctx.restore();
}

function drawSoftFlow(count, color, scale = 0.006) {
    ctx.save();
    ctx.strokeStyle = color;
    ctx.lineWidth = 1.1;
    ctx.globalAlpha = 0.30;

    const bbox = meteo.bbox;

    for (let i = 0; i < count; i++) {
        const lon = bbox.west + Math.random() * (bbox.east - bbox.west);
        const lat = bbox.south + Math.random() * (bbox.north - bbox.south);

        const u = interpolatedValue("u10", lon, lat);
        const v = interpolatedValue("v10", lon, lat);

        if (u === null || v === null) continue;

        const p1 = lonLatToPixel(lon, lat);
        const p2 = lonLatToPixel(lon + u * scale, lat + v * scale);

        if (!p1 || !p2) continue;

        ctx.beginPath();
        ctx.moveTo(p1[0], p1[1]);
        ctx.lineTo(p2[0], p2[1]);
        ctx.stroke();
    }

    ctx.restore();
}

function drawScene(ts) {
    if (!meteo || !map) return;

    const rect = canvas.parentElement.getBoundingClientRect();
    ctx.clearRect(0, 0, rect.width, rect.height);

    const dt = lastTs ? (ts - lastTs) / 16.67 : 1;
    lastTs = ts;

    if (playing) {
        fractional += 0.0065 * speed * dt;

        if (fractional >= 1) {
            fractional = 0;
            currentIndex++;

            if (currentIndex >= meteo.steps.length - 1) {
                currentIndex = 0;
            }

            timeRange.value = currentIndex;
        }
    }

    if (activeLayer === "wind") drawWindLayer();
    if (activeLayer === "gusts") drawGustLayer();
    if (activeLayer === "precipitation") drawRain();
    if (activeLayer === "cloud_cover") drawClouds();
    if (activeLayer === "temperature") drawTemperature();
    if (activeLayer === "pressure") drawPressure();
    if (activeLayer === "wave_height") drawWaves();

    updateHud();

    requestAnimationFrame(drawScene);
}

function updateHud() {
    const step = getStep(currentIndex);
    if (!step) return;

    const label = step.valid_label || `H+${String(step.step).padStart(3, "0")}`;

    hudTime.textContent = `${label}`;
    hudLayer.textContent = `${LAYER_LABELS[activeLayer]} · H+${String(step.step).padStart(3, "0")}`;

    infoStep.textContent = `H+${String(step.step).padStart(3, "0")}`;
    infoLayer.textContent = LAYER_LABELS[activeLayer];

    const ardea = sampleAllAt(ARDEA[0], ARDEA[1]);
    const sea = sampleAllAt(ARDEA_SEA[0], ARDEA_SEA[1]);

    infoArdea.textContent = `${fmt(ardea.temperature_c, 1)} °C · vento ${fmt(ardea.wind_kmh, 1)} km/h`;
    infoSea.textContent = `onda ${fmt(sea.wave_height_cm, 0)} cm · vento ${fmt(sea.wind_kmh, 1)} km/h`;
}

function sampleAllAt(lon, lat) {
    const wind = interpolatedValue("wind_kmh", lon, lat);
    const dir = interpolatedValue("wind_dir_deg", lon, lat);
    const gust = interpolatedValue("gust_kmh", lon, lat);
    const temp = interpolatedValue("temperature_c", lon, lat);
    const rain = interpolatedValue("precipitation_mm", lon, lat);
    const cloud = interpolatedValue("cloud_cover_pct", lon, lat);
    const pressure = interpolatedValue("pressure_hpa", lon, lat);
    const wave = interpolatedValue("wave_height_cm", lon, lat);

    return {
        wind_kmh: wind,
        wind_dir_deg: dir,
        wind_dir_cardinal: dir !== null ? windDirectionCardinal(dir) : "-",
        gust_kmh: gust,
        temperature_c: temp,
        precipitation_mm: rain,
        cloud_cover_pct: cloud,
        pressure_hpa: pressure,
        wave_height_cm: wave
    };
}

function showPopupAt(pixel, lon, lat) {
    const d = sampleAllAt(lon, lat);
    const step = getStep(currentIndex);

    popupTitle.textContent = `Punto meteo`;

    let big = "";
    let sub = "";

    if (activeLayer === "wind") {
        big = `${fmt(d.wind_kmh, 1)} km/h`;
        sub = `Vento da ${directionText(d.wind_dir_deg)} · raffica ${fmt(d.gust_kmh, 1)} km/h`;
    } else if (activeLayer === "gusts") {
        big = `${fmt(d.gust_kmh, 1)} km/h`;
        sub = `Raffica · vento medio ${fmt(d.wind_kmh, 1)} km/h`;
    } else if (activeLayer === "temperature") {
        big = `${fmt(d.temperature_c, 1)} °C`;
        sub = `Temperatura a 2 metri`;
    } else if (activeLayer === "precipitation") {
        big = `${fmt(d.precipitation_mm, 2)} mm`;
        sub = `Pioggia nello step`;
    } else if (activeLayer === "cloud_cover") {
        big = `${fmt(d.cloud_cover_pct, 0)} %`;
        sub = `Copertura nuvolosa`;
    } else if (activeLayer === "pressure") {
        big = `${fmt(d.pressure_hpa, 1)} hPa`;
        sub = `Pressione al livello del mare`;
    } else if (activeLayer === "wave_height") {
        big = `${fmt(d.wave_height_cm, 0)} cm`;
        sub = `Altezza onde`;
    }

    popupBody.innerHTML = `
        <div class="popup-big">${big}</div>
        <div class="popup-small">${sub}</div>

        <div class="popup-table">
            <div class="popup-row"><span>Coordinate</span><strong>${fmt(lat, 4)}, ${fmt(lon, 4)}</strong></div>
            <div class="popup-row"><span>Validità</span><strong>${step ? step.valid_label : "-"}</strong></div>
            <div class="popup-row"><span>Vento</span><strong>${fmt(d.wind_kmh, 1)} km/h da ${directionText(d.wind_dir_deg)}</strong></div>
            <div class="popup-row"><span>Raffica</span><strong>${fmt(d.gust_kmh, 1)} km/h</strong></div>
            <div class="popup-row"><span>Temperatura</span><strong>${fmt(d.temperature_c, 1)} °C</strong></div>
            <div class="popup-row"><span>Pioggia</span><strong>${fmt(d.precipitation_mm, 2)} mm</strong></div>
            <div class="popup-row"><span>Nuvole</span><strong>${fmt(d.cloud_cover_pct, 0)} %</strong></div>
            <div class="popup-row"><span>Pressione</span><strong>${fmt(d.pressure_hpa, 1)} hPa</strong></div>
            <div class="popup-row"><span>Onde</span><strong>${fmt(d.wave_height_cm, 0)} cm</strong></div>
        </div>
    `;

    popup.style.left = Math.min(pixel[0] + 16, window.innerWidth - 390) + "px";
    popup.style.top = Math.max(90, pixel[1] + 16) + "px";
    popup.style.display = "block";
}

async function loadData() {
    showLoading();

    setLoading("Carico manifest...");
    const manifestResponse = await fetch(`${MANIFEST_URL}?${cacheBuster()}`);

    if (!manifestResponse.ok) {
        throw new Error(`Manifest non leggibile: HTTP ${manifestResponse.status}`);
    }

    manifest = await manifestResponse.json();

    setLoading("Carico meteo_data.json...");
    const dataResponse = await fetch(`${METEO_DATA_URL}?${cacheBuster()}`);

    if (!dataResponse.ok) {
        throw new Error(`meteo_data.json non leggibile: HTTP ${dataResponse.status}`);
    }

    meteo = await dataResponse.json();

    setLoading("Inizializzo mappa e animazioni...");

    timeRange.max = Math.max(0, meteo.steps.length - 1);
    timeRange.value = 0;

    infoRun.textContent = `${manifest.run.date} ${String(manifest.run.hour_utc).padStart(2, "0")} UTC`;
    infoGrid.textContent = `${meteo.grid.lats.length} × ${meteo.grid.lons.length}`;

    initMap();
    resetParticles();

    hideLoading();

    requestAnimationFrame(drawScene);
}

layerSelect.addEventListener("change", function() {
    activeLayer = layerSelect.value;
    hidePopup();
});

speedSelect.addEventListener("change", function() {
    speed = parseFloat(speedSelect.value) || 1;
});

playBtn.addEventListener("click", function() {
    playing = !playing;
    playBtn.textContent = playing ? "Pausa" : "Play";
});

italiaBtn.addEventListener("click", function() {
    map.getView().animate({
        center: ol.proj.fromLonLat([12.4, 42.1]),
        zoom: 5.9,
        duration: 650
    });
});

focusBtn.addEventListener("click", function() {
    map.getView().animate({
        center: ol.proj.fromLonLat(ARDEA),
        zoom: 10.5,
        duration: 650
    });
});

reloadBtn.addEventListener("click", function() {
    window.location.reload();
});

timeRange.addEventListener("input", function() {
    currentIndex = parseInt(timeRange.value, 10) || 0;
    fractional = 0;
    hidePopup();
    updateHud();
});

loadData().catch(err => {
    console.error(err);
    setLoading("Errore: " + err.message);
});
</script>

</body>
</html>