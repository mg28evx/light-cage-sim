#!/usr/bin/env python3
"""Replica el campo óptico del Trial 3 de Porter et al. (2005).

La salida cuantifica irradiancia artificial; el 18 % de crecimiento permanece
como resultado experimental observado y no se usa para calibrar el ray tracer.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
import sys

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "confgs" / "porter_2005_growth18_lit.json"
XML_PATH = ROOT / "uploaded_lamps" / "PORTER_2005_TRIAL3_SYNTHETIC_400W.xml"
FIT_SUMMARY_PATH = ROOT / "sensitivity" / "out" / "porter_2005" / "porter_fit_summary.json"
OUT_DIR = ROOT / "sensitivity" / "out" / "porter_trial3"
THRESHOLDS_W_M2 = (0.017, 0.1, 1.0)
DEPTHS_M = (1, 2, 3, 4, 6, 7, 8, 9, 10)


def photopic_v_app(wavelength_nm: np.ndarray) -> np.ndarray:
    wavelength_um = np.asarray(wavelength_nm, dtype=float) / 1000.0
    v = (1.019 * np.exp(-285.4 * (wavelength_um - 0.559) ** 2)
         - 0.092 * np.exp(-1250.0 * (wavelength_um - 0.450) ** 2))
    return np.clip(v, 0.0, 1.0)


def load_inputs() -> tuple[dict, dict]:
    return (
        json.loads(CONFIG_PATH.read_text(encoding="utf-8")),
        json.loads(FIT_SUMMARY_PATH.read_text(encoding="utf-8")),
    )


def set_lamp_ring(config: dict, ring_fraction: float) -> None:
    radius = float(config["env"]["radio"])
    center_x = float(config["env"]["x"]) / 2.0
    center_y = float(config["env"]["y"]) / 2.0
    ring_radius = radius * ring_fraction
    for lamp, phi in zip(config["lamps"], np.linspace(0.0, 2.0 * np.pi, 4, endpoint=False)):
        lamp["x"] = center_x + ring_radius * float(np.cos(phi))
        lamp["y"] = center_y + ring_radius * float(np.sin(phi))


def run_engine(config: dict, rays: int, seed: int) -> dict:
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from simulation_engine import SimulationEngine

    cfg = json.loads(json.dumps(config))
    cfg["rays"] = int(rays)
    cfg["target_depths"] = list(DEPTHS_M)
    engine = SimulationEngine()
    engine.load_file(XML_PATH.name, XML_PATH.read_text(encoding="utf-8"))
    np.random.seed(seed)
    return engine.run(cfg)


def grid_layer(layer: dict, config: dict, bins: int) -> dict:
    diameter_x = float(config["env"]["x"])
    diameter_y = float(config["env"]["y"])
    radius = float(config["env"]["radio"])
    center_x = diameter_x / 2.0
    center_y = diameter_y / 2.0
    x_edges = np.linspace(0.0, diameter_x, bins + 1)
    y_edges = np.linspace(0.0, diameter_y, bins + 1)
    x_centers = 0.5 * (x_edges[:-1] + x_edges[1:])
    y_centers = 0.5 * (y_edges[:-1] + y_edges[1:])
    X, Y = np.meshgrid(x_centers, y_centers, indexing="ij")
    mask = (X - center_x) ** 2 + (Y - center_y) ** 2 <= radius**2
    cell_area = (x_edges[1] - x_edges[0]) * (y_edges[1] - y_edges[0])

    x = np.asarray(layer.get("x", []), dtype=float)
    y = np.asarray(layer.get("y", []), dtype=float)
    values = np.asarray(layer.get("val", []), dtype=float)
    wavelengths = np.asarray(layer.get("wl", []), dtype=float)
    if len(values):
        radiant, _, _ = np.histogram2d(
            x, y, bins=[x_edges, y_edges], weights=values
        )
        luminous, _, _ = np.histogram2d(
            x, y, bins=[x_edges, y_edges],
            weights=values * 683.0 * photopic_v_app(wavelengths),
        )
        irradiance = radiant / cell_area
        illuminance = luminous / cell_area
    else:
        irradiance = np.zeros_like(X)
        illuminance = np.zeros_like(X)
    irradiance[~mask] = np.nan
    illuminance[~mask] = np.nan
    return {
        "x": X, "y": Y, "mask": mask, "cell_area": cell_area,
        "irradiance": irradiance, "illuminance": illuminance,
    }


def summarize_grid(depth_m: float, grid: dict, scenario: str) -> dict:
    values = grid["irradiance"][grid["mask"]]
    lux = grid["illuminance"][grid["mask"]]
    row = {
        "scenario": scenario,
        "depth_m": float(depth_m),
        "cell_area_m2": float(grid["cell_area"]),
        "valid_area_m2": float(len(values) * grid["cell_area"]),
        "plane_radiant_flux_W": float(np.sum(values) * grid["cell_area"]),
        "irradiance_mean_W_m2": float(np.mean(values)),
        "irradiance_p10_W_m2": float(np.quantile(values, 0.10)),
        "irradiance_median_W_m2": float(np.median(values)),
        "irradiance_p90_W_m2": float(np.quantile(values, 0.90)),
        "irradiance_p99_W_m2": float(np.quantile(values, 0.99)),
        "irradiance_max_grid_W_m2": float(np.max(values)),
        "illuminance_mean_lux": float(np.mean(lux)),
        "illuminance_median_lux": float(np.median(lux)),
    }
    for threshold in THRESHOLDS_W_M2:
        key = str(threshold).replace(".", "p")
        row[f"coverage_ge_{key}_pct"] = float(100.0 * np.mean(values >= threshold))
    return row


def analyze_run(result: dict, config: dict, bins: int, scenario: str,
                keep_grids: bool = False) -> tuple[list[dict], dict[int, dict]]:
    rows, grids = [], {}
    for depth in DEPTHS_M:
        grid = grid_layer(result.get(str(depth), {}), config, bins)
        rows.append(summarize_grid(depth, grid, scenario))
        if keep_grids:
            grids[depth] = grid
    return rows, grids


def write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def write_grid_csv(path: Path, grids: dict[int, dict]) -> None:
    fields = ["depth_m", "x_m", "y_m", "irradiance_W_m2", "illuminance_lux"]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for depth, grid in grids.items():
            for x, y, e, lux in zip(
                grid["x"][grid["mask"]], grid["y"][grid["mask"]],
                grid["irradiance"][grid["mask"]], grid["illuminance"][grid["mask"]],
            ):
                writer.writerow({
                    "depth_m": depth, "x_m": f"{x:.5f}", "y_m": f"{y:.5f}",
                    "irradiance_W_m2": f"{e:.9g}", "illuminance_lux": f"{lux:.9g}",
                })


def plot_nominal(grids: dict[int, dict], rows: list[dict], config: dict, out_dir: Path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.colors import LogNorm

    selected = (6, 8, 10)
    positive = np.concatenate([
        grids[d]["irradiance"][grids[d]["mask"]]
        for d in selected
    ])
    positive = positive[positive > 0]
    vmin = max(float(np.quantile(positive, 0.01)), 1e-5)
    vmax = float(np.quantile(positive, 0.995))
    fig, axes = plt.subplots(1, 3, figsize=(14, 4.6), constrained_layout=True)
    image = None
    for ax, depth in zip(axes, selected):
        grid = grids[depth]
        image = ax.pcolormesh(
            grid["x"], grid["y"], grid["irradiance"], shading="nearest",
            cmap="viridis", norm=LogNorm(vmin=vmin, vmax=vmax),
        )
        ax.scatter(
            [lamp["x"] for lamp in config["lamps"]],
            [lamp["y"] for lamp in config["lamps"]],
            marker="x", color="white", linewidth=1.2, s=28,
        )
        ax.set(title=f"Profundidad {depth} m", xlabel="X [m]", ylabel="Y [m]", aspect="equal")
    fig.colorbar(image, ax=axes, label="Irradiancia artificial [W/m²]", shrink=0.85)
    fig.suptitle("Porter 2005 Trial 3: cuatro luminarias de 400 W")
    fig.savefig(out_dir / "trial3_irradiance_maps.png", dpi=180)
    plt.close(fig)

    lower = [row for row in rows if row["depth_m"] >= 6]
    depths = np.asarray([row["depth_m"] for row in lower])
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.4), constrained_layout=True)
    axes[0].plot(depths, [row["irradiance_mean_W_m2"] for row in lower], "o-", label="Media")
    axes[0].plot(depths, [row["irradiance_median_W_m2"] for row in lower], "s-", label="Mediana")
    axes[0].set(yscale="log", xlabel="Profundidad [m]", ylabel="Irradiancia [W/m²]")
    axes[0].grid(True, which="both", ls=":", alpha=0.45)
    axes[0].legend()
    for threshold in THRESHOLDS_W_M2:
        key = str(threshold).replace(".", "p")
        axes[1].plot(
            depths, [row[f"coverage_ge_{key}_pct"] for row in lower], "o-",
            label=f"≥ {threshold:g} W/m²",
        )
    axes[1].set(xlabel="Profundidad [m]", ylabel="Cobertura del plano [%]", ylim=(0, 102))
    axes[1].grid(True, ls=":", alpha=0.45)
    axes[1].legend()
    fig.savefig(out_dir / "trial3_depth_coverage.png", dpi=180)
    plt.close(fig)


def plot_scenarios(rows: list[dict], out_dir: Path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(8.5, 5.2), constrained_layout=True)
    for scenario in sorted({row["scenario"] for row in rows}):
        subset = [row for row in rows if row["scenario"] == scenario and row["depth_m"] >= 6]
        ax.plot(
            [row["depth_m"] for row in subset],
            [row["coverage_ge_0p017_pct"] for row in subset],
            marker="o", label=scenario,
        )
    ax.set(
        xlabel="Profundidad [m]", ylabel="Cobertura ≥ 0,017 W/m² [%]",
        ylim=(0, 102), title="Sensibilidad óptica, geométrica y de layout",
    )
    ax.grid(True, ls=":", alpha=0.45)
    ax.legend(fontsize=8, ncol=2)
    fig.savefig(out_dir / "trial3_uncertainty_scenarios.png", dpi=180)
    plt.close(fig)


def make_scenario(base: dict, fit: dict, name: str) -> dict:
    cfg = json.loads(json.dumps(base))
    c_lo, c_hi = fit["beam_attenuation_c_90pct_CI_per_m"]
    if name == "optical_low":
        cfg["optics"]["c"] = cfg["optics"]["kd_fijo"] = c_hi
        cfg["kd_list"] = [c_hi]
        for lamp in cfg["lamps"]:
            lamp["efficiency"] = 0.25
    elif name == "optical_high":
        cfg["optics"]["c"] = cfg["optics"]["kd_fijo"] = c_lo
        cfg["kd_list"] = [c_lo]
        for lamp in cfg["lamps"]:
            lamp["efficiency"] = 0.31
    elif name == "layout_inner_R3":
        set_lamp_ring(cfg, 1.0 / 3.0)
    elif name == "layout_outer_2R3":
        set_lamp_ring(cfg, 2.0 / 3.0)
    elif name == "literal_diameter_80m":
        cfg["env"]["radio"] = 40.0
        cfg["env"]["x"] = cfg["env"]["y"] = 80.0
        set_lamp_ring(cfg, 0.5)
    return cfg


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rays", type=int, default=2_000_000)
    parser.add_argument("--scenario-rays", type=int, default=250_000)
    parser.add_argument("--bins", type=int, default=128)
    args = parser.parse_args()

    config, fit = load_inputs()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    nominal_result = run_engine(config, args.rays, seed=20020528)
    nominal_rows, nominal_grids = analyze_run(
        nominal_result, config, args.bins, "nominal", keep_grids=True
    )
    write_csv(OUT_DIR / "trial3_depth_summary.csv", nominal_rows)
    write_grid_csv(OUT_DIR / "trial3_irradiance_grid.csv", nominal_grids)
    plot_nominal(nominal_grids, nominal_rows, config, OUT_DIR)

    scenario_names = (
        "nominal", "optical_low", "optical_high", "layout_inner_R3",
        "layout_outer_2R3", "literal_diameter_80m",
    )
    scenario_rows = []
    for index, name in enumerate(scenario_names):
        cfg = make_scenario(config, fit, name)
        result = run_engine(cfg, args.scenario_rays, seed=3000 + index)
        rows, _ = analyze_run(result, cfg, args.bins, name)
        scenario_rows.extend(rows)
    write_csv(OUT_DIR / "trial3_uncertainty_scenarios.csv", scenario_rows)
    plot_scenarios(scenario_rows, OUT_DIR)

    lower_nominal = [row for row in nominal_rows if row["depth_m"] >= 6]
    summary = {
        "source": "Porter et al. 2005, FRDC 2001/246, Trial 3 and Appendix 3",
        "simulation_scope": "artificial irradiance only",
        "rays_nominal": args.rays,
        "rays_per_sensitivity_scenario": args.scenario_rays,
        "grid_bins_per_axis": args.bins,
        "lamp_count": len(config["lamps"]),
        "electrical_power_total_W": sum(lamp["power"] for lamp in config["lamps"]),
        "radiant_power_total_W": sum(
            lamp["power"] * lamp["efficiency"] for lamp in config["lamps"]
        ),
        "luminous_flux_total_lm": 4.0 * fit["luminous_flux_lm"],
        "artificial_light_duration_days": config["porter_growth_trial"]["artificial_light_duration_days"],
        "electrical_energy_161d_MWh": 4.0 * 400.0 * 24.0 * 161.0 / 1e6,
        "radiant_energy_161d_MWh": sum(
            lamp["power"] * lamp["efficiency"] for lamp in config["lamps"]
        ) * 24.0 * 161.0 / 1e6,
        "lower_half_depths_m": [row["depth_m"] for row in lower_nominal],
        "lower_half_mean_irradiance_by_depth_W_m2": [
            row["irradiance_mean_W_m2"] for row in lower_nominal
        ],
        "lower_half_median_irradiance_by_depth_W_m2": [
            row["irradiance_median_W_m2"] for row in lower_nominal
        ],
        "reported_growth_advantage_pct": 18.0,
        "terminal_mean_weight_ratio_difference_pct": 100.0 * (2280.0 / 1880.0 - 1.0),
        "uncertainty_classes": {
            "measurement_and_inverse_fit": "Appendix fit MAPE 20.8%; c 90% interval carried into scenarios",
            "lamp_absolute_output": "33-38 klm and 100-124 W visible per lamp technology prior",
            "spectrum": "synthetic 3700 K metal-halide surrogate; original SPD unavailable",
            "layout": "four positions unpublished; R/2 ring is nominal",
            "cage": "80 m interpreted as perimeter; literal diameter retained as sensitivity case",
            "biological": "single lit/control cages, no raw weights, temperature series or dose-response model",
        },
        "diagnostic_threshold_warning": "0.017, 0.1 and 1 W/m2 are not validated Trial 3 growth thresholds",
    }
    (OUT_DIR / "trial3_replication_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
