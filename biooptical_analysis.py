import csv
import io
import math
from copy import deepcopy

import numpy as np


DEFAULT_BANDS = {
    "blue": [400.0, 500.0],
    "green": [500.0, 600.0],
    "red": [600.0, 700.0],
}

DEFAULT_THRESHOLDS_W_M2 = [0.054, 0.54, 5.4, 8.7]
DEFAULT_SPECTRAL_WEIGHTS = {"blue": 1.0, "green": 0.7, "red": 0.2}
DEFAULT_LARVAL_PROFILES = ["surface_strong", "surface_moderate", "uniform_0_15"]
DEFAULT_FISH_PROFILES = [
    "day_surface_feeding",
    "day_distributed",
    "night_lamp_centered",
    "night_deep_lamp",
    "uniform_0_15",
]


LAYER_COLUMNS = [
    "scenario_id", "lamp_id", "lamp_type", "lamp_depth_m", "beam_orientation",
    "layer_top_m", "layer_bottom_m", "layer_mid_m", "volume_m3",
    "E_total_mean_W_m2", "E_total_median_W_m2", "E_total_p90_W_m2",
    "E_total_p95_W_m2", "E_total_max_W_m2",
    "E_blue_mean_W_m2", "E_green_mean_W_m2", "E_red_mean_W_m2",
    "E_blue_p90_W_m2", "E_green_p90_W_m2", "E_red_p90_W_m2",
]


GRID_COLUMNS = [
    "scenario_id", "x_m", "y_m", "z_m", "cell_volume_m3",
    "E_total_W_m2", "E_blue_W_m2", "E_green_W_m2", "E_red_W_m2",
]

PARAMETER_COLUMNS = ["parameter", "value", "unit", "note"]


INDEX_COLUMNS = [
    "scenario_id", "larval_profile", "fish_profile", "fish_sigma_m",
    "w_blue", "w_green", "w_red", "IC",
    "IE_pez_total", "IE_pez_blue", "IE_pez_green", "IE_pez_red",
    "IE_contacto_total", "IE_contacto_blue", "IE_contacto_green", "IE_contacto_red",
    "IE_contacto_spectral", "normalization_base", "relative_metric", "relative_value",
]


def analysis_defaults(user_config=None):
    cfg = deepcopy(user_config or {})
    cfg.setdefault("enabled", False)
    cfg.setdefault("depth_min_m", 0.0)
    cfg.setdefault("depth_max_m", 15.0)
    cfg.setdefault("layer_height_m", 1.0)
    cfg.setdefault("grid_dx_m", 1.0)
    cfg.setdefault("grid_dy_m", 1.0)
    cfg.setdefault("tally_step_m", 0.5)
    cfg.setdefault("bands", deepcopy(DEFAULT_BANDS))
    cfg.setdefault("thresholds_W_m2", list(DEFAULT_THRESHOLDS_W_M2))
    cfg.setdefault("spectral_weights", deepcopy(DEFAULT_SPECTRAL_WEIGHTS))
    cfg.setdefault("larval_profiles", list(DEFAULT_LARVAL_PROFILES))
    cfg.setdefault("fish_profiles", list(DEFAULT_FISH_PROFILES))
    cfg.setdefault("fish_sigma_m", 2.0)
    cfg.setdefault("normalize_against", "")
    cfg.setdefault("grid_cells_csv", False)
    return cfg


def build_layers(config):
    cfg = analysis_defaults(config)
    z0 = float(cfg["depth_min_m"])
    z1 = float(cfg["depth_max_m"])
    dz = float(cfg["layer_height_m"])
    if dz <= 0:
        raise ValueError("analysis.layer_height_m debe ser > 0.")
    if z1 <= z0:
        raise ValueError("analysis.depth_max_m debe ser mayor que depth_min_m.")
    edges = list(np.arange(z0, z1, dz))
    if not edges or abs(edges[0] - z0) > 1e-9:
        edges.insert(0, z0)
    if abs(edges[-1] - z1) > 1e-9:
        edges.append(z1)
    edges = np.array(edges, dtype=float)
    if np.any(np.diff(edges) <= 0):
        raise ValueError("Las capas deben cubrir el rango sin solapamientos.")
    return [{"top": float(edges[i]), "bottom": float(edges[i + 1]), "mid": float(0.5 * (edges[i] + edges[i + 1]))}
            for i in range(len(edges) - 1)]


