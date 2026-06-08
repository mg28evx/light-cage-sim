import argparse
import csv
import json
import math
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from statistics import median

from optical_sources import fetch_remote_observations, find_cached_observations, get_source_status


BASE_DIR = Path(__file__).resolve().parent
DEFAULT_CENTERS_CSV = BASE_DIR / "data" / "optical_centers.csv"


WATER_CLASS_DEFAULTS = {
    # Conservative starting points for Chilean marine cage sites when no local
    # satellite extraction has been loaded yet. Values are not field measurements.
    "fjord_clear": {
        "claro": {"tss": 2.0, "cdom_a440": 0.35, "chl": 0.7},
        "tipico": {"tss": 4.0, "cdom_a440": 0.6, "chl": 1.2},
        "turbio": {"tss": 8.0, "cdom_a440": 1.0, "chl": 2.5},
    },
    "fjord_typical": {
        "claro": {"tss": 4.0, "cdom_a440": 0.6, "chl": 1.0},
        "tipico": {"tss": 8.0, "cdom_a440": 1.0, "chl": 2.0},
        "turbio": {"tss": 15.0, "cdom_a440": 1.8, "chl": 5.0},
    },
    "fjord_turbid": {
        "claro": {"tss": 8.0, "cdom_a440": 1.0, "chl": 2.0},
        "tipico": {"tss": 15.0, "cdom_a440": 1.8, "chl": 5.0},
        "turbio": {"tss": 30.0, "cdom_a440": 3.0, "chl": 10.0},
    },
    "coastal_turbid": {
        "claro": {"tss": 10.0, "cdom_a440": 1.2, "chl": 2.0},
        "tipico": {"tss": 20.0, "cdom_a440": 2.0, "chl": 5.0},
        "turbio": {"tss": 40.0, "cdom_a440": 3.5, "chl": 12.0},
    },
}


@dataclass
class Center:
    center_id: str
    name: str
    lat: float | None
    lon: float | None
    water_class: str
    notes: str = ""


def _clean_float(value):
    if value is None:
        return None
    value = str(value).strip()
    if value == "":
        return None
    try:
        parsed = float(value)
    except ValueError:
        return None
    if math.isnan(parsed):
        return None
    return parsed


def _slug(value):
    return "".join(ch.lower() if ch.isalnum() else "_" for ch in str(value)).strip("_")


def _quantile(values, q):
    clean = sorted(v for v in values if v is not None)
    if not clean:
        return None
    if len(clean) == 1:
        return clean[0]
    pos = (len(clean) - 1) * q
    lo = math.floor(pos)
    hi = math.ceil(pos)
    if lo == hi:
        return clean[lo]
    return clean[lo] * (hi - pos) + clean[hi] * (pos - lo)


def _round_optics(value):
    return round(float(value), 4)


def _observation_iso_week(observation):
    raw_date = observation.get("date")
    if not raw_date:
        return None
    try:
        parsed = datetime.fromisoformat(str(raw_date)[:10]).date()
    except ValueError:
        return None
    iso_year, iso_week, _ = parsed.isocalendar()
    return iso_year, iso_week


def _matching_observations(center, observations):
    center_keys = {_slug(center.center_id), _slug(center.name)}
    return [o for o in observations if _slug(o.get("center_id")) in center_keys]


def _aggregate_week_rows_by_year(center, rows):
    rows_by_year = {}
    for row in rows:
        iso_period = _observation_iso_week(row)
        if iso_period:
            rows_by_year.setdefault(iso_period[0], []).append(row)

    aggregated = []
    for iso_year, year_rows in sorted(rows_by_year.items()):
        item = {
            "center_id": center.center_id,
            "date": f"{iso_year}-01-01",
            "source": "weekly_equal_year_weight",
            "quality": "weekly_climatology",
        }
        for key in (
            "tss", "cdom_a440", "chl", "kd490",
            "tss_uncertainty_pct", "cdom_uncertainty_pct",
            "chl_uncertainty_pct", "kd490_uncertainty_pct",
            "n_valid_pixels",
        ):
            values = [row.get(key) for row in year_rows if row.get(key) is not None]
            item[key] = median(values) if values else None
        aggregated.append(item)
    return aggregated


