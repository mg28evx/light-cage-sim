"""
Diagnostico del piso de desajuste: incertidumbre de POSICION del sensor.

Hipotesis: cerca de las lamparas el campo tiene gradientes fuertes, de modo que un
error de 1-2 m en la posicion real del sensor respecto de su coordenada nominal
produce un error grande de irradiancia que ningun (a,b) puede corregir.

Prueba: se corre el simulador a alta resolucion (una vez por theta), se guarda el
campo E(x,y) por profundidad y banda, y se recalcula el ajuste permitiendo que cada
sensor se ubique dentro de una vecindad de su nominal:
    - PROFILING (techo optimista): cada punto toma el candidato de la vecindad que
      mejor ajusta -> cuanto PODRIA explicar la posicion.
    - MARGINALIZACION (honesto): se integra la verosimilitud sobre un prior gaussiano
      de offset de posicion (x,y,z) -> R2 defendible bajo esa incertidumbre.

Uso:  python3 attack_floor.py --rays 150000 --theta best
"""
import os
import argparse
import numpy as np

from meas_parser import load_measurements
from sim_interface import SimRunner, TARGET_DEPTHS

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
_OUT = os.path.join(_HERE, "out")
USE_BANDS = ["blue", "green"]
OUTLIER_PT = (10.0, 10.0, 8.0)

THETAS = {
    # [f_power, dz, pos_jitter, c550, omega, eta]
    "best":   [1.0, 1.964, 0.0, 0.889, 0.954, 1.014],   # mejor RMSE del barrido
    "median": [1.0, 1.331, 0.0, 0.738, 0.874, 0.636],   # mediana posterior
}


def _r2_rmse(lm, ls_off):
    resid = lm - ls_off
    ss = np.sum(resid ** 2)
    tot = np.sum((lm - lm.mean()) ** 2)
    return (1 - ss / tot if tot > 0 else np.nan), np.sqrt(np.mean(resid ** 2))


def build_field(runner, theta):
    """Devuelve interps[depth][band] = RegularGridInterpolator de E(x,y)."""
    cfg = runner.build_config(theta)
    res = runner.eng.run(cfg)
    return {d: runner._band_grids(res, d) for d in TARGET_DEPTHS}


