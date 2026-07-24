"""
Barrido de alta resolucion con STENCILS de vecindad del sensor (para atacar el piso).

Igual que calibrate_sweep pero: (1) rayos altos (campo suave), y (2) por cada punto
de sensor y banda guarda el campo E en una vecindad de offsets (dx,dy) y en los tres
planos de profundidad, de modo que la inferencia pueda marginalizar la POSICION del
sensor con un prior gaussiano.

Salida: chunks npz en out/attack/ con Y[run, punto, banda, plano_z, offset].
Uso:  python3 attack_sweep.py --n 360 --start 0 --count 60 --rays 100000
      (repetir subiendo --start). candidates.npz guarda la geometria del stencil.
"""
import os
import argparse
import numpy as np
from scipy.stats import qmc

from meas_parser import load_measurements
from sim_interface import SimRunner, TARGET_DEPTHS

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
_OUT = os.path.join(_HERE, "out", os.environ.get("ATK_SUBDIR", "attack"))
_MEAS = os.environ.get("MEAS_SUBDIR", "puntaiglesiaa")
os.makedirs(_OUT, exist_ok=True)

USE_BANDS = ["blue", "green"]
CAL_NAMES = ["c550", "omega", "eta", "dz"]
CAL_BOUNDS = np.array([[0.10, 1.50], [0.50, 0.97], [-1.50, 2.50], [-1.50, 2.00]])

# Stencil: offsets horizontales en circulo de radio R (paso 0.5 m) x 3 planos z.
STEN_R = 2.5
_g = np.arange(-STEN_R, STEN_R + 1e-9, 0.5)
OFFSETS = np.array([(dx, dy) for dx in _g for dy in _g if dx * dx + dy * dy <= STEN_R**2 + 1e-9])
N_OFF = len(OFFSETS)
Z_PLANES = np.array(TARGET_DEPTHS, dtype=float)   # [8,10,12]


def design(n, seed=99):
    u = qmc.LatinHypercube(d=4, seed=seed).random(n)
    return qmc.scale(u, CAL_BOUNDS[:, 0], CAL_BOUNDS[:, 1])


# Centro y dispersion para refinamiento alrededor del pico (post. atacado).
# Override por entorno (REF_MU / REF_SD, csv) para adaptar a otra grilla/sitio.
REFINE_MU = np.array([float(v) for v in os.environ.get("REF_MU", "1.23,0.71,0.19,0.32").split(",")])
REFINE_SD = np.array([float(v) for v in os.environ.get("REF_SD", "0.30,0.12,0.70,0.90").split(",")])


def refine_design(n, seed=321):
    rng = np.random.default_rng(seed)
    out = []
    while len(out) < n:
        s = rng.normal(REFINE_MU, REFINE_SD)
        if np.all(s >= CAL_BOUNDS[:, 0]) and np.all(s <= CAL_BOUNDS[:, 1]):
            out.append(s)
    return np.array(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=360)
    ap.add_argument("--start", type=int, default=0)
    ap.add_argument("--count", type=int, default=60)
    ap.add_argument("--rays", type=int, default=100000)
    ap.add_argument("--refine", action="store_true")
    args = ap.parse_args()

    recs = load_measurements(os.path.join(_ROOT, "measurements", _MEAS))
    pts = [(r["x"], r["y"], r["z"]) for r in recs]
    npts = len(pts)
    X = refine_design(args.n) if args.refine else design(args.n)
    tag = "ref" if args.refine else "chunk"
    end = min(args.start + args.count, args.n)
    runner = SimRunner(rays=args.rays, seed=0)

    # Geometria del stencil (una vez).
    cand_path = os.path.join(_OUT, "candidates.npz")
    if not os.path.exists(cand_path):
        np.savez(cand_path, offsets=OFFSETS, z_planes=Z_PLANES,
                 pts=np.array(pts), bands=np.array(USE_BANDS),
                 cal_names=np.array(CAL_NAMES), bounds=CAL_BOUNDS,
                 sten_r=STEN_R)

    # Puntos-mundo de todos los candidatos horizontales (compartidos entre planos):
    # para cada punto, (x+dx, y+dy) para cada offset -> [npts*N_OFF, 2]
    base_xy = np.array([[p[0], p[1]] for p in pts])
    world = (base_xy[:, None, :] + OFFSETS[None, :, :]).reshape(-1, 2)  # [npts*N_OFF,2]

    import time
    t0 = time.time()
    n_done = 0
    for k in range(args.start, end):
        c550, omega, eta, dz = X[k]
        theta = [1.0, dz, 0.0, c550, omega, eta]
        cfg = runner.build_config(theta)
        res = runner.eng.run(cfg)
        # Y[punto, banda, plano_z, offset] de log10(sim mW/m2)
        Y = np.full((npts, len(USE_BANDS), len(Z_PLANES), N_OFF), np.nan, dtype=np.float32)
        for zi, d in enumerate(TARGET_DEPTHS):
            interps = runner._band_grids(res, d)
            for bi, b in enumerate(USE_BANDS):
                itp = interps[b]
                if itp is None:
                    vals = np.zeros(len(world))
                else:
                    vals = itp(world)            # batch
                vals = np.log10(np.maximum(vals.reshape(npts, N_OFF) * 1e3, 1e-3))
                Y[:, bi, zi, :] = vals
        fname = f"ref_{k:04d}.npz" if args.refine else f"chunk_{k:04d}.npz"
        np.savez_compressed(os.path.join(_OUT, fname), idx=k, params=X[k], Y=Y)
        n_done += 1
    dt = time.time() - t0
    done = len([f for f in os.listdir(_OUT) if f.startswith("chunk_")])
    print(f"procesadas {n_done} [{args.start}:{end}] en {dt:.0f}s "
          f"({dt/max(n_done,1):.2f}s/corr) | total chunks: {done}/{args.n}")


if __name__ == "__main__":
    main()
