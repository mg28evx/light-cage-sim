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


DEFAULT_FNU_TO_TSS_SLOPE = 1.0
DEFAULT_FNU_TO_TSS_INTERCEPT = 0.0
RELONCAVI_NV09_RMSE_FNU = 0.66


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


def _calibration_from_values(slope=None, intercept=None):
    slope = _clean_float(slope)
    intercept = _clean_float(intercept)
    return {
        "slope": slope if slope is not None else DEFAULT_FNU_TO_TSS_SLOPE,
        "intercept": intercept if intercept is not None else DEFAULT_FNU_TO_TSS_INTERCEPT,
        "model": "tss_mg_l = slope * turbidity_fnu + intercept",
        "reference": "Calibración local requerida; por defecto se usa equivalencia operacional 1 FNU ≈ 1 mg/L.",
    }


def _tss_from_turbidity_fnu(turbidity_fnu, calibration):
    if turbidity_fnu is None:
        return None
    value = calibration["slope"] * float(turbidity_fnu) + calibration["intercept"]
    return max(value, 0.0)


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
            "tss", "turbidity_fnu", "cdom_a440", "chl", "kd490",
            "tss_uncertainty_pct", "turbidity_uncertainty_fnu", "cdom_uncertainty_pct",
            "chl_uncertainty_pct", "kd490_uncertainty_pct",
            "n_valid_pixels",
        ):
            values = [row.get(key) for row in year_rows if row.get(key) is not None]
            item[key] = median(values) if values else None
        item["tss_is_proxy"] = any(row.get("tss_is_proxy") for row in year_rows)
        item["tss_proxy_source"] = ", ".join(sorted({
            row.get("tss_proxy_source")
            for row in year_rows
            if row.get("tss_proxy_source")
        }))
        item["tss_conversion"] = next((row.get("tss_conversion") for row in year_rows if row.get("tss_conversion")), None)
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


def load_observations(path, fnu_to_tss_slope=None, fnu_to_tss_intercept=None):
    """Load satellite/proxy observations.

    Supported columns include:
    center_id,date,source,tss,spm,turbidity_fnu,chl,cdom_a440,cdom_a443,kd490,zsd,quality
    and optional uncertainty columns ending in _uncertainty_pct.
    """
    observations = []
    if not path:
        return observations
    calibration = _calibration_from_values(fnu_to_tss_slope, fnu_to_tss_intercept)

    with Path(path).open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            tss = _clean_float(row.get("tss"))
            tss_is_proxy = False
            tss_proxy_source = ""
            if tss is None:
                spm = _clean_float(row.get("spm"))
                if spm is not None:
                    tss = spm
                    tss_is_proxy = True
                    tss_proxy_source = "spm"
            turbidity_fnu = _clean_float(row.get("turbidity_fnu"))
            if tss is None and turbidity_fnu is not None:
                tss = _tss_from_turbidity_fnu(turbidity_fnu, calibration)
                tss_is_proxy = True
                tss_proxy_source = "turbidity_fnu"

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
                "turbidity_fnu": turbidity_fnu,
                "turbidity_algorithm": (row.get("turbidity_algorithm") or "").strip(),
                "turbidity_uncertainty_fnu": _clean_float(row.get("turbidity_uncertainty_fnu")),
                "tss_is_proxy": tss_is_proxy,
                "tss_proxy_source": tss_proxy_source,
                "tss_conversion": calibration if tss_is_proxy else None,
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


def _normalize_proxy_observations(observations, calibration):
    for obs in observations:
        turbidity_fnu = obs.get("turbidity_fnu")
        if obs.get("tss") is None and turbidity_fnu is not None:
            obs["tss"] = _tss_from_turbidity_fnu(turbidity_fnu, calibration)
            obs["tss_is_proxy"] = True
            obs["tss_proxy_source"] = obs.get("tss_proxy_source") or "turbidity_fnu"
            obs["tss_conversion"] = calibration
        if obs.get("source", "").startswith("sentinel2") and obs.get("turbidity_uncertainty_fnu") is None:
            obs["turbidity_uncertainty_fnu"] = RELONCAVI_NV09_RMSE_FNU
        obs.setdefault("tss_is_proxy", False)
        obs.setdefault("tss_proxy_source", "")
        obs.setdefault("tss_conversion", None)
    return observations


