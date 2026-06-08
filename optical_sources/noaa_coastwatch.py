import csv
import io
import math
from datetime import date, timedelta
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import urlopen


ERDDAP_BASE = "https://coastwatch.noaa.gov/erddap/griddap"
DATASETS = {
    "chl": ("noaacwNPPN20S3ASCIDINEOFDaily", "chlor_a"),
    "kd490": ("noaacwNPPN20S3AkdSCIDINEOFDaily", "kd_490"),
}


def source_status():
    return {
        "label": "NOAA CoastWatch ERDDAP",
        "available": True,
        "configured": True,
        "detail": "Público sin credenciales; descarga DINEOF global diario chlor_a y kd_490.",
    }


def _date_range(start_date, end_date):
    if end_date:
        end = date.fromisoformat(end_date)
    else:
        end = date.today()
    if start_date:
        start = date.fromisoformat(start_date)
    else:
        start = end - timedelta(days=90)
    return f"{start.isoformat()}T12:00:00Z", f"{end.isoformat()}T12:00:00Z"


def _buffer_to_box(lat, lon, buffer_m):
    lat_delta = max(float(buffer_m), 100.0) / 111_320.0
    lon_delta = lat_delta / max(math.cos(math.radians(lat)), 0.2)
    return lat - lat_delta, lat + lat_delta, lon - lon_delta, lon + lon_delta


def _build_url(dataset_id, variable, lat, lon, start_date, end_date, buffer_m):
    lat_min, lat_max, lon_min, lon_max = _buffer_to_box(lat, lon, buffer_m)
    start, end = _date_range(start_date, end_date)
    query = (
        f"{variable}"
        f"[({end}):({start})]"
        "[(0.0):(0.0)]"
        f"[({lat_max:.6f}):({lat_min:.6f})]"
        f"[({lon_min:.6f}):({lon_max:.6f})]"
    )
    return f"{ERDDAP_BASE}/{dataset_id}.csv?{quote(query, safe='(),:[]')}"


def _fetch_variable(dataset_id, variable, center, start_date, end_date, buffer_m, timeout=25):
    if center.lat is None or center.lon is None:
        return []

    url = _build_url(dataset_id, variable, center.lat, center.lon, start_date, end_date, buffer_m)
    with urlopen(url, timeout=timeout) as response:
        text = response.read().decode("utf-8", errors="replace")

    rows = list(csv.reader(io.StringIO(text)))
    if len(rows) < 3:
        return []

    header = rows[0]
    try:
        time_idx = header.index("time")
        value_idx = header.index(variable)
    except ValueError:
        return []

    values_by_date = {}
    for row in rows[2:]:
        if len(row) <= value_idx:
            continue
        try:
            value = float(row[value_idx])
        except (TypeError, ValueError):
            continue
        if not math.isfinite(value) or value < 0:
            continue
        day = row[time_idx][:10]
        values_by_date.setdefault(day, []).append(value)

    observations = []
    for day, values in values_by_date.items():
        values.sort()
        mid = len(values) // 2
        if len(values) % 2:
            value = values[mid]
        else:
            value = 0.5 * (values[mid - 1] + values[mid])
        observations.append({"date": day, variable: value})
    return observations


def _merge_observations(center, chl_rows, kd_rows):
    merged = {}
    for row in chl_rows:
        merged.setdefault(row["date"], {})["chl"] = row["chlor_a"]
    for row in kd_rows:
        merged.setdefault(row["date"], {})["kd490"] = row["kd_490"]

    observations = []
    for day, values in sorted(merged.items()):
        obs = {
            "center_id": center.center_id,
            "date": day,
            "source": "noaa_coastwatch_erddap",
            "tss": None,
            "chl": values.get("chlor_a"),
            "cdom_a440": None,
            "kd490": values.get("kd490"),
            "quality": "satellite",
        }
        observations.append(obs)
    return observations


def fetch_observations(center, start_date=None, end_date=None, buffer_m=1000):
    diagnostic = {
        "source": "noaa_coastwatch",
        "status": "ok",
        "detail": "NOAA CoastWatch ERDDAP consultado.",
    }
    try:
        chl_dataset, chl_var = DATASETS["chl"]
        kd_dataset, kd_var = DATASETS["kd490"]
        chl_rows = _fetch_variable(chl_dataset, chl_var, center, start_date, end_date, buffer_m)
        kd_rows = _fetch_variable(kd_dataset, kd_var, center, start_date, end_date, buffer_m)
        observations = _merge_observations(center, chl_rows, kd_rows)
        diagnostic["n_observations"] = len(observations)
        if not observations:
            diagnostic["status"] = "empty"
            diagnostic["detail"] = "Consulta ERDDAP sin píxeles válidos para el sitio/período."
        return {"observations": observations, "diagnostic": diagnostic}
    except HTTPError as exc:
        detail = exc.reason
        try:
            body = exc.read().decode("utf-8", errors="replace").strip()
            if body:
                detail = body[:500]
        except Exception:
            pass
        diagnostic["status"] = "error"
        diagnostic["detail"] = f"No se pudo consultar ERDDAP: HTTP {exc.code}: {detail}"
        return {"observations": [], "diagnostic": diagnostic}
    except (OSError, URLError, ValueError) as exc:
        diagnostic["status"] = "error"
        diagnostic["detail"] = f"No se pudo consultar ERDDAP: {exc}"
        return {"observations": [], "diagnostic": diagnostic}