def validate_analysis_config(config):
    cfg = analysis_defaults(config)
    build_layers(cfg)
    bands = cfg.get("bands", {})
    ranges = []
    for name, bounds in bands.items():
        if len(bounds) != 2:
            raise ValueError(f"La banda espectral {name} debe tener dos límites.")
        lo, hi = float(bounds[0]), float(bounds[1])
        if hi <= lo:
            raise ValueError(f"La banda espectral {name} tiene límites inválidos.")
        ranges.append((lo, hi, name))
    ranges.sort()
    for i in range(1, len(ranges)):
        if ranges[i][0] < ranges[i - 1][1]:
            raise ValueError(f"Las bandas espectrales {ranges[i - 1][2]} y {ranges[i][2]} se solapan.")
    for threshold in cfg.get("thresholds_W_m2", []):
        if float(threshold) < 0:
            raise ValueError("Los umbrales de irradiancia no pueden ser negativos.")
    for band, weight in cfg.get("spectral_weights", {}).items():
        if band not in bands:
            raise ValueError(f"Peso espectral definido para banda inexistente: {band}.")
        if float(weight) < 0:
            raise ValueError("Los pesos espectrales deben ser no negativos.")
    return cfg


def configure_volume_tally(sim_config, analysis_config):
    cfg = validate_analysis_config(analysis_config)
    env = sim_config.get("env", {})
    env_x = float(env.get("x") or 10.0)
    env_y = float(env.get("y") or 10.0)
    depth_min = float(cfg["depth_min_m"])
    depth_max = float(cfg["depth_max_m"])
    dx = float(cfg.get("grid_dx_m", 1.0))
    dy = float(cfg.get("grid_dy_m", 1.0))
    dz = float(cfg["layer_height_m"])
    if dx <= 0 or dy <= 0:
        raise ValueError("analysis.grid_dx_m y analysis.grid_dy_m deben ser > 0.")
    volume_cfg = {
        "enabled": True,
        "x_min_m": 0.0,
        "x_max_m": env_x,
        "y_min_m": 0.0,
        "y_max_m": env_y,
        "depth_min_m": depth_min,
        "depth_max_m": depth_max,
        "dx_m": dx,
        "dy_m": dy,
        "dz_m": dz,
        "step_m": float(cfg.get("tally_step_m", max(min(dx, dy, dz) * 0.5, 0.1))),
        "bands": cfg["bands"],
    }
    sim_config["volume_tally"] = volume_cfg
    mids = [layer["mid"] for layer in build_layers(cfg)]
    existing = [float(v) for v in sim_config.get("target_depths", [])]
    sim_config["target_depths"] = sorted(set(existing + mids), reverse=True)
    return sim_config


def _lamp_metadata(scenario_id, scenario_meta, sim_config):
    lamps = sim_config.get("lamps", [])
    ids = []
    depths = []
    orientations = []
    types = []
    for idx, lamp in enumerate(lamps):
        ids.append(str(lamp.get("label") or lamp.get("xml") or f"L{idx + 1}"))
        types.append(str(lamp.get("type") or "submerged"))
        try:
            depths.append(float(lamp.get("z", 0.0)))
        except (TypeError, ValueError):
            pass
        rx = float(lamp.get("rot_x", 0.0) or 0.0)
        ry = float(lamp.get("rot_y", 0.0) or 0.0)
        rz = float(lamp.get("rot_z", 0.0) or 0.0)
        orientations.append(_orientation_label(rx, ry, rz))
    meta_depth = scenario_meta.get("lamp_depth_m")
    lamp_depth = float(meta_depth) if meta_depth not in (None, "") else (float(np.mean(depths)) if depths else 0.0)
    return {
        "scenario_id": scenario_id,
        "lamp_id": scenario_meta.get("lamp_id") or "+".join(ids),
        "lamp_type": scenario_meta.get("lamp_type") or "+".join(sorted(set(types))) or "unknown",
        "lamp_depth_m": lamp_depth,
        "beam_orientation": scenario_meta.get("beam_orientation") or "+".join(sorted(set(orientations))) or "unknown",
    }


