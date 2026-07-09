import argparse
import csv
import math
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from statistics import median

import numpy as np

from optical_lookup import DEFAULT_CENTERS_CSV, _clean_float, _slug, load_centers, resolve_center


BASE_DIR = Path(__file__).resolve().parent
DEFAULT_OUTPUT_DIR = BASE_DIR / "data" / "ocean_physics"

TEMPERATURE_DATASET = "cmems_mod_glo_phy-thetao_anfc_0.083deg_P1D-m"
SALINITY_DATASET = "cmems_mod_glo_phy-so_anfc_0.083deg_P1D-m"
PRODUCT_ID = "GLOBAL_ANALYSISFORECAST_PHY_001_024"


@dataclass
class ExtractionConfig:
    start_date: date
    end_date: date
    buffer_m: float
    depth_m: float
    depth_window_m: float
    temperature_dataset: str
    salinity_dataset: str


def _date_from_iso(value, label):
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} debe tener formato YYYY-MM-DD") from exc


def _buffer_to_box(lat, lon, buffer_m):
    radius_m = max(float(buffer_m), 1.0)
    lat_delta = radius_m / 111_320.0
    lon_delta = lat_delta / max(math.cos(math.radians(lat)), 0.2)
    return lat - lat_delta, lat + lat_delta, lon - lon_delta, lon + lon_delta


def _depth_bounds(depth_m, depth_window_m):
    depth = max(float(depth_m), 0.0)
    half_window = max(float(depth_window_m), 0.0)
    return max(depth - half_window, 0.0), depth + half_window


def _daily_stats(ds, variable):
    if variable not in ds:
        raise KeyError(f"Variable {variable!r} no encontrada en dataset Copernicus.")

    array = ds[variable]
    reduction_dims = [dim for dim in array.dims if dim != "time"]
    if reduction_dims:
        values_by_day = array.median(dim=reduction_dims, skipna=True)
        counts_by_day = array.count(dim=reduction_dims)
    else:
        values_by_day = array
        counts_by_day = array.notnull().astype(int)

    stats = {}
    for idx, time_value in enumerate(values_by_day["time"].values):
        value = float(values_by_day.values[idx])
        count = int(counts_by_day.values[idx])
        if np.isfinite(value) and count > 0:
            day = np.datetime_as_string(time_value, unit="D")
            stats[day] = {"value": value, "count": count}
    return stats


def _coord_values(ds, name):
    if name not in ds.coords:
        return []
    values = []
    for value in ds.coords[name].values:
        parsed = float(value)
        if math.isfinite(parsed):
            values.append(parsed)
    return values


def _open_physics_dataset(dataset_id, variable, center, config):
    import copernicusmarine

    lat_min, lat_max, lon_min, lon_max = _buffer_to_box(center.lat, center.lon, config.buffer_m)
    depth_min, depth_max = _depth_bounds(config.depth_m, config.depth_window_m)
    return copernicusmarine.open_dataset(
        dataset_id=dataset_id,
        variables=[variable],
        minimum_longitude=lon_min,
        maximum_longitude=lon_max,
        minimum_latitude=lat_min,
        maximum_latitude=lat_max,
        minimum_depth=depth_min,
        maximum_depth=depth_max,
        start_datetime=config.start_date.isoformat(),
        end_datetime=config.end_date.isoformat(),
        coordinates_selection_method="outside",
    )


def extract_center(center, config):
    if center.lat is None or center.lon is None:
        raise ValueError(f"El centro {center.center_id!r} no tiene lat/lon.")

    thetao_ds = _open_physics_dataset(config.temperature_dataset, "thetao", center, config)
    so_ds = _open_physics_dataset(config.salinity_dataset, "so", center, config)

    temperature = _daily_stats(thetao_ds, "thetao")
    salinity = _daily_stats(so_ds, "so")
    days = sorted(set(temperature) | set(salinity))
    depth_levels = sorted(set(_coord_values(thetao_ds, "depth") + _coord_values(so_ds, "depth")))
    latitudes = sorted(set(_coord_values(thetao_ds, "latitude") + _coord_values(so_ds, "latitude")))
    longitudes = sorted(set(_coord_values(thetao_ds, "longitude") + _coord_values(so_ds, "longitude")))

    rows = []
    for day in days:
        temp = temperature.get(day, {})
        salt = salinity.get(day, {})
        rows.append({
            "center_id": center.center_id,
            "name": center.name,
            "lat": center.lat,
            "lon": center.lon,
            "date": day,
            "temperature_thetao_degC": _round_value(temp.get("value")),
            "salinity_so_psu": _round_value(salt.get("value")),
            "n_valid_temperature_cells": temp.get("count", 0),
            "n_valid_salinity_cells": salt.get("count", 0),
            "depth_request_m": config.depth_m,
            "depth_window_m": config.depth_window_m,
            "depth_levels_m": "|".join(f"{value:.3f}" for value in depth_levels),
            "buffer_m": config.buffer_m,
            "latitude_cells": "|".join(f"{value:.5f}" for value in latitudes),
            "longitude_cells": "|".join(f"{value:.5f}" for value in longitudes),
            "product_id": PRODUCT_ID,
            "temperature_dataset": config.temperature_dataset,
            "salinity_dataset": config.salinity_dataset,
            "source": "copernicus_marine_analysis_forecast_daily",
        })
    return rows


def _round_value(value):
    if value is None:
        return ""
    return round(float(value), 5)


