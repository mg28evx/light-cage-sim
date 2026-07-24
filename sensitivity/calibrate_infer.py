"""
Fase 2 (paso 2) - Inferencia posterior de los parametros bio-opticos.

Toma el barrido LHS (sweep.csv) como muestras del prior uniforme y las pondera por
la verosimilitud (importance sampling autonormalizado) para obtener el posterior de
(c550, omega, eta, dz). De ahi deriva a y b a 550 nm:
        a550 = c550 * (1 - omega)      b550 = c550 * omega

Modelo de observacion (por punto de sensor y banda, en log10 mW/m2):
    d_i = log10(meas_i) - log10(sim_i)
    logP = mediana_i(d_i)          # potencia/escala absoluta desconocida (nuisance),
                                    # marginalizada analiticamente (offset comun en log)
    e_i = d_i - logP               # residuo de discrepancia + ruido
    L  ~ RSS^{-(nu/2)}             # sigma (discrepancia) integrado con prior de Jeffreys

Robustez: se excluyen puntos censurados (bajo el piso del sensor) y el outlier de
haz directo (10,10,8). Se reporta ademas una variante Student-t que conserva el
outlier para verificar estabilidad.
"""
import os
import numpy as np
import pandas as pd

from meas_parser import load_measurements, BANDS

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
_OUT = os.path.join(_HERE, "out")
SWEEP = os.path.join(_OUT, "sweep.csv")

SWEEP2 = os.path.join(_OUT, "sweep2.csv")
PROP = os.path.join(_OUT, "refine_proposal.npz")
USE_BANDS = ["blue", "green"]     # rojo descartado (piso del sensor)
OUTLIER_PT = (10.0, 10.0, 8.0)    # haz directo
SIM_FLOOR = 1e-6                  # W/m2, evita log(0)
CAL_NAMES = ["c550", "omega", "eta", "dz"]
CAL_BOUNDS = np.array([[0.10, 1.50], [0.50, 0.97], [-1.50, 2.50], [-1.50, 2.00]])


def _mixture_prior_ratio(X, n1, n2):
    """Ratio p(x)/m(x) para IS con mezcla balanceada (round1 uniforme + round2 Normal).
    Con prior uniforme p=1/vol, devuelve (1/vol)/m(x). Si no hay round2, es 1 (constante)."""
    vol = float(np.prod(CAL_BOUNDS[:, 1] - CAL_BOUNDS[:, 0]))
    q1 = np.full(len(X), 1.0 / vol)
    if n2 == 0 or not os.path.exists(PROP):
        return np.ones(len(X))
    from scipy.stats import multivariate_normal
    pr = np.load(PROP)
    q2 = multivariate_normal(mean=pr["mu"], cov=pr["cov"], allow_singular=True).pdf(X)
    m = (n1 * q1 + n2 * q2) / (n1 + n2)
    return (1.0 / vol) / np.maximum(m, 1e-300)


def _build_targets(recs):
    """Devuelve (mask_index, meas_log10) para los residuos usados; en mW/m2."""
    idx, logmeas, tags = [], [], []
    for i, r in enumerate(recs):
        if r["censored"]:
            continue
        is_out = (r["x"], r["y"], r["z"]) == OUTLIER_PT
        for b in USE_BANDS:
            m = r[f"band_{b}"]
            if m <= 0:
                continue
            idx.append((i, b))
            logmeas.append(np.log10(m))
            tags.append("outlier" if is_out else "ok")
    return idx, np.array(logmeas), np.array(tags)


def _sim_logmatrix(df, idx):
    """Matriz [n_design, n_resid] de log10(sim en mW/m2)."""
    cols = [f"p{i}_{b}" for (i, b) in idx]
    S = df[cols].to_numpy() * 1e3           # W/m2 -> mW/m2
    S = np.maximum(S, SIM_FLOOR * 1e3)
    return np.log10(S)


def _loglike_gauss(D):
    """D=[n_design,n_resid] de d_i. Marginal Gaussiano: logL = -(nu/2) log RSS."""
    logP = np.median(D, axis=1, keepdims=True)      # perfila potencia (robusto)
    E = D - logP
    rss = np.sum(E ** 2, axis=1)
    nu = D.shape[1] - 1
    return -(nu / 2.0) * np.log(rss + 1e-12), logP.ravel()


def _loglike_studentt(D, nu_t=4.0):
    """Verosimilitud Student-t (robusta) con escala global plug-in."""
    logP = np.median(D, axis=1, keepdims=True)
    E = D - logP
    s = 1.4826 * np.median(np.abs(E - np.median(E, axis=1, keepdims=True)), axis=1, keepdims=True)
    s = np.maximum(s, 1e-3)
    z2 = (E / s) ** 2
    ll = -((nu_t + 1) / 2.0) * np.log1p(z2 / nu_t) - np.log(s)
    return ll.sum(axis=1), logP.ravel()


def _weighted_quantiles(x, w, qs):
    o = np.argsort(x)
    x, w = x[o], w[o]
    cw = np.cumsum(w) - 0.5 * w
    cw /= np.sum(w)
    return np.interp(qs, cw, x)