def _orientation_label(rx, ry, rz):
    if abs(rx) < 1e-6 and abs(ry) < 1e-6:
        return "down"
    if abs(abs(rx) - 90.0) < 20.0 or abs(abs(ry) - 90.0) < 20.0:
        return "horizontal"
    if rx > 20.0 or ry > 20.0:
        return "tilted"
    return "down"


def summarize_volume_tally(volume_tally, analysis_config, scenario_id, sim_config, scenario_meta=None):
    cfg = validate_analysis_config(analysis_config)
    meta = _lamp_metadata(scenario_id, scenario_meta or {}, sim_config)
    thresholds = [float(v) for v in cfg.get("thresholds_W_m2", DEFAULT_THRESHOLDS_W_M2)]
    rows = []
    threshold_cols = [f"frac_volume_E_gt_{_threshold_label(v)}" for v in thresholds]

    E_total = np.asarray(volume_tally["E_total_W_m2"], dtype=float)
    E_bands = {band: np.asarray(volume_tally.get(f"E_{band}_W_m2", np.zeros_like(E_total)), dtype=float)
               for band in ("blue", "green", "red")}
    valid = np.asarray(volume_tally["valid_mask"], dtype=bool)
    depth_edges = np.asarray(volume_tally["depth_edges_m"], dtype=float)
    cell_volume = np.asarray(volume_tally["cell_volume_m3"], dtype=float)
    if cell_volume.ndim == 0:
        cell_volume = np.full_like(E_total, float(cell_volume), dtype=float)

    if np.any(~np.isfinite(E_total)) or any(np.any(~np.isfinite(arr)) for arr in E_bands.values()):
        raise ValueError("La grilla volumétrica contiene NaN o infinitos.")
    if np.any(E_total < -1e-12) or any(np.any(arr < -1e-12) for arr in E_bands.values()):
        raise ValueError("La grilla volumétrica contiene irradiancias negativas.")

    for iz in range(E_total.shape[0]):
        layer_valid = valid[iz]
        vals = E_total[iz][layer_valid]
        if vals.size == 0:
            vals = np.array([0.0])
        row = {
            **meta,
            "layer_top_m": float(depth_edges[iz]),
            "layer_bottom_m": float(depth_edges[iz + 1]),
            "layer_mid_m": float(0.5 * (depth_edges[iz] + depth_edges[iz + 1])),
            "volume_m3": float(np.sum(cell_volume[iz][layer_valid])),
            "E_total_mean_W_m2": float(np.mean(vals)),
            "E_total_median_W_m2": float(np.median(vals)),
            "E_total_p90_W_m2": float(np.percentile(vals, 90)),
            "E_total_p95_W_m2": float(np.percentile(vals, 95)),
            "E_total_max_W_m2": float(np.max(vals)),
        }
        for band in ("blue", "green", "red"):
            bvals = E_bands[band][iz][layer_valid]
            if bvals.size == 0:
                bvals = np.array([0.0])
            row[f"E_{band}_mean_W_m2"] = float(np.mean(bvals))
            row[f"E_{band}_p90_W_m2"] = float(np.percentile(bvals, 90))
        for threshold, col in zip(thresholds, threshold_cols):
            row[col] = float(np.mean(vals > threshold)) if vals.size else 0.0
        rows.append(row)
    return rows, threshold_cols


