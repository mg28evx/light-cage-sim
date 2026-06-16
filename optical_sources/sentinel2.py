import csv
import importlib.util
import math
import os
import re
import shlex
import subprocess
from datetime import date, timedelta
from pathlib import Path
from statistics import median

import numpy as np


BASE_DIR = Path(__file__).resolve().parents[1]
DEFAULT_ACOLITE_OUTPUT_DIR = BASE_DIR / "data" / "optical_cache" / "sentinel2_acolite"
RELONCAVI_NV09_RMSE_FNU = 0.66


def _clean_float(value):
    if value is None:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _date_range(start_date, end_date):
    end = date.fromisoformat(end_date) if end_date else date.today()
    start = date.fromisoformat(start_date) if start_date else end - timedelta(days=90)
    return start, end


def _buffer_to_box(lat, lon, buffer_m):
    radius_m = max(float(buffer_m), 100.0)
    lat_delta = radius_m / 111_320.0
    lon_delta = lat_delta / max(math.cos(math.radians(lat)), 0.2)
    return lat - lat_delta, lat + lat_delta, lon - lon_delta, lon + lon_delta


def _output_dir():
    return Path(os.environ.get("SENTINEL2_ACOLITE_OUTPUT_DIR", DEFAULT_ACOLITE_OUTPUT_DIR))


def _nechad_coefficients():
    """Return optional Nechad coefficients.

    ACOLITE can already output turbidity products. If only water reflectance is
    available, this connector applies Nechad's form only when coefficients are
    configured, avoiding a hidden universal calibration.
    """
    a_t = _clean_float(os.environ.get("SENTINEL2_NECHAD_AT"))
    b_t = _clean_float(os.environ.get("SENTINEL2_NECHAD_BT"))
    c_t = _clean_float(os.environ.get("SENTINEL2_NECHAD_C"))
    if a_t is None or c_t is None:
        return None
    return {"AT": a_t, "BT": b_t or 0.0, "C": c_t}


def _nechad_turbidity(rhow, coefficients):
    if coefficients is None or rhow is None:
        return None
    if rhow <= 0 or rhow >= coefficients["C"]:
        return None
    return coefficients["AT"] * rhow / (1.0 - rhow / coefficients["C"]) + coefficients["BT"]


def _has_acolite_products(output_dir):
    if not output_dir.exists():
        return False
    return any(output_dir.rglob("*.nc")) or any(output_dir.rglob("*.csv"))


def source_status():
    output_dir = _output_dir()
    command_template = os.environ.get("ACOLITE_CMD_TEMPLATE", "")
    coefficients = _nechad_coefficients()
    has_products = _has_acolite_products(output_dir)
    return {
        "label": "Sentinel-2 / ACOLITE",
        "available": importlib.util.find_spec("xarray") is not None or has_products or bool(command_template),
        "configured": has_products or bool(command_template),
        "detail": (
            "Lee salidas ACOLITE DSF/Nechad desde "
            f"{output_dir}. "
            "Si solo existe rhow_665, configure SENTINEL2_NECHAD_AT y SENTINEL2_NECHAD_C "
            "para calcular turbidez FNU."
        ),
        "acolite_output_dir": str(output_dir),
        "acolite_products_found": has_products,
        "acolite_command_configured": bool(command_template),
        "nechad_coefficients_configured": coefficients is not None,
    }


def _date_from_path(path):
    match = re.search(r"(20\d{6})", path.name)
    if not match:
        return None
    raw = match.group(1)
    try:
        return date.fromisoformat(f"{raw[:4]}-{raw[4:6]}-{raw[6:8]}")
    except ValueError:
        return None


def _collect_files(output_dir, start, end):
    if not output_dir.exists():
        return []
    candidates = []
    for pattern in ("*.nc", "*.csv"):
        for path in output_dir.rglob(pattern):
            day = _date_from_path(path)
            if day is None or start <= day <= end:
                candidates.append(path)
    return sorted(candidates)