def load_centers(path=DEFAULT_CENTERS_CSV):
    path = Path(path)
    centers = {}
    if not path.exists():
        return centers

    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            center = Center(
                center_id=(row.get("center_id") or _slug(row.get("name", ""))).strip(),
                name=(row.get("name") or "").strip(),
                lat=_clean_float(row.get("lat")),
                lon=_clean_float(row.get("lon")),
                water_class=(row.get("water_class") or "fjord_typical").strip(),
                notes=(row.get("notes") or "").strip(),
            )
            centers[center.center_id] = center
            centers[_slug(center.name)] = center
    return centers


def load_observations(path):
    """Load satellite/proxy observations.

    Supported columns include:
    center_id,date,source,tss,spm,chl,cdom_a440,cdom_a443,kd490,zsd,quality
    and optional uncertainty columns ending in _uncertainty_pct.
    """
    observations = []
    if not path:
        return observations

    with Path(path).open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            tss = _clean_float(row.get("tss"))
            if tss is None:
                tss = _clean_float(row.get("spm"))

            cdom_a440 = _clean_float(row.get("cdom_a440"))
            cdom_a443 = _clean_float(row.get("cdom_a443"))
            if cdom_a440 is None and cdom_a443 is not None:
                cdom_a440 = cdom_a443 * math.exp(0.015 * 3.0)

            kd490 = _clean_float(row.get("kd490"))
            zsd = _clean_float(row.get("zsd"))
            if kd490 is None and zsd and zsd > 0:
                kd490 = 1.7 / zsd

            observations.append({
                "center_id": (row.get("center_id") or "").strip(),
                "date": (row.get("date") or "").strip(),
                "source": (row.get("source") or "").strip(),
                "tss": tss,
                "chl": _clean_float(row.get("chl")),
                "cdom_a440": cdom_a440,
                "kd490": kd490,
                "tss_uncertainty_pct": _clean_float(row.get("tss_uncertainty_pct")),
                "chl_uncertainty_pct": _clean_float(row.get("chl_uncertainty_pct")),
                "cdom_uncertainty_pct": _clean_float(row.get("cdom_uncertainty_pct")),
                "kd490_uncertainty_pct": _clean_float(row.get("kd490_uncertainty_pct")),
                "n_valid_pixels": _clean_float(row.get("n_valid_pixels")),
                "quality": (row.get("quality") or "").strip(),
            })
    return observations


def load_observations_for_center(center, observations_path=None, source="auto", start_date=None, end_date=None, buffer_m=1000):
    observations = []
    diagnostics = []
    selected_path = observations_path

    if not selected_path and source in ("auto", "cache"):
        cached_path = find_cached_observations(center.center_id, include_example=(source == "cache"))
        if cached_path:
            selected_path = str(cached_path)
            diagnostics.append({
                "source": "cache",
                "status": "ok",
                "detail": f"Observaciones cargadas desde {cached_path}",
            })

    if selected_path:
        observations.extend(load_observations(selected_path))

    if source != "cache":
        remote_observations, remote_diagnostics = fetch_remote_observations(
            center,
            start_date=start_date,
            end_date=end_date,
            buffer_m=buffer_m,
            source=source,
        )
        observations.extend(remote_observations)
        diagnostics.extend(remote_diagnostics)

    return observations, diagnostics