def volume_grid_rows(volume_tally, scenario_id):
    E_total = np.asarray(volume_tally["E_total_W_m2"], dtype=float)
    bands = {band: np.asarray(volume_tally.get(f"E_{band}_W_m2", np.zeros_like(E_total)), dtype=float)
             for band in ("blue", "green", "red")}
    valid = np.asarray(volume_tally["valid_mask"], dtype=bool)
    x_centers = np.asarray(volume_tally["x_centers_m"], dtype=float)
    y_centers = np.asarray(volume_tally["y_centers_m"], dtype=float)
    z_centers = np.asarray(volume_tally["depth_centers_m"], dtype=float)
    cell_volume = np.asarray(volume_tally["cell_volume_m3"], dtype=float)
    if cell_volume.ndim == 0:
        cell_volume = np.full_like(E_total, float(cell_volume), dtype=float)
    rows = []
    for iz, z in enumerate(z_centers):
        for iy, y in enumerate(y_centers):
            for ix, x in enumerate(x_centers):
                if not valid[iz, iy, ix]:
                    continue
                rows.append({
                    "scenario_id": scenario_id,
                    "x_m": float(x),
                    "y_m": float(y),
                    "z_m": float(z),
                    "cell_volume_m3": float(cell_volume[iz, iy, ix]),
                    "E_total_W_m2": float(E_total[iz, iy, ix]),
                    "E_blue_W_m2": float(bands["blue"][iz, iy, ix]),
                    "E_green_W_m2": float(bands["green"][iz, iy, ix]),
                    "E_red_W_m2": float(bands["red"][iz, iy, ix]),
                })
    return rows


def profile_distribution(profile_name, layers, kind, lamp_depth_m=5.0, beam_orientation="down", sigma_m=2.0):
    mids = np.array([layer["mid"] for layer in layers], dtype=float)
    name = str(profile_name)
    if kind == "larval":
        if name == "surface_strong":
            weights = np.where(mids < 3.0, 1.0, np.where(mids < 10.0, 0.25, 0.05))
        elif name == "surface_moderate":
            weights = np.exp(-mids / 5.5) + 0.05
        elif name == "uniform_0_15":
            weights = np.ones_like(mids)
        else:
            raise ValueError(f"Perfil larval no reconocido: {name}.")
    else:
        if name == "day_surface_feeding":
            weights = np.exp(-mids / 2.5) + 0.03
        elif name == "day_distributed":
            weights = np.exp(-mids / 8.0) + 0.15
        elif name == "night_lamp_centered":
            weights = np.exp(-0.5 * ((mids - float(lamp_depth_m)) / max(float(sigma_m), 1e-6)) ** 2)
        elif name == "night_deep_lamp":
            center = float(lamp_depth_m) + (2.0 if str(beam_orientation).lower().find("down") >= 0 else 0.5)
            weights = np.exp(-0.5 * ((mids - center) / max(float(sigma_m), 1e-6)) ** 2)
        elif name == "uniform_0_15":
            weights = np.ones_like(mids)
        else:
            raise ValueError(f"Perfil de pez no reconocido: {name}.")
    total = float(np.sum(weights))
    if total <= 0:
        raise ValueError(f"El perfil {name} no tiene masa positiva.")
    return weights / total


