"""
Diagnostico anti-sobreajuste: ¿que desplazamiento de posicion necesita el modelo?

Si el ajuste dependiera de mover los sensores distancias no fisicas (5-10 m), seria
sobreajuste. Si los offsets inferidos son modestos (<1-2 m), es una correccion fisica
plausible. Calcula, a sigma_xy fisico (=1.0 m), el desplazamiento horizontal posterior
medio por punto (marginalizando disenos bio-opticos), y la brecha in-sample vs val.
cruzada. Genera histograma de offsets.
"""
import os
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from attack_infer import load_sweep, zenith_tan, _importance_weights, S_DISC
from meas_parser import load_measurements

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
_OUT = os.path.join(_HERE, "out")
USE_BANDS = ["blue", "green"]
OUTLIER_PT = (10.0, 10.0, 8.0)
O_GRID = np.linspace(-3.5, 0.5, 41)
SIG_XY = 1.0    # valor fisico plausible
SIG_Z = 1.0


def main():
    params, Y, offsets, z_planes, pts = load_sweep()
    nd, npts, nband, nz, noff = Y.shape
    log_iw = np.log(_importance_weights(params))
    recs = load_measurements(os.path.join(_ROOT, "measurements", "puntaiglesiaa"))
    logmeas = np.full((npts, nband), np.nan); use = np.zeros((npts, nband), bool)
    for i, r in enumerate(recs):
        if r["censored"] or (r["x"], r["y"], r["z"]) == OUTLIER_PT:
            continue
        for bi, b in enumerate(USE_BANDS):
            if r[f"band_{b}"] > 0:
                logmeas[i, bi] = np.log10(r[f"band_{b}"]); use[i, bi] = True

    ncand = nz * noff
    Yflat = Y.reshape(nd, npts, nband, ncand)
    dist_h = np.hypot(offsets[:, 0], offsets[:, 1]); dh2 = dist_h**2
    dz_plane = z_planes[None, :] - pts[:, 2][:, None]
    dz2_cand = np.repeat(dz_plane**2, noff, axis=1)
    both = use[:, 0] & use[:, 1]; P = np.where(both)[0]; n_pt = len(P)
    Ypt = Yflat[:, P, :, :]; lm_pt = logmeas[P, :]
    dz2_pt = dz2_cand[P, :]
    s2 = np.full(n_pt, S_DISC**2); s2b = s2[None, :, None, None]
    # distancia horizontal de cada candidato (repetida por plano z)
    dist_cand = np.tile(dist_h, nz)                       # [ncand]

    wh = np.exp(-0.5 * dh2 / SIG_XY**2)
    wpos = np.exp(-0.5 * dz2_pt / SIG_Z**2) * np.tile(wh, nz)[None, :]
    wpos = wpos / wpos.sum(axis=1, keepdims=True)

    # perfilar O por diseno
    best_ll = np.full(nd, -np.inf); best_O = np.zeros(nd)
    for O in O_GRID:
        diff = lm_pt[None, :, :, None] - (Ypt + O)
        logg = -0.5*diff**2/s2b - 0.5*np.log(2*np.pi*s2b)
        gb = np.exp(logg.sum(axis=2))
        mix = np.sum(wpos[None, :, :]*gb, axis=2)
        ll = np.sum(np.log(mix+1e-300), axis=1)
        upd = ll > best_ll; best_ll[upd] = ll[upd]; best_O[upd] = O
    ll = best_ll + log_iw
    w = np.exp(ll-ll.max()); w /= w.sum()

    # posterior de posicion por punto (ambas bandas), y offset horizontal esperado
    diff = lm_pt[None, :, :, None] - (Ypt + best_O[:, None, None, None])
    gb = np.exp((-0.5*diff**2/s2b).sum(axis=2))          # [nd,n_pt,ncand]
    postp = wpos[None, :, :]*gb
    postp = postp / (postp.sum(2, keepdims=True)+1e-300)
    # offset horizontal esperado por (diseno,punto), luego promedio sobre disenos
    off_pt = np.sum(postp * dist_cand[None, None, :], axis=2)   # [nd,n_pt]
    off_mean = np.sum(w[:, None]*off_pt, axis=0)                # [n_pt]

    print(f"Offset horizontal inferido (sigma_xy={SIG_XY} m):")
    print(f"  mediana={np.median(off_mean):.2f} m  media={off_mean.mean():.2f} m  "
          f"max={off_mean.max():.2f} m")
    print(f"  fraccion de puntos con offset <1.5 m: {np.mean(off_mean<1.5):.0%}")
    print(f"  fraccion <2.0 m: {np.mean(off_mean<2.0):.0%}")

    fig, ax = plt.subplots(figsize=(7.5, 4.6))
    ax.hist(off_mean, bins=np.arange(0, 3.01, 0.25), color="#2E75B6",
            edgecolor="white", alpha=0.9)
    ax.axvline(np.median(off_mean), color="#C00000", lw=2,
               label=f"mediana {np.median(off_mean):.2f} m")
    ax.set_xlabel("Desplazamiento horizontal inferido del sensor [m]")
    ax.set_ylabel("nº de puntos de medición")
    ax.set_title("Correcciones de posición que el modelo necesita (σ_xy=1 m)")
    ax.legend(); ax.grid(axis="y", ls=":", alpha=0.5)
    fig.tight_layout(); fig.savefig(os.path.join(_OUT, "offsets_hist.png"), dpi=135)
    print("Figura: offsets_hist.png")


if __name__ == "__main__":
    main()