def resolve_center(center=None, lat=None, lon=None, water_class=None, centers_path=DEFAULT_CENTERS_CSV):
    centers = load_centers(centers_path)
    found = centers.get(center) or centers.get(_slug(center or ""))
    if found:
        return Center(
            center_id=found.center_id,
            name=found.name,
            lat=_clean_float(lat) if _clean_float(lat) is not None else found.lat,
            lon=_clean_float(lon) if _clean_float(lon) is not None else found.lon,
            water_class=water_class or found.water_class,
            notes=found.notes,
        )
    return Center(
        center_id=_slug(center or "custom_site"),
        name=center or "Custom site",
        lat=_clean_float(lat),
        lon=_clean_float(lon),
        water_class=water_class or "fjord_typical",
        notes="Centro ingresado manualmente.",
    )


def _base_for_water_class(water_class):
    return WATER_CLASS_DEFAULTS.get(water_class, WATER_CLASS_DEFAULTS["fjord_typical"])


def _estimate_kd490(values, g=0.85, mu_d=0.85):
    chl = float(values.get("chl") or 0.0)
    tss = float(values.get("tss") or 0.0)
    cdom = float(values.get("cdom_a440") or 0.0)
    aw_490 = 0.026
    aphy_star_490 = 0.012
    bstar_490 = 0.35
    a_cdom_490 = cdom * math.exp(-0.015 * (490.0 - 440.0))
    a_total = aw_490 + a_cdom_490 + aphy_star_490 * chl
    b_total = bstar_490 * tss
    return (a_total + (1.0 - g) * b_total) / mu_d


def _fit_defaults_to_kd(default_values, target_kd):
    if target_kd is None or target_kd <= 0:
        return default_values
    fitted = dict(default_values)
    base_kd = _estimate_kd490(fitted)
    if base_kd <= 0:
        return fitted
    ratio = max(0.35, min(target_kd / base_kd, 3.0))
    fitted["tss"] = fitted["tss"] * ratio
    fitted["cdom_a440"] = fitted["cdom_a440"] * ratio
    return fitted


def _scenario_values(center, observations):
    defaults = _base_for_water_class(center.water_class)
    matching = _matching_observations(center, observations)

    if not matching:
        return defaults, {
            "level": "baja",
            "reason": "Sin observaciones cargadas; se usaron proxies por clase de agua.",
            "n_observations": 0,
        }

    scenarios = {}
    quantiles = {"claro": 0.25, "tipico": 0.5, "turbio": 0.75}
    for label, q in quantiles.items():
        scenarios[label] = {}
        kd_observed = _quantile([row.get("kd490") for row in matching], q)
        kd_adjusted_defaults = _fit_defaults_to_kd(defaults[label], kd_observed)
        for key in ("tss", "cdom_a440", "chl"):
            observed = _quantile([row.get(key) for row in matching], q)
            fallback = kd_adjusted_defaults[key]
            scenarios[label][key] = observed if observed is not None else fallback

    valid_days = len({row.get("date") for row in matching if row.get("date")})
    if len(matching) >= 10 and valid_days >= 5:
        level = "media-alta"
    elif len(matching) >= 4:
        level = "media"
    else:
        level = "baja-media"

    kd_values = [row.get("kd490") for row in matching if row.get("kd490") is not None]
    confidence = {
        "level": level,
        "reason": "Presets derivados de observaciones satelitales/proxy disponibles.",
        "n_observations": len(matching),
        "valid_days": valid_days,
    }
    if kd_values:
        confidence["kd490_median"] = round(median(kd_values), 4)
        confidence["kd490_p25"] = round(_quantile(kd_values, 0.25), 4)
        confidence["kd490_p75"] = round(_quantile(kd_values, 0.75), 4)
        confidence["kd490_iqr"] = round(confidence["kd490_p75"] - confidence["kd490_p25"], 4)

    for key in ("tss", "chl", "cdom_a440"):
        values = [row.get(key) for row in matching if row.get(key) is not None]
        if values:
            p25 = _quantile(values, 0.25)
            p75 = _quantile(values, 0.75)
            confidence[f"{key}_iqr"] = round(p75 - p25, 4)

    for key in ("tss", "chl", "cdom", "kd490"):
        values = [
            row.get(f"{key}_uncertainty_pct")
            for row in matching
            if row.get(f"{key}_uncertainty_pct") is not None
        ]
        if values:
            confidence[f"{key}_uncertainty_pct_median"] = round(median(values), 2)

    pixel_counts = [row.get("n_valid_pixels") for row in matching if row.get("n_valid_pixels") is not None]
    if pixel_counts:
        confidence["n_valid_pixels_median"] = round(median(pixel_counts), 1)
    return scenarios, confidence