def compute_biological_indices(layer_rows_by_scenario, analysis_config):
    cfg = validate_analysis_config(analysis_config)
    larval_profiles = cfg.get("larval_profiles", DEFAULT_LARVAL_PROFILES)
    fish_profiles = cfg.get("fish_profiles", DEFAULT_FISH_PROFILES)
    weights = {k: float(v) for k, v in cfg.get("spectral_weights", DEFAULT_SPECTRAL_WEIGHTS).items()}
    rows = []
    metric_lookup = {}
    for scenario_id, layer_rows in layer_rows_by_scenario.items():
        sorted_rows = sorted(layer_rows, key=lambda r: float(r["layer_mid_m"]))
        layers = [{"top": r["layer_top_m"], "bottom": r["layer_bottom_m"], "mid": r["layer_mid_m"]}
                  for r in sorted_rows]
        E = {name: np.array([float(r[f"E_{name}_mean_W_m2"]) for r in sorted_rows], dtype=float)
             for name in ("blue", "green", "red")}
        E["total"] = np.array([float(r["E_total_mean_W_m2"]) for r in sorted_rows], dtype=float)
        lamp_depth = float(sorted_rows[0].get("lamp_depth_m", 5.0)) if sorted_rows else 5.0
        orientation = str(sorted_rows[0].get("beam_orientation", "down")) if sorted_rows else "down"
        for larval in larval_profiles:
            C = profile_distribution(larval, layers, "larval")
            if not math.isclose(float(np.sum(C)), 1.0, rel_tol=1e-9, abs_tol=1e-9):
                raise ValueError(f"C_i no suma 1 para {larval}.")
            for fish in fish_profiles:
                F = profile_distribution(
                    fish, layers, "fish",
                    lamp_depth_m=lamp_depth,
                    beam_orientation=orientation,
                    sigma_m=float(cfg.get("fish_sigma_m", 2.0)),
                )
                if not math.isclose(float(np.sum(F)), 1.0, rel_tol=1e-9, abs_tol=1e-9):
                    raise ValueError(f"F_i no suma 1 para {fish}.")
                contact = C * F
                metrics = {
                    "IC": float(np.sum(contact)),
                    "IE_pez_total": float(np.sum(F * E["total"])),
                    "IE_pez_blue": float(np.sum(F * E["blue"])),
                    "IE_pez_green": float(np.sum(F * E["green"])),
                    "IE_pez_red": float(np.sum(F * E["red"])),
                    "IE_contacto_total": float(np.sum(contact * E["total"])),
                    "IE_contacto_blue": float(np.sum(contact * E["blue"])),
                    "IE_contacto_green": float(np.sum(contact * E["green"])),
                    "IE_contacto_red": float(np.sum(contact * E["red"])),
                    "IE_contacto_spectral": float(np.sum(contact * (
                        weights.get("blue", 0.0) * E["blue"] +
                        weights.get("green", 0.0) * E["green"] +
                        weights.get("red", 0.0) * E["red"]
                    ))),
                }
                base_row = {
                    "scenario_id": scenario_id,
                    "larval_profile": larval,
                    "fish_profile": fish,
                    "fish_sigma_m": float(cfg.get("fish_sigma_m", 2.0)),
                    "w_blue": weights.get("blue", 0.0),
                    "w_green": weights.get("green", 0.0),
                    "w_red": weights.get("red", 0.0),
                    **metrics,
                    "normalization_base": cfg.get("normalize_against", ""),
                    "relative_metric": "",
                    "relative_value": "",
                }
                rows.append(base_row)
                metric_lookup[(scenario_id, larval, fish)] = metrics

    base_id = str(cfg.get("normalize_against", "") or "")
    if base_id:
        scenario_ids = set(layer_rows_by_scenario.keys())
        if base_id not in scenario_ids:
            raise ValueError(f"El escenario base para normalización no existe: {base_id}.")
        extra_rows = []
        for row in rows:
            scenario_id = row["scenario_id"]
            if scenario_id == base_id:
                continue
            key = (scenario_id, row["larval_profile"], row["fish_profile"])
            base_key = (base_id, row["larval_profile"], row["fish_profile"])
            for metric, value in metric_lookup[key].items():
                base_value = metric_lookup[base_key].get(metric, 0.0)
                ratio = value / base_value if base_value > 0 else ""
                extra_rows.append({
                    "scenario_id": scenario_id,
                    "larval_profile": row["larval_profile"],
                    "fish_profile": row["fish_profile"],
                    "fish_sigma_m": row["fish_sigma_m"],
                    "w_blue": row["w_blue"],
                    "w_green": row["w_green"],
                    "w_red": row["w_red"],
                    "IC": row["IC"],
                    "IE_pez_total": row["IE_pez_total"],
                    "IE_pez_blue": row["IE_pez_blue"],
                    "IE_pez_green": row["IE_pez_green"],
                    "IE_pez_red": row["IE_pez_red"],
                    "IE_contacto_total": row["IE_contacto_total"],
                    "IE_contacto_blue": row["IE_contacto_blue"],
                    "IE_contacto_green": row["IE_contacto_green"],
                    "IE_contacto_red": row["IE_contacto_red"],
                    "IE_contacto_spectral": row["IE_contacto_spectral"],
                    "normalization_base": base_id,
                    "relative_metric": metric,
                    "relative_value": ratio,
                })
        rows.extend(extra_rows)
    return rows


