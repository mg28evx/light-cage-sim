"""
Fase 2 (paso 3) - Chequeo predictivo posterior.

Corre el simulador con RAYOS ALTOS en la mediana del posterior y compara con las
mediciones por banda. Como la escala absoluta (potencia/unidades) es un nuisance
marginalizado, la comparacion se hace tras aplicar el offset log optimo (mediana de
d_i). Reporta R2 y RMSE en log10, y contrasta contra la config nominal previa para
mostrar la mejora del ajuste espacial/espectral.
"""
import os
import numpy as np
import pandas as pd

from meas_parser import load_measurements
from sim_interface import SimRunner

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
_OUT = os.path.join(_HERE, "out")
USE_BANDS = ["blue", "green"]
OUTLIER_PT = (10.0, 10.0, 8.0)


def _pairs(recs, sim):
    """Devuelve arrays log10(meas), log10(sim mW/m2), tag por (punto,banda) validos."""
    lm, ls, tag = [], [], []
    for r in recs:
        if r["censored"]:
            continue
        p = (r["x"], r["y"], r["z"])
        is_out = p == OUTLIER_PT
        for b in USE_BANDS:
            m = r[f"band_{b}"]
            s = sim[p][b] * 1e3
            if m <= 0 or s <= 0:
                continue
            lm.append(np.log10(m)); ls.append(np.log10(s))
            tag.append("outlier" if is_out else "ok")
    return np.array(lm), np.array(ls), np.array(tag)


def _fit_stats(lm, ls):
    """Aplica offset log optimo (potencia nuisance) y calcula R2, RMSE en log10."""
    off = np.median(lm - ls)
    pred = ls + off
    resid = lm - pred
    ss_res = np.sum(resid ** 2)
    ss_tot = np.sum((lm - np.mean(lm)) ** 2)
    r2 = 1 - ss_res / ss_tot if ss_tot > 0 else np.nan
    rmse = np.sqrt(np.mean(resid ** 2))
    return off, pred, r2, rmse


def main():
    post = np.load(os.path.join(_OUT, "posterior.npz"))
    X, w = post["X"], post["w_main"]
    med = {n: float(np.interp(0.5, np.cumsum(w[np.argsort(X[:, i])]) / w.sum(),
                              np.sort(X[:, i])))
           for i, n in enumerate(["c550", "omega", "eta", "dz"])}
    print("Mediana posterior:", {k: round(v, 3) for k, v in med.items()})

    recs = load_measurements(os.path.join(_ROOT, "measurements", "puntaiglesiaa"))
    pts = [(r["x"], r["y"], r["z"]) for r in recs]
    runner = SimRunner(rays=45000, seed=0)

    # Calibrado (posterior) vs nominal previo (c=0.4, omega=0.8, eta=1, dz=0)
    theta_cal = [1.0, med["dz"], 0.0, med["c550"], med["omega"], med["eta"]]
    theta_nom = [1.0, 0.0, 0.0, 0.40, 0.80, 1.0]
    sim_cal = runner.run(theta_cal, pts)
    sim_nom = runner.run(theta_nom, pts)

    out = {}
    for name, sim in [("calibrado", sim_cal), ("nominal", sim_nom)]:
        lm, ls, tag = _pairs(recs, sim)
        keep = tag != "outlier"
        off, pred, r2, rmse = _fit_stats(lm[keep], ls[keep])
        out[name] = dict(lm=lm, ls=ls, tag=tag, off=off, r2=r2, rmse=rmse)
        print(f"[{name}] R2(log)={r2:.3f}  RMSE(log10)={rmse:.3f}  "
              f"offset_log={off:.2f} (factor {10**off:.3f})  n={keep.sum()}")

    _figure(out)
    # a,b derivados de la mediana
    a = med["c550"] * (1 - med["omega"]); b = med["c550"] * med["omega"]
    print(f"\n(a, b) @550 nm en la mediana:  a={a:.3f}  b={b:.3f}  [1/m]")
    return out


def _figure(out):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(1, 2, figsize=(12, 5.4))
    for ax, name in zip(axes, ["nominal", "calibrado"]):
        o = out[name]
        for tg, col, lab in [("ok", "#2E75B6", "usado"), ("outlier", "#C00000", "outlier (excl.)")]:
            m = o["tag"] == tg
            ax.scatter(o["lm"][m], o["ls"][m] + o["off"], c=col, s=42, alpha=0.8,
                       edgecolor="w", linewidth=0.4, label=lab)
        lim = [min(o["lm"].min(), (o["ls"] + o["off"]).min()) - 0.2,
               max(o["lm"].max(), (o["ls"] + o["off"]).max()) + 0.2]
        ax.plot(lim, lim, "k--", alpha=0.5, label="1:1")
        ax.set_xlim(lim); ax.set_ylim(lim)
        ax.set_xlabel("log10 medicion [mW/m2]"); ax.set_ylabel("log10 simulacion (con offset)")
        ax.set_title(f"{name}:  R2={o['r2']:.2f},  RMSE={o['rmse']:.2f}")
        ax.grid(ls=":", alpha=0.4); ax.legend(fontsize=8)
    fig.suptitle("Chequeo predictivo posterior - Punta Iglesia (bandas azul+verde)",
                 color="#1F3864", fontsize=13, weight="bold")
    fig.tight_layout(rect=[0, 0, 1, 0.96])
    fig.savefig(os.path.join(_OUT, "ppc_scatter.png"), dpi=130)
    plt.close(fig)
    print("Figura: ppc_scatter.png")


if __name__ == "__main__":
    main()