def _preset_payload(name, values, g=0.85, r_wall=0.15):
    return {
        "label": name,
        "optics_mode": "scattering",
        "optics": {
            "mc_input_type": "bio",
            "tss": _round_optics(values["tss"]),
            "cdom_a440": _round_optics(values["cdom_a440"]),
            "chl": _round_optics(values["chl"]),
            "g": _round_optics(g),
            "r_wall": _round_optics(r_wall),
        },
    }


def build_optical_presets(
    center=None,
    lat=None,
    lon=None,
    water_class=None,
    observations_path=None,
    centers_path=DEFAULT_CENTERS_CSV,
    source="auto",
    start_date=None,
    end_date=None,
    buffer_m=1000,
):
    site = resolve_center(center=center, lat=lat, lon=lon, water_class=water_class, centers_path=centers_path)
    observations, diagnostics = load_observations_for_center(
        site,
        observations_path=observations_path,
        source=source,
        start_date=start_date,
        end_date=end_date,
        buffer_m=buffer_m,
    )
    scenarios, confidence = _scenario_values(site, observations)
    confidence["source_mode"] = source
    confidence["buffer_m"] = buffer_m
    if start_date or end_date:
        confidence["period"] = {"start_date": start_date, "end_date": end_date}

    return {
        "center": {
            "center_id": site.center_id,
            "name": site.name,
            "lat": site.lat,
            "lon": site.lon,
            "water_class": site.water_class,
            "notes": site.notes,
        },
        "presets": {
            name: _preset_payload(name, values)
            for name, values in scenarios.items()
        },
        "confidence": confidence,
        "diagnostics": diagnostics,
        "source_status": get_source_status(),
        "usage": "Copie uno de los objetos presets.* al JSON de configuración del simulador.",
    }


