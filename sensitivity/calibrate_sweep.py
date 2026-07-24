"""
Fase 2 (paso 1) - Barrido Latin-hypercube del simulador para calibracion.

Genera un diseno LHS fijo sobre los parametros bio-opticos que dominan el ajuste
(c550, omega, eta) mas la altura de lampara dz como nuisance, corre el ray tracer
con SEMILLA FIJA (forward model determinista) y guarda la irradiancia predicha por
punto de sensor y banda. Es resumible: cada llamada procesa un tramo [start:start+count]
y lo agrega a sweep.csv, para caber en el limite de tiempo por comando.

Uso:  python3 calibrate_sweep.py --n 1000 --start 0 --count 200 --rays 12000
      (repetir subiendo --start hasta completar N)
"""
import os
import argparse
import numpy as np
import pandas as pd
from scipy.stats import qmc

from meas_parser import load_measurements, BANDS
from sim_interface import SimRunner

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
_OUT = os.path.join(_HERE, "out")
os.makedirs(_OUT, exist_ok=True)
SWEEP = os.path.join(_OUT, "sweep.csv")

# Prior uniforme (rango de barrido) de los parametros a calibrar.
CAL_NAMES = ["c550", "omega", "eta", "dz"]
CAL_BOUNDS = np.array([
    [0.10, 1.50],   # c550  (a+b @550)
    [0.50, 0.97],   # omega (b/(a+b))
    [-1.50, 2.50],  # eta   (tilt espectral)
    [-1.50, 2.00],  # dz    (altura de lampara)
])
BAND_KEYS = list(BANDS.keys())  # blue, green, red


SWEEP2 = os.path.join(_OUT, "sweep2.csv")
PROP = os.path.join(_OUT, "refine_proposal.npz")


def design(n, seed=2024):
    sampler = qmc.LatinHypercube(d=len(CAL_NAMES), seed=seed)
    u = sampler.random(n)
    return qmc.scale(u, CAL_BOUNDS[:, 0], CAL_BOUNDS[:, 1])


def refine_design(count, seed=7):
    """Muestrea de una Normal centrada en el posterior (inflada), truncada al box.
    Guarda mu/cov de la propuesta para el peso de mezcla en la inferencia."""
    post = np.load(os.path.join(_OUT, "posterior.npz"))
    X, w = post["X"], post["w_main"]
    mu = np.average(X, axis=0, weights=w)
    cov = np.cov(X.T, aweights=w) * 1.8 + np.eye(len(CAL_NAMES)) * 1e-4
    np.savez(PROP, mu=mu, cov=cov)
    rng = np.random.default_rng(seed)
    out = []
    while len(out) < count:
        s = rng.multivariate_normal(mu, cov)
        if np.all(s >= CAL_BOUNDS[:, 0]) and np.all(s <= CAL_BOUNDS[:, 1]):
            out.append(s)
    return np.array(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=1000)
    ap.add_argument("--start", type=int, default=0)
    ap.add_argument("--count", type=int, default=200)
    ap.add_argument("--rays", type=int, default=12000)
    ap.add_argument("--refine", action="store_true",
                    help="muestreo enfocado alrededor del posterior -> sweep2.csv")
    args = ap.parse_args()

    recs = load_measurements(os.path.join(_ROOT, "measurements", "puntaiglesiaa"))
    pts = [(r["x"], r["y"], r["z"]) for r in recs]
    target_csv = SWEEP2 if args.refine else SWEEP
    if args.refine:
        X = refine_design(args.n)
        args.n = len(X)
    else:
        X = design(args.n)
    end = min(args.start + args.count, args.n)

    runner = SimRunner(rays=args.rays, seed=0)  # semilla fija -> determinista
    # Fuentes fijas en el barrido: potencia nominal (se marginaliza en analisis),
    # posicion sin jitter (marginal segun screening).
    pred_cols = [f"p{i}_{b}" for i in range(len(pts)) for b in BAND_KEYS]

    cols = ["idx"] + CAL_NAMES + pred_cols
    if not os.path.exists(target_csv):
        pd.DataFrame(columns=cols).to_csv(target_csv, index=False)
    import time
    t0 = time.time()
    n_done = 0
    with open(target_csv, "a") as fh:
        for k in range(args.start, end):
            c550, omega, eta, dz = X[k]
            theta = [1.0, dz, 0.0, c550, omega, eta]  # f_power=1, pos_jitter=0
            sim = runner.run(theta, pts)
            row = {"idx": k, "c550": c550, "omega": omega, "eta": eta, "dz": dz}
            for i, p in enumerate(pts):
                for b in BAND_KEYS:
                    row[f"p{i}_{b}"] = sim[p][b]
            fh.write(",".join(str(row[c]) for c in cols) + "\n")
            fh.flush()
            n_done += 1
    dt = time.time() - t0
    print(f"procesadas {n_done} corridas [{args.start}:{end}] en {dt:.0f}s ({dt/max(n_done,1):.2f}s/corr)")
    total = sum(1 for _ in open(target_csv)) - 1
    print(f"{os.path.basename(target_csv)} ahora tiene {total}/{args.n} filas")


if __name__ == "__main__":
    main()
