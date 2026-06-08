import importlib.util
import math
import os
from datetime import date, timedelta
from pathlib import Path

import numpy as np


DATASETS = {
    "my": {
        "chl": ("cmems_obs-oc_glo_bgc-plankton_my_l3-multi-4km_P1D", ["CHL", "CHL_uncertainty"]),
        "transp": (
            "cmems_obs-oc_glo_bgc-transp_my_l3-multi-4km_P1D",
            ["KD490", "KD490_uncertainty", "SPM", "SPM_uncertainty"],
        ),
        "optics": ("cmems_obs-oc_glo_bgc-optics_my_l3-multi-4km_P1D", ["CDM", "CDM_uncertainty"]),
    },
    "nrt": {
        "chl": ("cmems_obs-oc_glo_bgc-plankton_nrt_l3-multi-4km_P1D", ["CHL", "CHL_uncertainty"]),
        "transp": (
            "cmems_obs-oc_glo_bgc-transp_nrt_l3-multi-4km_P1D",
            ["KD490", "KD490_uncertainty", "SPM", "SPM_uncertainty"],
        ),
        "optics": ("cmems_obs-oc_glo_bgc-optics_nrt_l3-multi-4km_P1D", ["CDM", "CDM_uncertainty"]),
    },
}


def _credentials_present():
    if os.environ.get("COPERNICUSMARINE_SERVICE_USERNAME") and os.environ.get("COPERNICUSMARINE_SERVICE_PASSWORD"):
        return True
    home = Path.home()
    candidates = [
        home / ".copernicusmarine" / ".copernicusmarine-credentials",
        home / ".netrc",
    ]
    return any(path.exists() for path in candidates)


def source_status():
    available = importlib.util.find_spec("copernicusmarine") is not None
    configured = available and _credentials_present()
    return {
        "label": "Copernicus Marine",
        "available": available,
        "configured": configured,
        "detail": (
            "GlobColour global L3 diario: CHL, KD490, SPM, CDM e incertidumbres."
            if configured
            else "Ejecutar copernicusmarine login para habilitar GlobColour global."
        ),
    }


def _date_range(start_date, end_date):
    end = date.fromisoformat(end_date) if end_date else date.today()
    start = date.fromisoformat(start_date) if start_date else end - timedelta(days=90)
    return start, end


def _dataset_family(start, end):
    # NRT is intended for recent operational use; MY is reprocessed and preferred
    # for older periods because its calibration is more stable.
    return "nrt" if end >= date.today() - timedelta(days=120) else "my"


def _buffer_to_box(lat, lon, buffer_m):
    # GlobColour is 4 km; enforce a box large enough to contain several pixels.
    radius_m = max(float(buffer_m), 6000.0)
    lat_delta = radius_m / 111_320.0
    lon_delta = lat_delta / max(math.cos(math.radians(lat)), 0.2)
    return lat - lat_delta, lat + lat_delta, lon - lon_delta, lon + lon_delta


def _daily_spatial_stats(ds, variable):
    if variable not in ds:
        return {}
    array = ds[variable]
    spatial_dims = [dim for dim in array.dims if dim != "time"]
    if spatial_dims:
        medians = array.median(dim=spatial_dims, skipna=True)
        counts = array.count(dim=spatial_dims)
    else:
        medians = array
        counts = array.notnull().astype(int)

    result = {}
    for idx, time_value in enumerate(medians["time"].values):
        value = float(medians.values[idx])
        count = int(counts.values[idx])
        if np.isfinite(value) and count > 0:
            day = np.datetime_as_string(time_value, unit="D")
            result[day] = {"value": value, "count": count}
    return result


def _open_dataset(dataset_id, variables, center, start, end, buffer_m):
    import copernicusmarine

    lat_min, lat_max, lon_min, lon_max = _buffer_to_box(center.lat, center.lon, buffer_m)
    return copernicusmarine.open_dataset(
        dataset_id=dataset_id,
        variables=variables,
        minimum_longitude=lon_min,
        maximum_longitude=lon_max,
        minimum_latitude=lat_min,
        maximum_latitude=lat_max,
        start_datetime=start.isoformat(),
        end_datetime=end.isoformat(),
        coordinates_selection_method="outside",
    )


def _merge_dataset(observations, ds, variable_map):
    stats = {name: _daily_spatial_stats(ds, name) for name in variable_map}
    days = set()
    for values in stats.values():
        days.update(values.keys())

    for day in days:
        obs = observations.setdefault(day, {})
        for source_var, target_var in variable_map.items():
            item = stats[source_var].get(day)
            if not item:
                continue
            value = item["value"]
            if source_var == "CDM":
                # Copernicus CDM is absorption by CDOM + detritus at 443 nm.
                value = value * math.exp(0.015 * 3.0)
            obs[target_var] = value
            obs["n_valid_pixels"] = max(obs.get("n_valid_pixels", 0), item["count"])


def fetch_observations(center, start_date=None, end_date=None, buffer_m=1000):
    status = source_status()
    diagnostic = {
        "source": "copernicus",
        "status": "skipped",
        "detail": status["detail"],
    }
    if not status["available"]:
        diagnostic["detail"] = "Paquete copernicusmarine no instalado."
        return {"observations": [], "diagnostic": diagnostic}
    if not status["configured"]:
        return {"observations": [], "diagnostic": diagnostic}
    if center.lat is None or center.lon is None:
        diagnostic["detail"] = "El centro no tiene coordenadas."
        return {"observations": [], "diagnostic": diagnostic}

    start, end = _date_range(start_date, end_date)
    family = _dataset_family(start, end)
    observations_by_day = {}
    used_datasets = []

    try:
        for key, variable_map in (
            ("chl", {"CHL": "chl", "CHL_uncertainty": "chl_uncertainty_pct"}),
            (
                "transp",
                {
                    "KD490": "kd490",
                    "KD490_uncertainty": "kd490_uncertainty_pct",
                    "SPM": "tss",
                    "SPM_uncertainty": "tss_uncertainty_pct",
                },
            ),
            ("optics", {"CDM": "cdom_a440", "CDM_uncertainty": "cdom_uncertainty_pct"}),
        ):
            dataset_id, variables = DATASETS[family][key]
            ds = _open_dataset(dataset_id, variables, center, start, end, buffer_m)
            _merge_dataset(observations_by_day, ds, variable_map)
            used_datasets.append(dataset_id)

        observations = []
        for day, values in sorted(observations_by_day.items()):
            observations.append({
                "center_id": center.center_id,
                "date": day,
                "source": f"copernicus_globcolour_{family}",
                "quality": "satellite_l3",
                **values,
            })

        diagnostic.update({
            "status": "ok" if observations else "empty",
            "detail": f"Copernicus GlobColour {family.upper()} consultado.",
            "n_observations": len(observations),
            "datasets": used_datasets,
            "resolution_km": 4,
        })
        return {"observations": observations, "diagnostic": diagnostic}
    except Exception as exc:
        diagnostic["status"] = "error"
        diagnostic["detail"] = f"No se pudo consultar Copernicus Marine: {exc}"
        diagnostic["datasets"] = used_datasets
        return {"observations": [], "diagnostic": diagnostic}