def build_optical_weekly_profile(
    center=None,
    lat=None,
    lon=None,
    water_class=None,
    observations_path=None,
    centers_path=DEFAULT_CENTERS_CSV,
    source="auto",
    buffer_m=1000,
    years_back=3,
):
    site = resolve_center(center=center, lat=lat, lon=lon, water_class=water_class, centers_path=centers_path)
    current_year = date.today().year
    years_back = max(1, min(int(years_back or 3), 15))
    start_year = current_year - years_back
    end_year = current_year - 1
    start_date = f"{start_year}-01-01"
    end_date = f"{end_year}-12-31"

    observations, diagnostics = load_observations_for_center(
        site,
        observations_path=observations_path,
        source=source,
        start_date=start_date,
        end_date=end_date,
        buffer_m=buffer_m,
    )
    matching = _matching_observations(site, observations)
    weeks = {week: [] for week in range(1, 54)}
    for observation in matching:
        iso_period = _observation_iso_week(observation)
        if not iso_period:
            continue
        iso_year, iso_week = iso_period
        if start_year <= iso_year <= end_year and iso_week in weeks:
            weeks[iso_week].append(observation)

    week_payloads = []
    for iso_week in range(1, 54):
        rows = weeks[iso_week]
        yearly_rows = _aggregate_week_rows_by_year(site, rows)
        represented_years = sorted({
            _observation_iso_week(row)[0]
            for row in rows
            if _observation_iso_week(row)
        })
        valid_days = len({row.get("date") for row in rows if row.get("date")})
        n_observations = len(rows)
        useful = len(represented_years) >= 2 and valid_days >= 4
        status = "util" if useful else ("limitada" if n_observations else "sin_datos")

        medians = {}
        ranges = {}
        for key in ("tss", "cdom_a440", "chl", "kd490"):
            values = [row.get(key) for row in yearly_rows if row.get(key) is not None]
            medians[key] = _round_optics(median(values)) if values else None
            ranges[key] = {
                "p25": _round_optics(_quantile(values, 0.25)) if values else None,
                "p75": _round_optics(_quantile(values, 0.75)) if values else None,
            }

        scenarios, confidence = _scenario_values(site, yearly_rows)
        confidence["n_observations"] = n_observations
        confidence["valid_days"] = valid_days
        if useful and len(represented_years) >= 3:
            confidence["level"] = "media-alta"
        elif useful:
            confidence["level"] = "media"
        elif n_observations:
            confidence["level"] = "baja-media"
        confidence["source_mode"] = source
        confidence["buffer_m"] = buffer_m
        confidence["iso_week"] = iso_week
        confidence["years"] = represented_years
        confidence["historical_period"] = {"start_date": start_date, "end_date": end_date}

        week_payloads.append({
            "iso_week": iso_week,
            "status": status,
            "useful": useful,
            "n_observations": n_observations,
            "valid_days": valid_days,
            "years": represented_years,
            "medians": medians,
            "ranges": ranges,
            "presets": {
                name: _preset_payload(name, values)
                for name, values in scenarios.items()
            },
            "confidence": confidence,
        })

    return {
        "center": {
            "center_id": site.center_id,
            "name": site.name,
            "lat": site.lat,
            "lon": site.lon,
            "water_class": site.water_class,
            "notes": site.notes,
        },
        "historical_period": {"start_date": start_date, "end_date": end_date},
        "years_back": years_back,
        "weeks": week_payloads,
        "diagnostics": diagnostics,
        "source_status": get_source_status(),
        "method": "Climatología por semana ISO con igual ponderación para cada año completo.",
    }


def main():
    parser = argparse.ArgumentParser(description="Genera presets bio-ópticos para el simulador Evolux.")
    parser.add_argument("--center", help="Nombre o center_id. Ej: bajos_lami, pilpilehue")
    parser.add_argument("--lat", type=float, help="Latitud si no existe el centro en el CSV.")
    parser.add_argument("--lon", type=float, help="Longitud si no existe el centro en el CSV.")
    parser.add_argument("--water-class", default=None, choices=sorted(WATER_CLASS_DEFAULTS.keys()))
    parser.add_argument("--observations", help="CSV con observaciones satelitales/proxy.")
    parser.add_argument("--source", default="auto", choices=["auto", "cache", "copernicus", "nasa_oceancolor", "noaa_coastwatch", "sentinel2"])
    parser.add_argument("--start-date", help="Fecha inicial YYYY-MM-DD.")
    parser.add_argument("--end-date", help="Fecha final YYYY-MM-DD.")
    parser.add_argument("--buffer-m", default=1000, type=float, help="Radio de extracción en metros.")
    parser.add_argument("--centers", default=str(DEFAULT_CENTERS_CSV), help="CSV de centros conocidos.")
    parser.add_argument("--output", help="Archivo JSON de salida. Si se omite, imprime a stdout.")
    args = parser.parse_args()

    result = build_optical_presets(
        center=args.center,
        lat=args.lat,
        lon=args.lon,
        water_class=args.water_class,
        observations_path=args.observations,
        centers_path=args.centers,
        source=args.source,
        start_date=args.start_date,
        end_date=args.end_date,
        buffer_m=args.buffer_m,
    )
    text = json.dumps(result, indent=4, ensure_ascii=False)
    if args.output:
        Path(args.output).write_text(text + "\n", encoding="utf-8")
    else:
        print(text)


if __name__ == "__main__":
    main()