def _resolve_centers(args):
    if args.all_centers:
        centers = {}
        for center in load_centers(args.centers).values():
            centers[center.center_id] = center
        return [centers[key] for key in sorted(centers)]

    center = resolve_center(
        center=args.center,
        lat=args.lat,
        lon=args.lon,
        water_class=args.water_class,
        centers_path=args.centers,
    )
    if center.center_id == "custom_site" and (center.lat is None or center.lon is None):
        raise ValueError("Indique --center conocido o bien --lat y --lon.")
    return [center]


def _default_output_path(centers, config):
    if len(centers) == 1:
        slug = _slug(centers[0].center_id)
    else:
        slug = "all_centers"
    filename = (
        f"copernicus_physics_{slug}_"
        f"{config.start_date.isoformat()}_{config.end_date.isoformat()}_"
        f"z{config.depth_m:g}m.csv"
    )
    return DEFAULT_OUTPUT_DIR / filename


def write_csv(rows, output_path):
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "center_id",
        "name",
        "lat",
        "lon",
        "date",
        "temperature_thetao_degC",
        "salinity_so_psu",
        "n_valid_temperature_cells",
        "n_valid_salinity_cells",
        "depth_request_m",
        "depth_window_m",
        "depth_levels_m",
        "buffer_m",
        "latitude_cells",
        "longitude_cells",
        "product_id",
        "temperature_dataset",
        "salinity_dataset",
        "source",
    ]
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def summarize(rows):
    valid_temperature = [
        _clean_float(row["temperature_thetao_degC"])
        for row in rows
        if _clean_float(row["temperature_thetao_degC"]) is not None
    ]
    valid_salinity = [
        _clean_float(row["salinity_so_psu"])
        for row in rows
        if _clean_float(row["salinity_so_psu"]) is not None
    ]
    centers = sorted({row["center_id"] for row in rows})
    dates = sorted({row["date"] for row in rows})
    return {
        "centers": centers,
        "rows": len(rows),
        "date_start": dates[0] if dates else "",
        "date_end": dates[-1] if dates else "",
        "temperature_median_degC": _round_value(median(valid_temperature)) if valid_temperature else "",
        "salinity_median_psu": _round_value(median(valid_salinity)) if valid_salinity else "",
    }


def parse_args():
    parser = argparse.ArgumentParser(
        description="Extrae temperatura y salinidad diaria desde Copernicus Marine para centros Evolux."
    )
    parser.add_argument("--center", help="Nombre o center_id. Ej: bajos_lami, pilpilehue")
    parser.add_argument("--all-centers", action="store_true", help="Extrae todos los centros definidos en el CSV.")
    parser.add_argument("--lat", type=float, help="Latitud si no existe el centro en el CSV.")
    parser.add_argument("--lon", type=float, help="Longitud si no existe el centro en el CSV.")
    parser.add_argument("--water-class", default=None)
    parser.add_argument("--centers", default=str(DEFAULT_CENTERS_CSV), help="CSV de centros conocidos.")
    parser.add_argument("--start-date", required=True, help="Fecha inicial YYYY-MM-DD.")
    parser.add_argument("--end-date", required=True, help="Fecha final YYYY-MM-DD.")
    parser.add_argument("--buffer-m", default=6000.0, type=float, help="Radio de extracción espacial en metros.")
    parser.add_argument(
        "--depth-m",
        default=0.5,
        type=float,
        help="Profundidad objetivo en metros. 0.5 m corresponde a la capa superficial Copernicus.",
    )
    parser.add_argument(
        "--depth-window-m",
        default=0.0,
        type=float,
        help="Semiancho de la ventana vertical. Use, por ejemplo, 5 para mediana 0-5.5 m aprox.",
    )
    parser.add_argument("--temperature-dataset", default=TEMPERATURE_DATASET)
    parser.add_argument("--salinity-dataset", default=SALINITY_DATASET)
    parser.add_argument("--output", help="CSV de salida. Si se omite, usa data/ocean_physics/.")
    return parser.parse_args()


def main():
    args = parse_args()
    start = _date_from_iso(args.start_date, "--start-date")
    end = _date_from_iso(args.end_date, "--end-date")
    if end < start:
        raise ValueError("--end-date debe ser mayor o igual a --start-date")
    if end > date.today() + timedelta(days=10):
        raise ValueError("El rango solicitado supera el horizonte operacional razonable del producto forecast.")

    config = ExtractionConfig(
        start_date=start,
        end_date=end,
        buffer_m=args.buffer_m,
        depth_m=args.depth_m,
        depth_window_m=args.depth_window_m,
        temperature_dataset=args.temperature_dataset,
        salinity_dataset=args.salinity_dataset,
    )
    centers = _resolve_centers(args)

    rows = []
    for center in centers:
        rows.extend(extract_center(center, config))

    output_path = Path(args.output) if args.output else _default_output_path(centers, config)
    write_csv(rows, output_path)
    summary = summarize(rows)
    print(f"Archivo: {output_path}")
    print(f"Filas: {summary['rows']}")
    print(f"Centros: {', '.join(summary['centers'])}")
    print(f"Periodo: {summary['date_start']} a {summary['date_end']}")
    print(f"Mediana thetao degC: {summary['temperature_median_degC']}")
    print(f"Mediana so psu: {summary['salinity_median_psu']}")


if __name__ == "__main__":
    main()
