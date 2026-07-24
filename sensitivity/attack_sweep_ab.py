"""
Barrido de alta resolucion con stencils, parametrizacion de pendientes espectrales
INDEPENDIENTES: theta = (a550, b550, eta_a, eta_b, dz). Guarda el campo de irradiancia
por banda en una vecindad de cada sensor (igual formato que attack_sweep) para permitir
la marginalizacion de posicion en la inferencia.

Uso: python3 attack_sweep_ab.py --n 280 --start 0 --count 32 --rays 70000
"""
import os
import argparse
import numpy as np
from scipy.stats import qmc

from meas_parser import load_measurements
from sim_interface import SimRunner, TARGET_DEPTHS

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
_OUT = os.path.join(_HERE, "out", "attack_ab")
os.makedirs(_OUT, exist_ok=True)

USE_BANDS = ["blue", "green"]
CAL_NAMES = ["a550", "b550", "eta_a", "eta_b", "dz"]
CAL_BOUNDS = np.array([
    [0.02, 0.80],    # a550  absorcion @550
    [0.05, 1.50],    # b550  dispersion @550
    [-1.00, 3.00],   # eta_a pendiente espectral de absorcion
    [-1.00, 3.00],   # eta_b pendiente espectral de dispersion
    [-1.50, 2.00],   # dz    altura de lampara
])

STEN_R = 2.5
_g = np.arange(-STEN_R, STEN_R + 1e-9, 0.5)
OFFSETS = np.array([(dx, dy) for dx in _g for dy in _g if dx*dx + dy*dy <= STEN_R**2 + 1e-9])
N_OFF = len(OFFSETS)
Z_PLANES = np.array(TARGET_DEPTHS, dtype=float)


def design(n, seed=77):
    u = qmc.LatinHypercube(d=5, seed=seed).random(n)
    return qmc.scale(u, CAL_BOUNDS[:, 0], CAL_BOUNDS[:, 1])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=280)
    ap.add_argument("--start", type=int, default=0)
    ap.add_argument("--count", type=int, default=32)
    ap.add_argument("--rays", type=int, default=70000)
    args = ap.parse_args()

    recs = load_measurements(os.path.join(_ROOT, "measurements", "puntaiglesiaa"))
    pts = [(r["x"], r["y"], r["z"]) for r in recs]
    npts = len(pts)
    X = design(args.n)
    end = min(args.start + args.count, args.n)
    runner = SimRunner(rays=args.rays, seed=0)

    cand_path = os.path.join(_OUT, "candidates.npz")
    if not os.path.exists(cand_path):
        np.savez(cand_path, offsets=OFFSETS, z_planes=Z_PLANES, pts=np.array(pts),
                 bands=np.array(USE_BANDS), cal_names=np.array(CAL_NAMES), bounds=CAL_BOUNDS)

    base_xy = np.array([[p[0], p[1]] for p in pts])
    world = (base_xy[:, None, :] + OFFSETS[None, :, :]).reshape(-1, 2)

    import time
    t0 = time.time(); n_done = 0
    for k in range(args.start, end):
        theta = X[k]
        cfg = runner.build_config_ab(theta)
        res = runner.eng.run(cfg)
        Y = np.full((npts, len(USE_BANDS), len(Z_PLANES), N_OFF), np.nan, np.float32)
        for zi, d in enumerate(TARGET_DEPTHS):
            interps = runner._band_grids(res, d)
            for bi, b in enumerate(USE_BANDS):
                itp = interps[b]
                vals = np.zeros(len(world)) if itp is None else itp(world)
                Y[:, bi, zi, :] = np.log10(np.maximum(vals.reshape(npts, N_OFF)*1e3, 1e-3))
        np.savez_compressed(os.path.join(_OUT, f"chunk_{k:04d}.npz"),
                            idx=k, params=X[k], Y=Y)
        n_done += 1
    dt = time.time() - t0
    done = len([f for f in os.listdir(_OUT) if f.startswith("chunk_")])
    print(f"procesadas {n_done} [{args.start}:{end}] en {dt:.0f}s ({dt/max(n_done,1):.2f}s/corr)"
          f" | total {done}/{args.n}")


if __name__ == "__main__":
    main()
