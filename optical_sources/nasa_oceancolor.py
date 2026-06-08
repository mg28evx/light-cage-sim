import importlib.util
import math
import os
import re
from datetime import date, timedelta
from pathlib import Path

import numpy as np


COLLECTIONS = {
    "viirs": {
        "chl": ("VIIRSN_L3m_CHL", "*.L3m.DAY.CHL.chlor_a.4km.nc", "chlor_a"),
        "kd490": ("VIIRSN_L3m_KD", "*.L3m.DAY.KD.Kd_490.4km.nc", "Kd_490"),
        "cdom": ("VIIRSN_L3m_IOP", "*.L3m.DAY.IOP.adg_443.4km.nc", "adg_443"),
    },
    "pace": {
        "chl": ("PACE_OCI_L3M_CHL", "*.L3m.DAY.CHL.chlor_a.4km.nc", "chlor_a"),
        "kd490": ("PACE_OCI_L3M_KD", "*.L3m.DAY.KD.Kd_490.4km.nc", "Kd_490"),
        "cdom": ("PACE_OCI_L3M_IOP", "*.L3m.DAY.IOP.adg_443.4km.nc", "adg_443"),
    },
}

BASE_DIR = Path(__file__).resolve().parents[1]
CACHE_DIR = BASE_DIR / "data" / "optical_cache" / "nasa_oceancolor"
MAX_INTERACTIVE_DAYS = 14


def _credentials_present():
    if os.environ.get("EARTHDATA_TOKEN"):
        return True
    netrc_path = Path.home() / ".netrc"
    if not netrc_path.exists():
        return False
    try:
        return "urs.earthdata.nasa.gov" in netrc_path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return False


def source_status():
    configured = _credentials_present()
    return {
        "label": "NASA OceanColor",
        "available": importlib.util.find_spec("earthaccess") is not None,
        "configured": configured,
        "detail": (
            "VIIRS/PACE L3m diario 4 km: chlor_a, Kd_490 y adg_443; caché local."
            if configured
            else "Ejecutar earthaccess.login(persist=True) para descarga operacional."
        ),
    }


def _date_range(start_date, end_date):
    end = date.fromisoformat(end_date) if end_date else date.today() - timedelta(days=1)
    start = date.fromisoformat(start_date) if start_date else end - timedelta(days=6)
    was_clipped = False
    if (end - start).days + 1 > MAX_INTERACTIVE_DAYS:
        start = end - timedelta(days=MAX_INTERACTIVE_DAYS - 1)
        was_clipped = True
    return start, end, was_clipped


def _sensor_for_period(start):
    # PACE begins in 2024, but VIIRS provides the longer operational baseline.
    return "pace" if start >= date(2024, 4, 1) and os.environ.get("OPTICAL_NASA_SENSOR", "").lower() == "pace" else "viirs"


def _buffer_to_box(lat, lon, buffer_m):
    radius_m = max(float(buffer_m), 6000.0)
    lat_delta = radius_m / 111_320.0
    lon_delta = lat_delta / max(math.cos(math.radians(lat)), 0.2)
    return lon - lon_delta, lat - lat_delta, lon + lon_delta, lat + lat_delta


def _granule_date(granule):
    granule_name = granule.get("umm", {}).get("GranuleUR", "")
    match = re.search(r"\.(\d{8})\.L3m\.", granule_name)
    if not match:
        return None
    return date.fromisoformat(f"{match.group(1)[:4]}-{match.group(1)[4:6]}-{match.group(1)[6:8]}")


def _search_granules(short_name, pattern, start, end, bbox):
    import earthaccess

    results = earthaccess.search_data(
        short_name=short_name,
        temporal=(start.isoformat(), end.isoformat()),
        bounding_box=bbox,
        granule_name=pattern,
        count=MAX_INTERACTIVE_DAYS + 5,
    )
    by_day = {}
    for granule in results:
        day = _granule_date(granule)
        if day and start <= day <= end:
            by_day[day] = granule
    return by_day


