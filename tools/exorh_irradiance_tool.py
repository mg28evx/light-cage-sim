#!/usr/bin/env python3
"""Compara irradiancia pineal ponderada por exorrodopsina en una jaula.

La herramienta reutiliza ``SimulationEngine`` de light-cage-sim. El motor
resuelve la distribución angular, la propagación y la ventana de recepción
pineal; este módulo pondera espectralmente cada contribución con un nomograma
A1 de exorrodopsina y agrega el resultado sobre un plano horizontal.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.colors as mcolors
import matplotlib.pyplot as plt
import numpy as np
from scipy.ndimage import gaussian_filter


COLORS = ["#007FA8", "#E0A800", "#7A4E9D"]


def exorh_sensitivity(wavelength_nm: np.ndarray, lmax_nm: float = 500.0) -> np.ndarray:
    """Nomograma A1 de Govardovskii, normalizado a uno en su máximo."""
    lam = np.asarray(wavelength_nm, dtype=float)
    x = lmax_nm / lam
    a = 0.8795 + 0.0459 * np.exp(-((lmax_nm - 300.0) ** 2) / 11940.0)
    alpha = 1.0 / (
        np.exp(69.7 * (a - x))
        + np.exp(28.0 * (0.922 - x))
        + np.exp(-14.9 * (1.104 - x))
        + 0.674
    )
    beta = 0.26 * np.exp(
        -((lam - (189.0 + 0.315 * lmax_nm)) / (-40.5 + 0.195 * lmax_nm)) ** 2
    )
    response = alpha + beta
    return response / np.nanmax(response)


def ring_positions(count: int, center: float, radius: float) -> list[tuple[float, float]]:
    angles = np.linspace(0.0, 2.0 * np.pi, count, endpoint=False) + np.pi / 6.0
    return [(center + radius * np.cos(a), center + radius * np.sin(a)) for a in angles]


def simulate_source(
    engine_cls,
    parser_cls,
    label: str,
    xml_path: Path,
    *,
    cage_side_m: float,
    lamp_depth_m: float,
    plane_depth_m: float,
    ring_radius_m: float,
    base_lamps: int,
    kd_m_inv: float,
    target_w_m2: float,
    grid_cell_m: float,
    rays: int,
    seed: int,
    cycle_hours: float,
    diesel_l_per_kwh: float,
    diesel_price_clp_l: float,
) -> dict:
    content = xml_path.read_text(encoding="utf-8")
    parser = parser_cls(content)
    electrical_w = float(parser.get_electrical_power())
    radiant_w = float(parser.get_radiant_power())
    efficiency = radiant_w / electrical_w
    center = cage_side_m / 2.0
    positions = ring_positions(base_lamps, center, ring_radius_m)

    lamps = [
        {
            "xml": xml_path.name,
            "x": x,
            "y": y,
            "z": lamp_depth_m,
            "power": electrical_w,
            "dim": 1.0,
            "efficiency": efficiency,
            "rot_x": 0.0,
            "rot_y": 0.0,
            "rot_z": 0.0,
        }
        for x, y in positions
    ]
    config = {
        "env": {
            "type": "jaula",
            "shape": "rect",
            "x": cage_side_m,
            "y": cage_side_m,
            "z": max(plane_depth_m + 3.0, 20.0),
            "n1": 1.0,
            "n2": 1.333,
        },
        "optics": {
            "mode": "kd_fijo",
            "kd_fijo": kd_m_inv,
            "atten_coef_type": "kd",
        },
        "target_depths": [plane_depth_m],
        "rays": rays,
        "source_model": "point",
        "irradiance_type": "pineal",
        "mu_max": 85.0,
        "normalize_pineal": True,
        "lamps": lamps,
    }

    np.random.seed(seed)
    engine = engine_cls()
    if not engine.load_file(xml_path.name, content):
        raise RuntimeError(f"No fue posible cargar {xml_path}")
    result = engine.run(config)[str(plane_depth_m)]
    x = np.asarray(result["x"], dtype=float)
    y = np.asarray(result["y"], dtype=float)
    values = np.asarray(result["val"], dtype=float)
    wavelengths = np.asarray(result["wl"], dtype=float)
    dup_values = values * exorh_sensitivity(wavelengths)

    edges = np.arange(0.0, cage_side_m + grid_cell_m * 0.5, grid_cell_m)
    if edges[-1] < cage_side_m:
        edges = np.append(edges, cage_side_m)
    hist, _, _ = np.histogram2d(x, y, bins=[edges, edges], weights=dup_values)
    dx = np.diff(edges)
    dy = np.diff(edges)
    cell_area = dy[:, None] * dx[None, :]
    field = hist.T / cell_area
    centers = 0.5 * (edges[:-1] + edges[1:])
    xx, yy = np.meshgrid(centers, centers)
    mask = np.ones_like(field, dtype=bool)
    mean_base = float(np.mean(field[mask]))
    mean_per_lamp = mean_base / base_lamps
    lamps_required = int(math.ceil(target_w_m2 / mean_per_lamp))
    mean_achieved = mean_per_lamp * lamps_required
    electrical_system_kw = lamps_required * electrical_w / 1000.0
    annual_kwh = electrical_system_kw * cycle_hours
    fuel_l = annual_kwh * diesel_l_per_kwh
    cost_clp = fuel_l * diesel_price_clp_l

    return {
        "label": label,
        "xml_path": str(xml_path),
        "electrical_W": electrical_w,
        "radiant_W": radiant_w,
        "base_lamps": base_lamps,
        "mean_base_W_m2": mean_base,
        "mean_per_lamp_W_m2": mean_per_lamp,
        "target_W_m2": target_w_m2,
        "lamps_required": lamps_required,
        "mean_achieved_W_m2": mean_achieved,
        "electrical_system_kW": electrical_system_kw,
        "annual_kWh": annual_kwh,
        "fuel_L": fuel_l,
        "cost_CLP": cost_clp,
        "field_W_m2": field,
        "mask": mask,
        "centers_m": centers,
    }


def make_figures(rows: list[dict], outdir: Path, args: argparse.Namespace) -> None:
    plt.rcParams.update(
        {
            "font.family": "sans-serif",
            "font.sans-serif": ["Helvetica", "Arial", "DejaVu Sans"],
            "font.size": 9,
            "axes.titlesize": 10,
            "axes.labelsize": 9,
            "figure.dpi": 180,
            "axes.spines.top": False,
            "axes.spines.right": False,
        }
    )

    positive = np.concatenate([r["field_W_m2"][r["mask"]] for r in rows])
    positive = positive[positive > 0]
    vmin = max(float(np.percentile(positive, 3)), 1e-6)
    vmax = float(np.percentile(positive, 99.5))
    norm = mcolors.LogNorm(vmin=vmin, vmax=max(vmax, vmin * 10.0))
    fig, axes = plt.subplots(1, 3, figsize=(10.5, 3.25), constrained_layout=True)
    image = None
    for ax, row in zip(axes, rows):
        field_raw = row["field_W_m2"]
        field = np.where(row["mask"], gaussian_filter(field_raw, sigma=1.0), np.nan)
        centers = row["centers_m"]
        image = ax.pcolormesh(centers, centers, field, shading="nearest", cmap="viridis", norm=norm)
        for x, y in ring_positions(args.base_lamps, args.cage_side_m / 2.0, args.ring_radius_m):
            ax.plot(x, y, marker="x", color="white", ms=4, mew=1.0)
        ax.set_aspect("equal")
        ax.set_xlim(0, args.cage_side_m)
        ax.set_ylim(0, args.cage_side_m)
        ax.set_title(
            f'{row["label"]}\nPromedio 6 lámparas: {row["mean_base_W_m2"]:.4f} W/m²'
            .replace(".", ",")
        )
        ax.set_xlabel("x (m)")
    axes[0].set_ylabel("y (m)")
    cbar = fig.colorbar(image, ax=axes, fraction=0.025, pad=0.02)
    cbar.set_label("irradiancia DUP a 12 m (W/m²)")
    fig.savefig(outdir / "exorh_irradiance_12m.png", bbox_inches="tight")
    plt.close(fig)

    names = [r["label"] for r in rows]
    counts = np.array([r["lamps_required"] for r in rows], dtype=float)
    powers = np.array([r["electrical_system_kW"] for r in rows], dtype=float)
    costs = np.array([r["cost_CLP"] for r in rows], dtype=float) / 1_000_000.0
    fuel = np.array([r["fuel_L"] for r in rows], dtype=float)
    fig, axes = plt.subplots(1, 2, figsize=(10.5, 3.55))
    x = np.arange(len(rows))
    bars = axes[0].bar(x, counts, color=COLORS)
    axes[0].set_xticks(x, names)
    axes[0].set_ylabel("lámparas por jaula (unidades)")
    for bar, count, power in zip(bars, counts, powers):
        axes[0].text(
            bar.get_x() + bar.get_width() / 2.0,
            bar.get_height() + max(counts) * 0.025,
            f"{int(count)} u.\n{power:.2f} kW".replace(".", ","),
            ha="center",
            va="bottom",
        )
    axes[0].set_ylim(0, max(counts) * 1.23)
    axes[0].grid(axis="y", color="#E5E5E5", lw=0.6)

    bars = axes[1].bar(x, costs, color=COLORS)
    axes[1].set_xticks(x, names)
    axes[1].set_ylabel("costo de combustible (millones de CLP/año)")
    for bar, cost, liters in zip(bars, costs, fuel):
        axes[1].text(
            bar.get_x() + bar.get_width() / 2.0,
            bar.get_height() + max(costs) * 0.025,
            f"CLP {cost:.2f} M\n{liters:.0f} L".replace(".", ","),
            ha="center",
            va="bottom",
        )
    axes[1].set_ylim(0, max(costs) * 1.23)
    axes[1].grid(axis="y", color="#E5E5E5", lw=0.6)
    fig.tight_layout()
    fig.savefig(outdir / "exorh_target_economics.png", bbox_inches="tight")
    plt.close(fig)


def serializable(row: dict) -> dict:
    return {key: value for key, value in row.items() if not isinstance(value, np.ndarray)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--light-cage-sim", type=Path, required=True)
    parser.add_argument("--tempest", type=Path, required=True)
    parser.add_argument("--seacage", type=Path, required=True)
    parser.add_argument("--omnidirectional", type=Path, required=True)
    parser.add_argument("--outdir", type=Path, required=True)
    parser.add_argument("--cage-side-m", type=float, default=40.0)
    parser.add_argument("--lamp-depth-m", type=float, default=3.0)
    parser.add_argument("--plane-depth-m", type=float, default=12.0)
    parser.add_argument("--ring-radius-m", type=float, default=10.0)
    parser.add_argument("--base-lamps", type=int, default=6)
    parser.add_argument("--kd-m-inv", type=float, default=0.15)
    parser.add_argument("--target-w-m2", type=float, default=0.12)
    parser.add_argument("--grid-cell-m", type=float, default=0.25)
    parser.add_argument("--rays", type=int, default=300000)
    parser.add_argument("--seed", type=int, default=20260723)
    parser.add_argument("--cycle-hours", type=float, default=4380.0)
    parser.add_argument("--diesel-l-per-kwh", type=float, default=0.28)
    parser.add_argument("--diesel-price-clp-l", type=float, default=1000.0)
    args = parser.parse_args()

    sys.path.insert(0, str(args.light_cage_sim))
    from parsers import TM33Parser
    from simulation_engine import SimulationEngine

    args.outdir.mkdir(parents=True, exist_ok=True)
    sources = [
        ("TEMPEST", args.tempest),
        ("SEACAGE", args.seacage),
        ("Omnidireccional", args.omnidirectional),
    ]
    rows = [
        simulate_source(
            SimulationEngine,
            TM33Parser,
            label,
            path,
            cage_side_m=args.cage_side_m,
            lamp_depth_m=args.lamp_depth_m,
            plane_depth_m=args.plane_depth_m,
            ring_radius_m=args.ring_radius_m,
            base_lamps=args.base_lamps,
            kd_m_inv=args.kd_m_inv,
            target_w_m2=args.target_w_m2,
            grid_cell_m=args.grid_cell_m,
            rays=args.rays,
            seed=args.seed,
            cycle_hours=args.cycle_hours,
            diesel_l_per_kwh=args.diesel_l_per_kwh,
            diesel_price_clp_l=args.diesel_price_clp_l,
        )
        for label, path in sources
    ]
    make_figures(rows, args.outdir, args)

    fields = [
        "label",
        "electrical_W",
        "radiant_W",
        "base_lamps",
        "mean_base_W_m2",
        "mean_per_lamp_W_m2",
        "target_W_m2",
        "lamps_required",
        "mean_achieved_W_m2",
        "electrical_system_kW",
        "annual_kWh",
        "fuel_L",
        "cost_CLP",
    ]
    with (args.outdir / "exorh_irradiance_12m.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row[key] for key in fields})
    payload = {
        "scenario": {
            "cage_shape": "square",
            "cage_side_m": args.cage_side_m,
            "lamp_depth_m": args.lamp_depth_m,
            "plane_depth_m": args.plane_depth_m,
            "ring_radius_m": args.ring_radius_m,
            "base_lamps": args.base_lamps,
            "kd_m_inv": args.kd_m_inv,
            "target_W_m2": args.target_w_m2,
            "pineal_mu_max_deg": 85.0,
            "pineal_normalized": True,
            "grid_cell_m": args.grid_cell_m,
            "rays_per_lamp": args.rays,
            "seed": args.seed,
        },
        "rows": [serializable(row) for row in rows],
    }
    (args.outdir / "exorh_irradiance_12m.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(json.dumps(payload, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