def load_observations_for_center(
    center,
    observations_path=None,
    source="auto",
    start_date=None,
    end_date=None,
    buffer_m=1000,
    fnu_to_tss_slope=None,
    fnu_to_tss_intercept=None,
):
    observations = []
    diagnostics = []
    selected_path = observations_path
    calibration = _calibration_from_values(fnu_to_tss_slope, fnu_to_tss_intercept)

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
        observations.extend(load_observations(
            selected_path,
            fnu_to_tss_slope=calibration["slope"],
            fnu_to_tss_intercept=calibration["intercept"],
        ))

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

    return _normalize_proxy_observations(observations, calibration), diagnostics


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
    proxy_rows = [row for row in matching if row.get("tss_is_proxy")]
    if proxy_rows:
        confidence["tss_proxy_count"] = len(proxy_rows)
        confidence["tss_proxy_fraction"] = round(len(proxy_rows) / max(len(matching), 1), 3)
        confidence["tss_proxy_source"] = ", ".join(sorted({
            row.get("tss_proxy_source") or "proxy"
            for row in proxy_rows
        }))
        conversion = next((row.get("tss_conversion") for row in proxy_rows if row.get("tss_conversion")), None)
        if conversion:
            confidence["tss_conversion"] = conversion
        confidence["reason"] = (
            "Presets derivados de observaciones satelitales; TSS incluye conversión proxy "
            "desde turbidez FNU cuando no existe TSS/SPM directo."
        )

    turbidity_values = [row.get("turbidity_fnu") for row in matching if row.get("turbidity_fnu") is not None]
    if turbidity_values:
        confidence["turbidity_fnu_median"] = round(median(turbidity_values), 4)
        confidence["turbidity_fnu_p25"] = round(_quantile(turbidity_values, 0.25), 4)
        confidence["turbidity_fnu_p75"] = round(_quantile(turbidity_values, 0.75), 4)

    source_names = sorted({row.get("source") for row in matching if row.get("source")})
    if source_names:
        confidence["observation_sources"] = source_names
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

    turbidity_uncertainties = [
        row.get("turbidity_uncertainty_fnu")
        for row in matching
        if row.get("turbidity_uncertainty_fnu") is not None
    ]
    if turbidity_uncertainties:
        confidence["turbidity_uncertainty_fnu_median"] = round(median(turbidity_uncertainties), 3)

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
    fnu_to_tss_slope=None,
    fnu_to_tss_intercept=None,
):
    site = resolve_center(center=center, lat=lat, lon=lon, water_class=water_class, centers_path=centers_path)
    observations, diagnostics = load_observations_for_center(
        site,
        observations_path=observations_path,
        source=source,
        start_date=start_date,
        end_date=end_date,
        buffer_m=buffer_m,
        fnu_to_tss_slope=fnu_to_tss_slope,
        fnu_to_tss_intercept=fnu_to_tss_intercept,
    )
    scenarios, confidence = _scenario_values(site, observations)
    confidence["source_mode"] = source
    confidence["buffer_m"] = buffer_m
    confidence["fnu_to_tss_calibration"] = _calibration_from_values(fnu_to_tss_slope, fnu_to_tss_intercept)
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
    fnu_to_tss_slope=None,
    fnu_to_tss_intercept=None,
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
        fnu_to_tss_slope=fnu_to_tss_slope,
        fnu_to_tss_intercept=fnu_to_tss_intercept,
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
        turbidity_values = [row.get("turbidity_fnu") for row in yearly_rows if row.get("turbidity_fnu") is not None]
        medians["turbidity_fnu"] = _round_optics(median(turbidity_values)) if turbidity_values else None
        ranges["turbidity_fnu"] = {
            "p25": _round_optics(_quantile(turbidity_values, 0.25)) if turbidity_values else None,
            "p75": _round_optics(_quantile(turbidity_values, 0.75)) if turbidity_values else None,
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
        confidence["fnu_to_tss_calibration"] = _calibration_from_values(fnu_to_tss_slope, fnu_to_tss_intercept)

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
    parser.add_argument("--fnu-to-tss-slope", default=None, type=float, help="Pendiente local para TSS = pendiente*FNU + intercepto.")
    parser.add_argument("--fnu-to-tss-intercept", default=None, type=float, help="Intercepto local para TSS = pendiente*FNU + intercepto.")
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
        fnu_to_tss_slope=args.fnu_to_tss_slope,
        fnu_to_tss_intercept=args.fnu_to_tss_intercept,
    )
    text = json.dumps(result, indent=4, ensure_ascii=False)
    if args.output:
        Path(args.output).write_text(text + "\n", encoding="utf-8")
    else:
        print(text)


if __name__ == "__main__":
    main()