def rows_to_csv(rows, columns):
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=columns, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    return output.getvalue()


def analysis_parameters_rows(analysis_config):
    cfg = analysis_defaults(analysis_config)
    rows = [
        {
            "parameter": "depth_min_m",
            "value": cfg["depth_min_m"],
            "unit": "m",
            "note": "Límite superior del rango vertical analizado, como profundidad desde superficie.",
        },
        {
            "parameter": "depth_max_m",
            "value": cfg["depth_max_m"],
            "unit": "m",
            "note": "Límite inferior del rango vertical analizado, como profundidad desde superficie.",
        },
        {
            "parameter": "layer_height_m",
            "value": cfg["layer_height_m"],
            "unit": "m",
            "note": "Espesor vertical de cada capa resumida.",
        },
        {
            "parameter": "grid_dx_m",
            "value": cfg.get("grid_dx_m", 1.0),
            "unit": "m",
            "note": "Resolución horizontal de celda en eje X para tally volumétrico.",
        },
        {
            "parameter": "grid_dy_m",
            "value": cfg.get("grid_dy_m", 1.0),
            "unit": "m",
            "note": "Resolución horizontal de celda en eje Y para tally volumétrico.",
        },
        {
            "parameter": "tally_step_m",
            "value": cfg.get("tally_step_m", 0.5),
            "unit": "m",
            "note": "Paso de integración a lo largo del rayo para acumular energía en celdas.",
        },
        {
            "parameter": "fish_sigma_m",
            "value": cfg.get("fish_sigma_m", 2.0),
            "unit": "m",
            "note": "Dispersión vertical asumida del pez alrededor del centro nocturno inducido por lámpara.",
        },
        {
            "parameter": "spectral_weight_blue",
            "value": cfg["spectral_weights"].get("blue", 0.0),
            "unit": "adimensional",
            "note": "Peso exploratorio para irradiancia azul 400-500 nm en IE_contacto_spectral.",
        },
        {
            "parameter": "spectral_weight_green",
            "value": cfg["spectral_weights"].get("green", 0.0),
            "unit": "adimensional",
            "note": "Peso exploratorio para irradiancia verde 500-600 nm en IE_contacto_spectral.",
        },
        {
            "parameter": "spectral_weight_red",
            "value": cfg["spectral_weights"].get("red", 0.0),
            "unit": "adimensional",
            "note": "Peso exploratorio para irradiancia roja 600-700 nm en IE_contacto_spectral.",
        },
        {
            "parameter": "thresholds_W_m2",
            "value": ";".join(str(v) for v in cfg.get("thresholds_W_m2", [])),
            "unit": "W/m2",
            "note": "Anclas experimentales configurables para fracción de volumen; no son límites biológicos universales.",
        },
        {
            "parameter": "larval_profiles",
            "value": ";".join(cfg.get("larval_profiles", [])),
            "unit": "perfil",
            "note": "Perfiles C(z) evaluados; cada distribución se normaliza para sumar 1.",
        },
        {
            "parameter": "fish_profiles",
            "value": ";".join(cfg.get("fish_profiles", [])),
            "unit": "perfil",
            "note": "Perfiles F(z) evaluados; cada distribución se normaliza para sumar 1.",
        },
        {
            "parameter": "normalize_against",
            "value": cfg.get("normalize_against", ""),
            "unit": "scenario_id",
            "note": "Escenario base usado para índices relativos normalizados.",
        },
    ]
    for band, bounds in cfg.get("bands", {}).items():
        rows.append({
            "parameter": f"band_{band}",
            "value": f"{bounds[0]}-{bounds[1]}",
            "unit": "nm",
            "note": "Rango espectral integrado desde SPD real del archivo TM-33.",
        })
    return rows


