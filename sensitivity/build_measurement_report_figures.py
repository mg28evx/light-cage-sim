"""Genera exclusivamente figuras descriptivas de mediciones para los informes."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from meas_parser import load_measurements


ROOT = Path(__file__).resolve().parents[1]
SITES = {
    "puntaiglesia": (
        ROOT / "measurements" / "puntaiglesia_full",
        ROOT / "docs" / "reportes" / "latex" / "punta_iglesias" / "figures",
    ),
    "hueihue": (
        ROOT / "measurements" / "medicioneshueihue",
        ROOT / "docs" / "reportes" / "latex" / "hueihue" / "figures",
    ),
}
EVOLUX_BLACK = "#060400"
EVOLUX_YELLOW = "#FDC32E"
EVOLUX_GRAY = "#6B6B6B"
EVOLUX_GRID = "#D9D9D9"


def style(ax):
    ax.set_facecolor("white")
    ax.grid(True, color=EVOLUX_GRID, ls=":", lw=0.8)
    ax.spines[["top", "right"]].set_visible(False)
    ax.spines[["bottom", "left"]].set_color(EVOLUX_BLACK)
    ax.tick_params(colors=EVOLUX_BLACK)


def fmt(v):
    if v == 0:
        return "0,0000"
    return f"{v:.4f}".replace(".", ",")


def write_measurement_table(rows, path):
    rows = sorted(rows, key=lambda r: (r["z"], r["x"], r["y"]))
    n = (len(rows) + 1) // 2
    left, right = rows[:n], rows[n:]
    lines = [
        r"\begin{tabular}{rrrr|rrrr}",
        r"\toprule",
        r"$x$ & $y$ & $z$ & $E$ [W/m$^2$] & $x$ & $y$ & $z$ & $E$ [W/m$^2$] \\",
        r"\midrule",
    ]
    for i, a in enumerate(left):
        sa = f"{a['x']:.0f} & {a['y']:.0f} & {a['z']:.0f} & {fmt(a['par'] / 1000)}"
        if i < len(right):
            b = right[i]
            sb = f"{b['x']:.0f} & {b['y']:.0f} & {b['z']:.0f} & {fmt(b['par'] / 1000)}"
        else:
            sb = " &  &  & "
        lines.append(sa + " & " + sb + r" \\")
    lines += [r"\bottomrule", r"\end{tabular}"]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--site", choices=SITES, required=True)
    args = ap.parse_args()
    folder, out = SITES[args.site]
    out.mkdir(parents=True, exist_ok=True)
    rows = load_measurements(str(folder))
    depths = sorted({r["z"] for r in rows})
    write_measurement_table(rows, out.parent / "measurements_table.tex")

    means = [np.mean([r["par"] / 1000 for r in rows if r["z"] == z]) for z in depths]
    threshold = 0.012
    fig, ax = plt.subplots(figsize=(7.1, 4.3), facecolor="white")
    if args.site == "hueihue":
        plot_depths = np.asarray(depths, dtype=float)
        plot_means = np.asarray(means, dtype=float)
        x_fit = plot_depths - float(plot_depths[0])
        slope, intercept = np.polyfit(x_fit, np.log(plot_means), 1)
        k = -slope
        e0_fit = np.exp(intercept)
        z_threshold = depths[0] + np.log(e0_fit / threshold) / k
        z_fit = np.linspace(depths[0], z_threshold, 160)
        e_fit = e0_fit * np.exp(-k * (z_fit - depths[0]))
        ax.plot(plot_depths, plot_means, "o-", lw=2.3, color=EVOLUX_BLACK,
                markerfacecolor=EVOLUX_BLACK, markeredgecolor=EVOLUX_BLACK,
                label="Promedio medido")
        ax.plot(z_fit, e_fit, "--", lw=2.3, color=EVOLUX_YELLOW,
                label="Ajuste y extrapolación exponencial")
        ax.set_xticks([8, 10, 12, 14.8], labels=["8", "10", "12", "14,8"])
    else:
        plot_depths = np.asarray(depths, dtype=float)
        plot_means = np.asarray(means, dtype=float)
        ax.plot(plot_depths, plot_means, "o-", lw=2.3, color=EVOLUX_BLACK,
                markerfacecolor=EVOLUX_BLACK, markeredgecolor=EVOLUX_BLACK,
                label="Promedio medido")
        x_fit = np.asarray(depths, dtype=float) - float(depths[0])
        slope, intercept = np.polyfit(x_fit, np.log(means), 1)
        k = -slope
        e0_fit = np.exp(intercept)
        z_threshold = depths[0] + np.log(e0_fit / threshold) / k
        z_fit = np.linspace(depths[0], z_threshold, 160)
        e_fit = np.exp(intercept) * np.exp(-k * (z_fit - depths[0]))
        ax.plot(z_fit, e_fit, "--", lw=2.3, color=EVOLUX_YELLOW,
                label="Ajuste y extrapolación exponencial")
        ax.set_xticks([8, 10, 12, 14])
    threshold_label = f"{z_threshold:.1f}".replace(".", ",")
    ax.scatter([z_threshold], [threshold], marker="D", s=58,
               facecolor=EVOLUX_YELLOW, edgecolor=EVOLUX_BLACK, linewidth=0.9,
               label=f"Intersección: z={threshold_label} m", zorder=4)
    ax.axhline(threshold, color=EVOLUX_GRAY, ls=":", lw=1.7,
               label="Referencia 0,012 W/m²")
    y_max = max(float(np.max(plot_means)), float(np.max(e_fit)), threshold)
    ax.set_yscale("linear")
    ax.set_ylim(0.0, 1.12 * y_max)
    ax.set_xlabel("Profundidad [m]")
    ax.set_ylabel("Irradiancia PAR medida [W/m²]")
    style(ax)
    ax.legend(fontsize=8, frameon=True, facecolor="white",
              edgecolor=EVOLUX_GRAY, framealpha=1.0)
    fig.tight_layout()
    fig.savefig(out / "perfil_profundidad.pdf")
    plt.close(fig)
    par = np.asarray([r["par"] / 1000 for r in rows])
    max_row = max(rows, key=lambda r: r["par"])
    summary = {
        "site": args.site,
        "n": len(rows),
        "corrected_records": sum("correction_factor" in r for r in rows),
        "mean_global_W_m2": float(np.mean(par)),
        "max_W_m2": float(max_row["par"] / 1000),
        "max_xyz_m": [max_row["x"], max_row["y"], max_row["z"]],
        "mean_by_depth_W_m2": {
            str(int(z)): float(np.mean([r["par"] / 1000 for r in rows if r["z"] == z]))
            for z in depths
        },
        "k_m-1": float(k),
        "threshold_W_m2": threshold,
        "threshold_depth_m": float(z_threshold),
    }
    print(json.dumps(summary, indent=2, ensure_ascii=False))

if __name__ == "__main__":
    main()