def _spatial_median(path, variable, center, buffer_m):
    import xarray as xr

    lat_min, lat_max, lon_min, lon_max = _lat_lon_bounds(center, buffer_m)
    with xr.open_dataset(path) as ds:
        if variable not in ds:
            return None, 0
        data = ds[variable].sel(
            lat=slice(lat_max, lat_min),
            lon=slice(lon_min, lon_max),
        )
        values = np.asarray(data.values, dtype=float)
        values = values[np.isfinite(values)]
        if values.size == 0:
            return None, 0
        return float(np.median(values)), int(values.size)


def _lat_lon_bounds(center, buffer_m):
    lon_min, lat_min, lon_max, lat_max = _buffer_to_box(center.lat, center.lon, buffer_m)
    return lat_min, lat_max, lon_min, lon_max


def fetch_observations(center, start_date=None, end_date=None, buffer_m=1000):
    status = source_status()
    diagnostic = {
        "source": "nasa_oceancolor",
        "status": "skipped",
        "detail": status["detail"],
    }
    if not status["available"]:
        diagnostic["detail"] = "Paquete earthaccess no instalado."
        return {"observations": [], "diagnostic": diagnostic}
    if not status["configured"]:
        return {"observations": [], "diagnostic": diagnostic}
    if center.lat is None or center.lon is None:
        diagnostic["detail"] = "El centro no tiene coordenadas."
        return {"observations": [], "diagnostic": diagnostic}

    import earthaccess

    start, end, was_clipped = _date_range(start_date, end_date)
    sensor = _sensor_for_period(start)
    bbox = _buffer_to_box(center.lat, center.lon, buffer_m)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    try:
        auth = earthaccess.login(strategy="netrc")
        if not auth.authenticated:
            diagnostic["status"] = "error"
            diagnostic["detail"] = "Earthdata Login no autenticó la sesión."
            return {"observations": [], "diagnostic": diagnostic}

        observations_by_day = {}
        resolved_files = 0
        for key, target_key in (("chl", "chl"), ("kd490", "kd490"), ("cdom", "cdom_a440")):
            short_name, pattern, variable = COLLECTIONS[sensor][key]
            granules = _search_granules(short_name, pattern, start, end, bbox)
            paths = earthaccess.download(list(granules.values()), local_path=str(CACHE_DIR)) if granules else []
            resolved_files += len(paths)
            for day, path in zip(granules.keys(), paths):
                value, count = _spatial_median(path, variable, center, buffer_m)
                if value is None:
                    continue
                if variable == "adg_443":
                    value = value * math.exp(0.015 * 3.0)
                obs = observations_by_day.setdefault(day.isoformat(), {})
                obs[target_key] = value
                obs["n_valid_pixels"] = max(obs.get("n_valid_pixels", 0), count)

        observations = [
            {
                "center_id": center.center_id,
                "date": day,
                "source": f"nasa_oceancolor_{sensor}",
                "quality": "satellite_l3m",
                **values,
            }
            for day, values in sorted(observations_by_day.items())
        ]
        detail = f"NASA OceanColor {sensor.upper()} L3m consultado."
        if was_clipped:
            detail += f" Período limitado a {MAX_INTERACTIVE_DAYS} días."
        diagnostic.update({
            "status": "ok" if observations else "empty",
            "detail": detail,
            "n_observations": len(observations),
            "resolved_files": resolved_files,
            "resolution_km": 4,
            "uncertainty_note": "L3m no incluye incertidumbre porcentual por píxel en estos archivos.",
        })
        return {"observations": observations, "diagnostic": diagnostic}
    except Exception as exc:
        diagnostic["status"] = "error"
        diagnostic["detail"] = f"No se pudo consultar NASA OceanColor: {exc}"
        return {"observations": [], "diagnostic": diagnostic}
