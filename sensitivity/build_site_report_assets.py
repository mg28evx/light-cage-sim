"""Genera insumos cuantitativos reproducibles para los informes de irradiancia.

Uso (SITE debe coincidir con --site):
  SITE=puntaiglesia venv/bin/python sensitivity/build_site_report_assets.py --site puntaiglesia
  SITE=hueihue venv/bin/python sensitivity/build_site_report_assets.py --site hueihue

El modelo es deliberadamente condicional: usa un conjunto bio-optico representativo
del posterior con posicion de sensor marginalizada y perfila una unica escala global
en log10. No interpreta esa escala como dimming fisico.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import TwoSlopeNorm
import numpy as np

from meas_parser import load_measurements
from sim_interface import SimRunner


ROOT = Path(__file__).resolve().parents[1]

SITE = {
    "puntaiglesia": {
        "label": "Punta Iglesias",
        "folder": ROOT / "measurements" / "puntaiglesia_full",
        "out": ROOT / "docs" / "reportes" / "latex" / "punta_iglesias",
        # Representativo del subconjunto dz~0 del ataque con posicion latente.
        "theta": [1.0, 0.0, 0.0, 1.010, 0.736, 0.451],
        "exclude_cal": {(10.0, 10.0, 8.0)},
        "sigma_xy": [0.3, 0.5, 1.0, 1.5, 2.0, 2.5],
        "r2_xval": [0.677, 0.711, 0.865, 0.892, 0.899, 0.902],
        "r2_fixed": 0.389,
    },
    "hueihue": {
        "label": "Hueihue",
        "folder": ROOT / "measurements" / "medicioneshueihue",
        "out": ROOT / "docs" / "reportes" / "latex" / "hueihue",
        # Pico del ataque compatible con profundidad nominal cercana a 3 m.
        "theta": [1.0, 0.0, 0.0, 1.285, 0.507, -1.069],
        "exclude_cal": set(),
        "sigma_xy": [0.3, 0.5, 1.0, 1.5, 2.0, 2.5],
        "r2_xval": [0.636, 0.666, 0.741, 0.766, 0.775, 0.780],
        "r2_fixed": 0.382,
    },
}

BLUE = "#4472C4"
GREEN = "#70AD47"
RED = "#C00000"
NAVY = "#1F4E79"
GREY = "#666666"


def _metrics(y: np.ndarray, yh: np.ndarray) -> dict:
    resid = y - yh
    den = np.sum((y - np.mean(y)) ** 2)
    r2 = float(1.0 - np.sum(resid**2) / den) if den > 0 else float("nan")
    rmse = float(np.sqrt(np.mean(resid**2)))
    return {"r2": r2, "rmse_log10": rmse, "scatter_factor": float(10**rmse)}


def _fmt(v: float) -> str:
    if v == 0:
        return "0,0000"
    return f"{v:.4f}".replace(".", ",")


def _write_table(rows: list[dict], path: Path) -> None:
    rows = sorted(rows, key=lambda r: (r["z"], r["x"], r["y"]))
    n = (len(rows) + 1) // 2
    left, right = rows[:n], rows[n:]
    lines = [
        r"\begin{tabular}{rrrr|rrrr}",
        r"\toprule",
        r"$x$ & $y$ & $z$ & $E$ [W/m$^2$] & $x$ & $y$ & $z$ & $E$ [W/m$^2$] \\",
        r"\midrule",
    ]
    for i in range(n):
        a = left[i]
        sa = f"{a['x']:.0f} & {a['y']:.0f} & {a['z']:.0f} & {_fmt(a['par_meas_w'])}"
        if i < len(right):
            b = right[i]
            sb = f"{b['x']:.0f} & {b['y']:.0f} & {b['z']:.0f} & {_fmt(b['par_meas_w'])}"
        else:
            sb = " &  &  & "
        lines.append(sa + " & " + sb + r" \\")
    lines += [r"\bottomrule", r"\end{tabular}"]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _style(ax):
    ax.grid(True, ls=":", alpha=0.4)
    ax.spines[["top", "right"]].set_visible(False)


def _plot_depth(rows: list[dict], out: Path) -> None:
    depths = sorted({r["z"] for r in rows})
    mm, md, sm, sd = [], [], [], []
    for z in depths:
        m = np.array([r["par_meas_w"] for r in rows if r["z"] == z])
        s = np.array([r["par_sim_w"] for r in rows if r["z"] == z])
        mm.append(np.mean(m)); md.append(np.median(m)); sm.append(np.mean(s)); sd.append(np.median(s))
    fig, ax = plt.subplots(figsize=(7.1, 4.3))
    ax.plot(depths, mm, "o-", lw=2.2, color=BLUE, label="Medición: media")
    ax.plot(depths, md, "s--", lw=1.8, color=NAVY, label="Medición: mediana")
    ax.plot(depths, sm, "o-", lw=2.0, color=GREEN, label="Simulación condicionada: media")
    ax.plot(depths, sd, "s--", lw=1.6, color="#548235", label="Simulación condicionada: mediana")
    ax.axhline(0.012, color=RED, ls=":", lw=1.5, label="Umbral 0,012 W/m²")
    ax.set_yscale("log"); ax.set_xlabel("Profundidad [m]"); ax.set_ylabel("Irradiancia PAR [W/m²]")
    ax.set_xticks(depths); _style(ax); ax.legend(fontsize=8, ncol=2)
    fig.tight_layout(); fig.savefig(out / "figures" / "perfil_profundidad.pdf"); plt.close(fig)


def _plot_coverage(rows: list[dict], out: Path) -> None:
    depths = sorted({r["z"] for r in rows}); thresholds = [0.012, 0.016, 0.120]
    colors = [BLUE, GREEN, "#A5A5A5"]
    fig, ax = plt.subplots(figsize=(7.1, 4.3)); x = np.arange(len(depths)); w = 0.23
    for j, (thr, col) in enumerate(zip(thresholds, colors)):
        vals = [100*np.mean([r["par_meas_w"] >= thr for r in rows if r["z"] == z]) for z in depths]
        bars = ax.bar(x + (j-1)*w, vals, w, color=col, label=f"E ≥ {thr:.3f} W/m²")
        ax.bar_label(bars, labels=[f"{v:.0f}%" for v in vals], fontsize=8, padding=2)
    ax.set_xticks(x, [f"{z:.0f} m" for z in depths]); ax.set_ylim(0, 108)
    ax.set_ylabel("Cobertura de puntos [%]"); _style(ax); ax.legend(fontsize=8)
    fig.tight_layout(); fig.savefig(out / "figures" / "cobertura_profundidad.pdf"); plt.close(fig)


def _plot_scatter(rows: list[dict], metrics: dict, out: Path) -> None:
    fig, ax = plt.subplots(figsize=(6.3, 5.4))
    for band, color, marker, label in [("blue", BLUE, "o", "Azul"), ("green", GREEN, "s", "Verde")]:
        x = np.array([r[f"{band}_meas_w"] for r in rows if not r["censored"]])
        y = np.array([r[f"{band}_sim_w"] for r in rows if not r["censored"]])
        ax.scatter(x, y, s=34, alpha=0.82, color=color, marker=marker, label=label)
    allv = np.array([r[k] for r in rows if not r["censored"] for k in
                     ("blue_meas_w", "green_meas_w", "blue_sim_w", "green_sim_w")])
    lo = max(np.min(allv[allv > 0])*0.65, 1e-6); hi = np.max(allv)*1.55
    q = np.geomspace(lo, hi, 200)
    ax.plot(q, q, color="black", lw=1.5, label="1:1")
    ax.plot(q, 3*q, color=GREY, lw=1, ls=":"); ax.plot(q, q/3, color=GREY, lw=1, ls=":", label="factor 3")
    ax.set_xscale("log"); ax.set_yscale("log"); ax.set_xlim(lo, hi); ax.set_ylim(lo, hi)
    ax.set_xlabel("Medición [W/m²]"); ax.set_ylabel("Simulación escalada [W/m²]")
    ax.text(0.03, 0.96, f"R² nominal = {metrics['nominal']['r2']:.2f}\nRMSE = ×{metrics['nominal']['scatter_factor']:.1f}",
            transform=ax.transAxes, va="top", fontsize=9)
    _style(ax); ax.legend(fontsize=8, loc="lower right")
    fig.tight_layout(); fig.savefig(out / "figures" / "match_scatter.pdf"); plt.close(fig)


def _plot_residuals(rows: list[dict], out: Path) -> None:
    depths = sorted({r["z"] for r in rows}); n = len(depths)
    fig, axes = plt.subplots(1, n, figsize=(3.55*n, 3.55), squeeze=False, constrained_layout=True)
    norm = TwoSlopeNorm(vmin=-1.5, vcenter=0, vmax=1.5)
    im = None
    for ax, z in zip(axes[0], depths):
        sub = [r for r in rows if r["z"] == z]
        xs = sorted({r["x"] for r in sub}); ys = sorted({r["y"] for r in sub})
        dx = min(np.diff(xs)) if len(xs) > 1 else 1.0; dy = min(np.diff(ys)) if len(ys) > 1 else 1.0
        for r in sub:
            if r["censored"]:
                ax.scatter(r["x"], r["y"], marker="x", s=52, color="black")
                ax.text(r["x"], r["y"]+0.5, "cens.", ha="center", fontsize=7)
            else:
                val = np.log10(r["par_meas_w"] / max(r["par_sim_w"], 1e-12))
                im = ax.scatter(r["x"], r["y"], c=[val], cmap="RdBu_r", norm=norm,
                                s=190, edgecolor="black", linewidth=0.5)
                ax.text(r["x"], r["y"], f"×{10**val:.1f}", ha="center", va="center", fontsize=7)
        ax.set_title(f"z = {z:.0f} m"); ax.set_xlabel("x [m]"); ax.set_ylabel("y [m]")
        ax.set_xlim(min(xs)-0.75*dx,max(xs)+0.75*dx); ax.set_ylim(min(ys)-0.75*dy,max(ys)+0.75*dy)
        ax.set_aspect("equal"); _style(ax)
    if im is not None:
        cb = fig.colorbar(im, ax=axes.ravel().tolist(), shrink=0.78, pad=0.025)
        cb.set_label("log10(medición / simulación)")
    fig.savefig(out / "figures" / "residuos_espaciales.pdf"); plt.close(fig)


def _plot_position(meta: dict, out: Path) -> None:
    x = np.asarray(meta["sigma_xy"]); y = np.asarray(meta["r2_xval"])
    fig, ax = plt.subplots(figsize=(6.7, 4.0))
    ax.plot(x, y, "s-", color=BLUE, lw=2.4, ms=6, label="Validación azul→verde")
    ax.axhline(meta["r2_fixed"], color=RED, ls="--", lw=1.6, label="Posición nominal")
    for xx, yy in zip(x, y): ax.text(xx, yy+0.015, f"{yy:.2f}", ha="center", fontsize=8)
    ax.set_xlabel("σ horizontal de posición del sensor [m]"); ax.set_ylabel("R² logarítmico")
    ax.set_ylim(max(0, meta["r2_fixed"]-0.12), 1.0); _style(ax); ax.legend(fontsize=8)
    fig.tight_layout(); fig.savefig(out / "figures" / "incertidumbre_posicion.pdf"); plt.close(fig)


def main() -> None:
    ap = argparse.ArgumentParser(); ap.add_argument("--site", choices=SITE, required=True); ap.add_argument("--rays", type=int, default=300000)
    args = ap.parse_args(); meta = SITE[args.site]; out = meta["out"]; (out/"figures").mkdir(parents=True, exist_ok=True)
    if os.environ.get("SITE", "puntaiglesia") != args.site:
        raise SystemExit("Defina SITE con el mismo valor que --site antes de importar sim_interface")

    recs = load_measurements(str(meta["folder"])); pts = [(r["x"],r["y"],r["z"]) for r in recs]
    runner = SimRunner(rays=args.rays, seed=0); sim = runner.run(meta["theta"], pts)

    cal = [i for i,r in enumerate(recs) if not r["censored"] and (r["x"],r["y"],r["z"]) not in meta["exclude_cal"]]
    diffs = []
    for i in cal:
        r = recs[i]; s = sim[pts[i]]
        for b in ("blue","green"):
            diffs.append(np.log10(r[f"band_{b}"]) - np.log10(max(s[b]*1000, 1e-3)))
    log_scale = float(np.median(diffs)); scale = 10**log_scale

    rows = []
    for r,p in zip(recs,pts):
        s = sim[p]
        row = {k:r[k] for k in ("x","y","z","file","source","censored")}
        for b in ("blue","green","red"):
            row[f"{b}_meas_w"] = r[f"band_{b}"]/1000
            row[f"{b}_sim_w"] = s[b]*scale
        row["par_meas_w"] = r["par"]/1000
        row["par_sim_w"] = sum(row[f"{b}_sim_w"] for b in ("blue","green","red"))
        rows.append(row)

    used = [r for r in rows if not r["censored"]]
    y = np.array([[np.log10(r["blue_meas_w"]),np.log10(r["green_meas_w"])] for r in used]).reshape(-1)
    yh = np.array([[np.log10(max(r["blue_sim_w"],1e-12)),np.log10(max(r["green_sim_w"],1e-12))] for r in used]).reshape(-1)
    nominal = _metrics(y,yh)
    par_abs = np.array([abs(np.log10(r["par_meas_w"]/max(r["par_sim_w"],1e-12))) for r in used])
    order = np.argsort(par_abs)

    par = np.array([r["par_meas_w"] for r in rows])
    summary = {
        "site": meta["label"], "n": len(rows), "n_censored": int(sum(r["censored"] for r in rows)),
        "mean_wm2": float(np.mean(par)), "median_wm2": float(np.median(par)), "max_wm2": float(np.max(par)),
        "coverage_0012": float(np.mean(par>=0.012)), "coverage_0016": float(np.mean(par>=0.016)),
        "coverage_0120": float(np.mean(par>=0.120)), "log_scale": log_scale, "scale": scale,
        "nominal": nominal, "r2_fixed_attack": meta["r2_fixed"],
        "r2_xval_sigma_1m": meta["r2_xval"][2], "r2_xval_sigma_2p5m": meta["r2_xval"][-1],
        "closest": [[used[i]["x"],used[i]["y"],used[i]["z"],float(10**par_abs[i])] for i in order[:5]],
        "farthest": [[used[i]["x"],used[i]["y"],used[i]["z"],float(10**par_abs[i])] for i in order[-5:][::-1]],
        "theta": meta["theta"], "rays": args.rays,
    }
    (out/"summary.json").write_text(json.dumps(summary,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    cols = ["file","source","x","y","z","censored","par_meas_w","par_sim_w","blue_meas_w","blue_sim_w","green_meas_w","green_sim_w","red_meas_w","red_sim_w"]
    with (out/"match_points.csv").open("w",encoding="utf-8") as fh:
        fh.write(",".join(cols)+"\n")
        for r in rows: fh.write(",".join(str(r[c]) for c in cols)+"\n")
    _write_table(rows,out/"measurements_table.tex")
    _plot_depth(rows,out); _plot_coverage(rows,out); _plot_scatter(rows,summary,out); _plot_residuals(rows,out); _plot_position(meta,out)
    print(json.dumps(summary,indent=2,ensure_ascii=False))


if __name__ == "__main__":
    main()
