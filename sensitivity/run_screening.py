"""
Fase 1 - Screening de sensibilidad (metodo de Morris / elementary effects).

Cuantifica cuanto pesa cada fuente de incertidumbre en el DESAJUSTE simulacion-vs-
medicion, resuelto por banda espectral. El motor MC se corre con semilla fija por
theta, de modo que los efectos elementales reflejan la fisica, no el ruido de MC.

Metricas de salida (por banda azul/verde/rojo + PAR):
    misfit  : RMSE robusto del residuo log10(sim)-log10(meas) en los sensores.
              Es lo que una calibracion minimizaria -> "que hay que fijar".
    level   : mediana del residuo log10 -> nivel global (potencia, magnitud a+b).
    pattern : escala robusta (MAD) del residuo demediado -> patron espacial
              (posicion, altura, reparto absorcion/dispersion). Insensible a la
              escala global por construccion.

Uso:  python3 run_screening.py [--traj 30] [--rays 20000]
Salidas en sensitivity/out/: design.csv, morris_indices.csv, figuras PNG.
"""
import os
import argparse
import numpy as np
import pandas as pd

from SALib.sample import morris as morris_sample
from SALib.analyze import morris as morris_analyze

from meas_parser import load_measurements, BANDS
from sim_interface import SimRunner, PARAM_NAMES, DEFAULT_BOUNDS

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
_OUT = os.path.join(_HERE, "out")
os.makedirs(_OUT, exist_ok=True)
_MEAS = os.environ.get("MEAS_SUBDIR", "puntaiglesiaa")
_TAG = os.environ.get("SCREEN_TAG", "")   # sufijo para no pisar salidas de otro sitio

OUTPUT_BANDS = list(BANDS.keys()) + ["par"]
METRICS = ["misfit", "level", "pattern"]


def _robust_rmse(res):
    """RMSE robusto: raiz de la mediana de los cuadrados (insensible a outliers)."""
    res = np.asarray(res, dtype=float)
    return float(np.sqrt(np.median(res ** 2)))


def _robust_mad(res):
    res = np.asarray(res, dtype=float)
    return float(1.4826 * np.median(np.abs(res - np.median(res))))


def compute_metrics(sim, recs):
    """Compara sim (dict punto->banda->E) con mediciones. Devuelve dict banda_metric."""
    out = {}
    for band in OUTPUT_BANDS:
        residuals = []
        for r in recs:
            if r["censored"]:
                continue
            key = "par" if band == "par" else f"band_{band}"
            meas = r[key]
            if meas <= 0:
                continue
            p = (r["x"], r["y"], r["z"])
            s = sim[p]["green" if band == "par" else band] if band == "par" else sim[p][band]
            # PAR sim = suma de bandas.
            if band == "par":
                s = sim[p]["blue"] + sim[p]["green"] + sim[p]["red"]
            if s <= 0:
                s = 1e-9
            # meas en mW/m2, sim en W/m2 -> a mW/m2 para comparar en misma unidad.
            residuals.append(np.log10(s * 1e3) - np.log10(meas))
        residuals = np.asarray(residuals)
        if residuals.size == 0:
            out[f"{band}__misfit"] = np.nan
            out[f"{band}__level"] = np.nan
            out[f"{band}__pattern"] = np.nan
            continue
        out[f"{band}__misfit"] = _robust_rmse(residuals)
        out[f"{band}__level"] = float(np.median(residuals))
        out[f"{band}__pattern"] = _robust_mad(residuals)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--traj", type=int, default=30, help="trayectorias de Morris")
    ap.add_argument("--rays", type=int, default=20000)
    ap.add_argument("--levels", type=int, default=4)
    args = ap.parse_args()

    recs = load_measurements(os.path.join(_ROOT, "measurements", _MEAS))
    sensor_pts = [(r["x"], r["y"], r["z"]) for r in recs]
    n_valid = sum(1 for r in recs if not r["censored"])
    print(f"{len(recs)} mediciones ({n_valid} validas, {len(recs)-n_valid} censuradas)")

    problem = {
        "num_vars": len(PARAM_NAMES),
        "names": PARAM_NAMES,
        "bounds": [list(DEFAULT_BOUNDS[n]) for n in PARAM_NAMES],
    }
    X = morris_sample.sample(problem, N=args.traj, num_levels=args.levels)
    print(f"Diseno de Morris: {X.shape[0]} corridas ({args.traj} trayectorias)")

    runner = SimRunner(rays=args.rays, seed=0)

    out_cols = [f"{b}__{m}" for b in OUTPUT_BANDS for m in METRICS]
    Y = np.full((X.shape[0], len(out_cols)), np.nan)
    rows = []
    import time
    t0 = time.time()
    for i, theta in enumerate(X):
        sim = runner.run(theta, sensor_pts)
        met = compute_metrics(sim, recs)
        for j, c in enumerate(out_cols):
            Y[i, j] = met[c]
        rows.append(dict(zip(PARAM_NAMES, theta), **met))
        if (i + 1) % 25 == 0 or i == X.shape[0] - 1:
            el = time.time() - t0
            print(f"  {i+1}/{X.shape[0]} corridas ({el:.0f}s, {el/(i+1):.2f}s/corrida)")

    design = pd.DataFrame(rows)
    design.to_csv(os.path.join(_OUT, f"design{_TAG}.csv"), index=False)

    # --- Analisis de Morris por columna de salida --------------------------
    idx_rows = []
    for j, c in enumerate(out_cols):
        yj = Y[:, j]
        if np.all(np.isnan(yj)) or np.nanstd(yj) == 0:
            continue
        res = morris_analyze.analyze(problem, X, np.nan_to_num(yj, nan=np.nanmean(yj)),
                                     num_levels=args.levels)
        band, metric = c.split("__")
        for k, name in enumerate(problem["names"]):
            idx_rows.append(dict(band=band, metric=metric, param=name,
                                 mu_star=res["mu_star"][k], sigma=res["sigma"][k],
                                 mu_star_conf=res["mu_star_conf"][k]))
    idx = pd.DataFrame(idx_rows)
    idx.to_csv(os.path.join(_OUT, f"morris_indices{_TAG}.csv"), index=False)
    print(f"\nGuardado design.csv y morris_indices.csv en {_OUT}")

    _make_figures(idx)
    _print_ranking(idx)
    return idx