def _median(values):
    clean = sorted(v for v in values if v is not None and math.isfinite(v))
    return median(clean) if clean else None


def _box_filter(lat, lon, lat_min, lat_max, lon_min, lon_max):
    return lat is not None and lon is not None and lat_min <= lat <= lat_max and lon_min <= lon <= lon_max


def _extract_csv(path, center, buffer_m, coefficients):
    lat_min, lat_max, lon_min, lon_max = _buffer_to_box(center.lat, center.lon, buffer_m)
    rows = []
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            lat = _clean_float(row.get("lat") or row.get("latitude"))
            lon = _clean_float(row.get("lon") or row.get("longitude"))
            if lat is not None and lon is not None and not _box_filter(lat, lon, lat_min, lat_max, lon_min, lon_max):
                continue
            rows.append(row)
    if not rows:
        return None

    turbidity_values = []
    rhow_values = []
    for row in rows:
        turbidity = _clean_float(row.get("turbidity_fnu") or row.get("turbidity") or row.get("tur_nechad665"))
        rhow = _clean_float(row.get("rhow_665") or row.get("rho_w_665") or row.get("rhos_665"))
        if turbidity is None:
            turbidity = _nechad_turbidity(rhow, coefficients)
        if turbidity is not None:
            turbidity_values.append(turbidity)
        if rhow is not None:
            rhow_values.append(rhow)

    return _observation_from_values(path, center, turbidity_values, rhow_values, len(rows), coefficients)


def _first_existing(ds, names):
    for name in names:
        if name in ds:
            return name
    lowered = {name.lower(): name for name in ds.variables}
    for name in names:
        if name.lower() in lowered:
            return lowered[name.lower()]
    return None


def _variable_by_hint(ds, hints):
    for name in ds.data_vars:
        lowered = name.lower()
        if all(hint in lowered for hint in hints):
            return name
    return None


def _masked_values(ds, variable, center, buffer_m):
    lat_name = _first_existing(ds, ("lat", "latitude"))
    lon_name = _first_existing(ds, ("lon", "longitude"))
    if lat_name is None or lon_name is None or variable is None:
        return np.array([], dtype=float)

    lat_min, lat_max, lon_min, lon_max = _buffer_to_box(center.lat, center.lon, buffer_m)
    data = ds[variable]
    lat = ds[lat_name]
    lon = ds[lon_name]

    mask = (lat >= lat_min) & (lat <= lat_max) & (lon >= lon_min) & (lon <= lon_max)
    values = np.asarray(data.where(mask).values, dtype=float)

    values = values[np.isfinite(values)]
    return values[values >= 0]


def _extract_netcdf(path, center, buffer_m, coefficients):
    import xarray as xr

    with xr.open_dataset(path) as ds:
        turbidity_var = (
            _first_existing(ds, ("turbidity_fnu", "turbidity", "tur_nechad665", "tur_nechad_665"))
            or _variable_by_hint(ds, ("turb",))
            or _variable_by_hint(ds, ("nechad",))
        )
        rhow_var = (
            _first_existing(ds, ("rhow_665", "rho_w_665", "rhos_665", "rhow_B4", "rhos_B4"))
            or _variable_by_hint(ds, ("rhow", "665"))
            or _variable_by_hint(ds, ("rhos", "665"))
        )
        turbidity_values = _masked_values(ds, turbidity_var, center, buffer_m)
        rhow_values = _masked_values(ds, rhow_var, center, buffer_m)

    if turbidity_values.size == 0 and rhow_values.size and coefficients:
        turbidity_values = np.array([
            value
            for value in (_nechad_turbidity(float(rhow), coefficients) for rhow in rhow_values)
            if value is not None
        ])

    n_valid = int(max(turbidity_values.size, rhow_values.size))
    return _observation_from_values(path, center, turbidity_values, rhow_values, n_valid, coefficients)