def build_outputs(layer_rows_by_scenario, analysis_config, grid_rows=None):
    threshold_cols = []
    for threshold in analysis_defaults(analysis_config).get("thresholds_W_m2", DEFAULT_THRESHOLDS_W_M2):
        threshold_cols.append(f"frac_volume_E_gt_{_threshold_label(float(threshold))}")
    layer_rows = []
    for rows in layer_rows_by_scenario.values():
        layer_rows.extend(rows)
    index_rows = compute_biological_indices(layer_rows_by_scenario, analysis_config)
    parameter_rows = analysis_parameters_rows(analysis_config)
    layer_csv = rows_to_csv(layer_rows, LAYER_COLUMNS + threshold_cols)
    indices_csv = rows_to_csv(index_rows, INDEX_COLUMNS)
    parameters_csv = rows_to_csv(parameter_rows, PARAMETER_COLUMNS)
    grid_csv = rows_to_csv(grid_rows or [], GRID_COLUMNS) if grid_rows else ""
    plots = build_plots(layer_rows_by_scenario, index_rows)
    return {
        "layer_rows": layer_rows,
        "index_rows": index_rows,
        "parameter_rows": parameter_rows,
        "grid_rows": grid_rows or [],
        "scenario_ids": list(layer_rows_by_scenario.keys()),
        "layer_summary_csv": layer_csv,
        "biological_indices_csv": indices_csv,
        "analysis_parameters_csv": parameters_csv,
        "grid_cells_csv": grid_csv,
        "plots": plots,
        "notes": interpretation_notes(),
    }