def _make_figures(idx):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    # Figura 1: mu_star por parametro, para el misfit de cada banda.
    mis = idx[idx["metric"] == "misfit"]
    bands = ["blue", "green", "red", "par"]
    params = PARAM_NAMES
    fig, ax = plt.subplots(figsize=(10, 5.5))
    w = 0.2
    xpos = np.arange(len(params))
    for bi, b in enumerate(bands):
        sub = mis[mis["band"] == b].set_index("param").reindex(params)
        ax.bar(xpos + (bi - 1.5) * w, sub["mu_star"].values, w, label=b)
    ax.set_xticks(xpos); ax.set_xticklabels(params, rotation=20)
    ax.set_ylabel(r"$\mu^*$ (importancia sobre el misfit)")
    ax.set_title("Sensibilidad del desajuste sim-vs-medicion por fuente y banda")
    ax.legend(title="banda"); ax.grid(axis="y", ls=":", alpha=0.5)
    fig.tight_layout(); fig.savefig(os.path.join(_OUT, f"mu_star_misfit_por_banda{_TAG}.png"), dpi=130)
    plt.close(fig)

    # Figura 2: mu_star vs sigma (interaccion/no linealidad) para PAR misfit.
    fig, ax = plt.subplots(figsize=(7, 6))
    sub = idx[(idx["band"] == "par") & (idx["metric"] == "misfit")]
    ax.scatter(sub["mu_star"], sub["sigma"], s=60)
    for _, row in sub.iterrows():
        ax.annotate(row["param"], (row["mu_star"], row["sigma"]),
                    xytext=(5, 5), textcoords="offset points")
    lim = max(sub["mu_star"].max(), sub["sigma"].max()) * 1.1
    ax.plot([0, lim], [0, lim], "k--", alpha=0.4, label=r"$\sigma=\mu^*$")
    ax.set_xlabel(r"$\mu^*$ (efecto medio)"); ax.set_ylabel(r"$\sigma$ (interaccion/no lineal)")
    ax.set_title("Morris - PAR: importancia vs interaccion")
    ax.legend(); ax.grid(ls=":", alpha=0.5)
    fig.tight_layout(); fig.savefig(os.path.join(_OUT, f"mu_star_vs_sigma_par{_TAG}.png"), dpi=130)
    plt.close(fig)

    # Figura 3: descomposicion nivel vs patron (PAR).
    fig, ax = plt.subplots(figsize=(9, 5))
    xpos = np.arange(len(PARAM_NAMES)); w = 0.35
    for mi, metric in enumerate(["level", "pattern"]):
        sub = idx[(idx["band"] == "par") & (idx["metric"] == metric)]
        sub = sub.set_index("param").reindex(PARAM_NAMES)
        ax.bar(xpos + (mi - 0.5) * w, sub["mu_star"].values, w, label=metric)
    ax.set_xticks(xpos); ax.set_xticklabels(PARAM_NAMES, rotation=20)
    ax.set_ylabel(r"$\mu^*$"); ax.set_title("PAR: nivel global vs patron espacial")
    ax.legend(); ax.grid(axis="y", ls=":", alpha=0.5)
    fig.tight_layout(); fig.savefig(os.path.join(_OUT, f"nivel_vs_patron_par{_TAG}.png"), dpi=130)
    plt.close(fig)
    print("Figuras guardadas: mu_star_misfit_por_banda.png, mu_star_vs_sigma_par.png, nivel_vs_patron_par.png")


def _print_ranking(idx):
    print("\n=== Ranking de fuentes por misfit (mu_star normalizado) ===")
    for b in ["par", "blue", "green", "red"]:
        sub = idx[(idx["band"] == b) & (idx["metric"] == "misfit")].copy()
        if sub.empty:
            continue
        tot = sub["mu_star"].sum()
        sub["pct"] = 100 * sub["mu_star"] / (tot + 1e-12)
        sub = sub.sort_values("mu_star", ascending=False)
        print(f"\n[{b}]")
        for _, r in sub.iterrows():
            print(f"  {r['param']:<11} mu*={r['mu_star']:.4f}  ({r['pct']:4.1f}%)  sigma={r['sigma']:.4f}")


if __name__ == "__main__":
    main()