def _summarize(name, X, w):
    ess = (w.sum() ** 2) / np.sum(w ** 2)
    print(f"\n=== Posterior [{name}]  ESS={ess:.0f}/{len(w)} ===")
    out = {}
    derived = {
        "c550": X[:, 0], "omega": X[:, 1], "eta": X[:, 2], "dz": X[:, 3],
        "a550": X[:, 0] * (1 - X[:, 1]),
        "b550": X[:, 0] * X[:, 1],
    }
    for k, v in derived.items():
        mean = np.sum(w * v) / np.sum(w)
        lo, med, hi = _weighted_quantiles(v, w, [0.05, 0.5, 0.95])
        out[k] = (mean, med, lo, hi)
        print(f"  {k:<6} mean={mean:7.3f}  med={med:7.3f}  90%CI=[{lo:7.3f}, {hi:7.3f}]")
    return out, ess


def main():
    df1 = pd.read_csv(SWEEP)
    n1 = len(df1)
    n2 = 0
    if os.path.exists(SWEEP2):
        df2 = pd.read_csv(SWEEP2)
        n2 = len(df2)
        df = pd.concat([df1, df2], ignore_index=True)
    else:
        df = df1
    recs = load_measurements(os.path.join(_ROOT, "measurements", "puntaiglesiaa"))
    idx, logmeas, tags = _build_targets(recs)
    print(f"{n1} uniformes + {n2} enfocadas = {len(df)} muestras | "
          f"{len(idx)} residuos ({np.sum(tags=='outlier')} del outlier)")

    X = df[CAL_NAMES].to_numpy()
    Slog = _sim_logmatrix(df, idx)
    D = logmeas[None, :] - Slog             # d_i por diseno
    mix = _mixture_prior_ratio(X, n1, n2)   # correccion de propuesta (MIS)

    # --- Principal: Gaussiano marginal, SIN outlier ---
    keep = tags != "outlier"
    ll_g, logP_g = _loglike_gauss(D[:, keep])
    w_g = np.exp(ll_g - ll_g.max()) * mix
    res_main, ess_main = _summarize("Gaussiano sin outlier", X, w_g)
    # potencia implicada (factor sobre 600W nominal)
    pf = 10.0 ** logP_g
    pf_mean = np.sum(w_g * pf) / np.sum(w_g)
    pf_lo, pf_med, pf_hi = _weighted_quantiles(pf, w_g, [0.05, 0.5, 0.95])
    print(f"  factor_potencia med={pf_med:.3f}  90%CI=[{pf_lo:.3f}, {pf_hi:.3f}]  "
          f"(=> ~{pf_med*600:.0f} W efectivos si nominal 600W)")

    # --- Robustez: Student-t, CON outlier ---
    ll_t, _ = _loglike_studentt(D)
    w_t = np.exp(ll_t - ll_t.max()) * mix
    res_rob, _ = _summarize("Student-t con outlier", X, w_t)

    # Guardar resumen y pesos
    np.savez(os.path.join(_OUT, "posterior.npz"),
             X=X, w_main=w_g, w_rob=w_t, logP_main=logP_g,
             cal_names=CAL_NAMES)
    summ = pd.DataFrame({k: dict(zip(["mean", "med", "lo", "hi"], v))
                         for k, v in res_main.items()}).T
    summ.to_csv(os.path.join(_OUT, "posterior_summary.csv"))
    print(f"\nGuardado posterior.npz y posterior_summary.csv en {_OUT}")

    _figures(X, w_g)
    return X, w_g


def _figures(X, w):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    labels = {"c550": "c550 = a+b @550 [1/m]", "omega": "omega = b/(a+b)",
              "eta": "eta (tilt espectral)", "dz": "dz altura lampara [m]",
              "a550": "a @550 [1/m]", "b550": "b @550 [1/m]"}
    vals = {"c550": X[:, 0], "omega": X[:, 1], "eta": X[:, 2], "dz": X[:, 3],
            "a550": X[:, 0] * (1 - X[:, 1]), "b550": X[:, 0] * X[:, 1]}
    fig, axes = plt.subplots(2, 3, figsize=(13, 7))
    for ax, key in zip(axes.ravel(), ["c550", "omega", "eta", "dz", "a550", "b550"]):
        v = vals[key]
        ax.hist(v, bins=30, weights=w, density=True, color="#2E75B6", alpha=0.85)
        lo, med, hi = _weighted_quantiles(v, w, [0.05, 0.5, 0.95])
        for xline, ls in [(med, "-"), (lo, "--"), (hi, "--")]:
            ax.axvline(xline, color="#C00000", ls=ls, lw=1.3)
        ax.set_title(labels[key]); ax.set_yticks([])
        ax.grid(axis="x", ls=":", alpha=0.4)
    fig.suptitle("Posterior marginal (Fase 2) - calibracion bio-optica de Punta Iglesia",
                 color="#1F3864", fontsize=13, weight="bold")
    fig.tight_layout(rect=[0, 0, 1, 0.97])
    fig.savefig(os.path.join(_OUT, "posterior_marginales.png"), dpi=130)
    plt.close(fig)

    # a vs b conjunto (scatter ponderado)
    fig, ax = plt.subplots(figsize=(6.5, 5.5))
    a = vals["a550"]; b = vals["b550"]
    sc = ax.scatter(a, b, c=w, cmap="viridis", s=14, alpha=0.7)
    ax.set_xlabel("a @550 [1/m]"); ax.set_ylabel("b @550 [1/m]")
    ax.set_title("Posterior conjunto (a, b) @550 nm"); ax.grid(ls=":", alpha=0.4)
    plt.colorbar(sc, ax=ax, label="peso posterior")
    fig.tight_layout(); fig.savefig(os.path.join(_OUT, "posterior_a_b.png"), dpi=130)
    plt.close(fig)
    print("Figuras: posterior_marginales.png, posterior_a_b.png")


if __name__ == "__main__":
    main()