def sample_candidates(interps, x, y, z, offs_xy, z_choices):
    """Matriz [n_cand, n_band] de log10(sim mW/m2) para offsets (dx,dy) y planos z."""
    rows = []
    for zc in z_choices:
        itp = interps[zc]
        for (dx, dy) in offs_xy:
            vals = []
            for b in USE_BANDS:
                v = 0.0 if itp[b] is None else float(itp[b]((x + dx, y + dy)))
                vals.append(np.log10(max(v * 1e3, 1e-3)))
            rows.append(vals)
    return np.array(rows)  # [n_cand, n_band]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rays", type=int, default=150000)
    ap.add_argument("--theta", default="best", choices=list(THETAS))
    args = ap.parse_args()

    recs = load_measurements(os.path.join(_ROOT, "measurements", "puntaiglesiaa"))
    runner = SimRunner(rays=args.rays, seed=0)
    import time
    t = time.time()
    interps = build_field(runner, THETAS[args.theta])
    print(f"campo a {args.rays} rayos en {time.time()-t:.1f}s | theta={args.theta}")

    # Puntos y mediciones (log10 mW/m2), banda a banda.
    entries = []  # (x,y,z, band_index, logmeas)
    for r in recs:
        if r["censored"] or (r["x"], r["y"], r["z"]) == OUTLIER_PT:
            continue
        for bi, b in enumerate(USE_BANDS):
            m = r[f"band_{b}"]
            if m > 0:
                entries.append((r["x"], r["y"], r["z"], bi, np.log10(m)))
    lm = np.array([e[4] for e in entries])
    print(f"{len(entries)} residuos (azul+verde, sin censura ni outlier)")

    # Vecindad de offsets horizontales (paso 0.5 m).
    def offs(radius):
        g = np.arange(-radius, radius + 1e-9, 0.5)
        return [(dx, dy) for dx in g for dy in g if dx * dx + dy * dy <= radius * radius + 1e-9]

    # --- 0) baseline: posicion nominal exacta ---
    ls0 = np.array([sample_candidates(interps, x, y, z, [(0, 0)], [z])[0, bi]
                    for (x, y, z, bi, _) in entries])
    off = np.median(lm - ls0)
    r2_0, rmse_0 = _r2_rmse(lm, ls0 + off)
    print(f"\n[baseline nominal]           R2={r2_0:6.3f}  RMSE={rmse_0:.3f}")

    # Precalcula candidatos por entrada (con vecindad grande y z vecinos) una vez.
    RmaxProf = 3.0
    offs_big = offs(RmaxProf)
    d2 = np.array([dx * dx + dy * dy for (dx, dy) in offs_big])  # dist^2 horizontal
    cand_cache = []
    for (x, y, z, bi, _) in entries:
        z_choices = [zc for zc in TARGET_DEPTHS if abs(zc - z) <= 2.0]
        # matriz [n_z*n_off, n_band]; guardamos tambien dz y d2 alineados
        rows, zoff = [], []
        for zc in z_choices:
            itp = interps[zc]
            for k, (dx, dy) in enumerate(offs_big):
                vals = [0.0 if itp[b] is None else float(itp[b]((x + dx, y + dy))) for b in USE_BANDS]
                rows.append([np.log10(max(v * 1e3, 1e-3)) for v in vals])
                zoff.append(zc - z)
        cand_cache.append((np.array(rows), np.tile(d2, len(z_choices)), np.array(zoff), bi))

    # --- 1) PROFILING dentro de radio r (techo optimista) ---
    print("\n-- profiling (techo): cada sensor toma el mejor candidato dentro del radio --")
    for R in [0.5, 1.0, 1.5, 2.0, 3.0]:
        for _ in range(6):  # iterar offset global <-> mejor candidato
            ls = []
            for (rows, dd, zoff, bi) in cand_cache:
                mask = (dd <= R * R + 1e-9)
                ls.append(rows[mask, bi])
            # con offset actual, cada punto elige el candidato mas cercano a la medicion
            chosen = []
            for i, cand in enumerate(ls):
                chosen.append(cand[np.argmin(np.abs(lm[i] - (cand + off)))])
            chosen = np.array(chosen)
            off = np.median(lm - chosen)
        r2, rmse = _r2_rmse(lm, chosen + off)
        print(f"   radio {R:>3}m            R2={r2:6.3f}  RMSE={rmse:.3f}")

    # --- 2) MARGINALIZACION con prior gaussiano de posicion (honesto) ---
    print("\n-- marginalizacion: integra verosimilitud sobre prior N(0,sigma) de offset --")
    off = np.median(lm - ls0)
    for sig_xy, sig_z in [(0.5, 0.5), (1.0, 1.0), (1.5, 1.0), (2.0, 1.0)]:
        # sigma de discrepancia estimada por MAD de residuos baseline
        s_obs = max(1.4826 * np.median(np.abs((lm - ls0 - off) - np.median(lm - ls0 - off))), 0.15)
        # iterar offset global
        for _ in range(6):
            pred = []
            for i, (rows, dd, zoff, bi) in enumerate(cand_cache):
                cand = rows[:, bi] + off
                wpos = np.exp(-0.5 * (dd / sig_xy**2 + (zoff**2) / sig_z**2))
                # verosimilitud marginal del punto = sum_k wpos_k * N(lm|cand_k, s_obs)
                like = wpos * np.exp(-0.5 * ((lm[i] - cand) / s_obs) ** 2)
                # prediccion puntual = media posterior de la posicion (para R2)
                pred.append(np.sum(like * (cand)) / (np.sum(like) + 1e-300))
            pred = np.array(pred)
            off += np.median(lm - pred)
        r2, rmse = _r2_rmse(lm, pred)
        print(f"   sigma_xy={sig_xy}m sigma_z={sig_z}m   R2={r2:6.3f}  RMSE={rmse:.3f}")


if __name__ == "__main__":
    main()