def build_plots(layer_rows_by_scenario, index_rows):
    try:
        import matplotlib.pyplot as plt
        import plotter
    except ImportError:
        return {}
    plotter.setup_matplotlib()
    plots = {}
    if layer_rows_by_scenario:
        fig, ax = plt.subplots(figsize=(7.5, 4.5))
        for scenario_id, rows in layer_rows_by_scenario.items():
            rows_s = sorted(rows, key=lambda r: float(r["layer_mid_m"]))
            ax.plot([r["E_total_mean_W_m2"] for r in rows_s],
                    [r["layer_mid_m"] for r in rows_s], marker="o", label=scenario_id)
        ax.invert_yaxis()
        ax.set_xlabel("Irradiancia media simulada [W/m²]")
        ax.set_ylabel("Profundidad [m]")
        ax.set_title("Irradiancia simulada por capa")
        ax.grid(True, alpha=0.25)
        ax.legend(fontsize=8)
        plots["vertical_irradiance_total"] = plotter.get_base64_image(fig)

        fig, ax = plt.subplots(figsize=(8.5, 4.8))
        line_styles = ["-", "--", ":", "-."]
        for s_idx, (scenario_id, rows) in enumerate(layer_rows_by_scenario.items()):
            rows_s = sorted(rows, key=lambda r: float(r["layer_mid_m"]))
            for band, color in [("blue", "#1f77b4"), ("green", "#2ca02c"), ("red", "#d62728")]:
                ax.plot(
                    [r[f"E_{band}_mean_W_m2"] for r in rows_s],
                    [r["layer_mid_m"] for r in rows_s],
                    marker="o",
                    color=color,
                    linestyle=line_styles[s_idx % len(line_styles)],
                    alpha=0.9,
                    label=f"{scenario_id} {band}",
                )
        ax.invert_yaxis()
        ax.set_xlabel("Irradiancia media por banda [W/m²]")
        ax.set_ylabel("Profundidad [m]")
        ax.set_title("Irradiancia simulada por banda y escenario")
        ax.grid(True, alpha=0.25)
        ax.legend(fontsize=7, ncol=2)
        plots["vertical_irradiance_bands"] = plotter.get_base64_image(fig)

        scenario_ids = list(layer_rows_by_scenario.keys())
        depths = sorted({float(r["layer_mid_m"]) for rows in layer_rows_by_scenario.values() for r in rows})
        matrix = np.zeros((len(depths), len(scenario_ids)))
        for j, scenario_id in enumerate(scenario_ids):
            by_depth = {float(r["layer_mid_m"]): float(r["E_total_mean_W_m2"]) for r in layer_rows_by_scenario[scenario_id]}
            matrix[:, j] = [by_depth.get(d, 0.0) for d in depths]
        fig_width = max(7.5, 1.4 * len(scenario_ids) + 5.0)
        fig, ax = plt.subplots(figsize=(fig_width, 4.8))
        im = ax.imshow(matrix, aspect="auto", origin="upper")
        ax.set_xticks(range(len(scenario_ids)))
        ax.set_xticklabels(scenario_ids, rotation=30, ha="right", fontsize=8)
        ax.set_yticks(range(len(depths)))
        ax.set_yticklabels([f"{d:.1f}" for d in depths])
        ax.set_ylabel("Profundidad [m]")
        ax.set_title(f"Irradiancia simulada por capa y escenario (n={len(scenario_ids)})")
        if len(scenario_ids) > 1:
            ax.set_xticks(np.arange(-0.5, len(scenario_ids), 1), minor=True)
            ax.grid(which="minor", axis="x", color="white", linewidth=1.2)
            ax.tick_params(which="minor", bottom=False)
        fig.colorbar(im, ax=ax, label="W/m²")
        plots["scenario_depth_heatmap"] = plotter.get_base64_image(fig)

    compact = [r for r in index_rows if not r.get("relative_metric")]
    if compact:
        selected = compact[: min(8, len(compact))]
        labels = [f"{r['scenario_id']}\n{r['larval_profile']}\n{r['fish_profile']}" for r in selected]
        vals = [r["IE_contacto_spectral"] for r in selected]
        fig, ax = plt.subplots(figsize=(8.5, 4.8))
        ax.bar(range(len(vals)), vals, color="#1f77b4")
        ax.set_xticks(range(len(vals)))
        ax.set_xticklabels(labels, rotation=35, ha="right", fontsize=7)
        ax.set_ylabel("Índice relativo [W/m² ponderado]")
        ax.set_title("Índice relativo de exposición lumínica en zona de contacto")
        ax.grid(axis="y", alpha=0.25)
        plots["contact_spectral_index"] = plotter.get_base64_image(fig)
    return plots


def interpretation_notes():
    return [
        "El simulador óptico calcula irradiancia radiométrica simulada en W/m²; el módulo biológico calcula índices relativos derivados.",
        "IC, IE_pez, IE_contacto e IE_contacto_spectral no son probabilidad de infección ni abundancia esperada.",
        "Los pesos espectrales por defecto son exploratorios y deben usarse sólo para comparación relativa entre escenarios.",
        "Los umbrales 0.054, 0.54, 5.4 y 8.7 W/m² son anclas experimentales configurables, no límites biológicos universales.",
        "La luz se modela como modulador secundario mediado principalmente por F(z); salinidad, temperatura, circulación y presión larval deben evaluarse aparte.",
    ]


def _threshold_label(value):
    return str(value).replace(".", "_").replace("-", "neg_")