def _observation_from_values(path, center, turbidity_values, rhow_values, n_valid, coefficients):
    turbidity = _median(np.asarray(turbidity_values, dtype=float).tolist()) if len(turbidity_values) else None
    rhow = _median(np.asarray(rhow_values, dtype=float).tolist()) if len(rhow_values) else None
    if turbidity is None and rhow is None:
        return None

    day = _date_from_path(path)
    return {
        "center_id": center.center_id,
        "date": day.isoformat() if day else "",
        "source": "sentinel2_acolite",
        "quality": "acolite_dsf_nechad",
        "turbidity_fnu": turbidity,
        "turbidity_algorithm": "ACOLITE/Nechad 665 nm" if turbidity is not None else "",
        "turbidity_uncertainty_fnu": RELONCAVI_NV09_RMSE_FNU if turbidity is not None else None,
        "rhow_665": rhow,
        "n_valid_pixels": n_valid,
        "tss": None,
        "tss_is_proxy": turbidity is not None,
        "tss_proxy_source": "sentinel2_acolite_turbidity_fnu" if turbidity is not None else "",
        "tss_conversion": None,
        "meta": {
            "file": str(path),
            "nechad_coefficients": coefficients,
        },
    }


def _run_acolite_if_configured(center, start_date, end_date, buffer_m, output_dir):
    template = os.environ.get("ACOLITE_CMD_TEMPLATE")
    if not template:
        return None
    rendered = template.format(
        lat=center.lat,
        lon=center.lon,
        center_id=center.center_id,
        start_date=start_date or "",
        end_date=end_date or "",
        buffer_m=buffer_m,
        output_dir=str(output_dir),
    )
    timeout = int(os.environ.get("ACOLITE_TIMEOUT_SECONDS", "1800"))
    result = subprocess.run(
        shlex.split(rendered),
        cwd=str(BASE_DIR),
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    return {
        "returncode": result.returncode,
        "stdout": result.stdout[-1000:],
        "stderr": result.stderr[-1000:],
    }


def fetch_observations(center, start_date=None, end_date=None, buffer_m=1000):
    status = source_status()
    diagnostic = {
        "source": "sentinel2",
        "status": "skipped",
        "detail": status["detail"],
    }
    if center.lat is None or center.lon is None:
        diagnostic["detail"] = "El centro no tiene coordenadas."
        return {"observations": [], "diagnostic": diagnostic}

    output_dir = _output_dir()
    output_dir.mkdir(parents=True, exist_ok=True)
    start, end = _date_range(start_date, end_date)
    coefficients = _nechad_coefficients()

    run_result = None
    try:
        run_result = _run_acolite_if_configured(center, start_date, end_date, buffer_m, output_dir)
        if run_result and run_result["returncode"] != 0:
            diagnostic.update({
                "status": "error",
                "detail": "ACOLITE_CMD_TEMPLATE terminó con error.",
                "acolite_run": run_result,
            })
            return {"observations": [], "diagnostic": diagnostic}

        observations = []
        errors = []
        for path in _collect_files(output_dir, start, end):
            try:
                if path.suffix.lower() == ".csv":
                    observation = _extract_csv(path, center, buffer_m, coefficients)
                else:
                    observation = _extract_netcdf(path, center, buffer_m, coefficients)
                if observation:
                    observations.append(observation)
            except Exception as exc:
                errors.append(f"{path.name}: {exc}")

        diagnostic.update({
            "status": "ok" if observations else "empty",
            "detail": (
                "Salidas ACOLITE leídas correctamente."
                if observations
                else "No se encontraron salidas ACOLITE con turbidez/rhow válida para el sitio/período."
            ),
            "n_observations": len(observations),
            "acolite_output_dir": str(output_dir),
            "acolite_run": run_result,
            "nechad_coefficients_configured": coefficients is not None,
        })
        if errors:
            diagnostic["warnings"] = errors[:5]
        return {"observations": observations, "diagnostic": diagnostic}
    except Exception as exc:
        diagnostic["status"] = "error"
        diagnostic["detail"] = f"No se pudo procesar Sentinel-2/ACOLITE: {exc}"
        diagnostic["acolite_run"] = run_result
        return {"observations": [], "diagnostic": diagnostic}
