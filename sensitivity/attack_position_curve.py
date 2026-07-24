"""
Relacion fina entre la incertidumbre de posicion del sensor (sigma_xy) y el ajuste.

Barre sigma_xy en malla fina (sin inclinacion) y reporta, para cada valor:
  - R2 validado cruzado (posicion inferida con azul, prediciendo verde) = honesto
  - R2 in-sample (posicion informada por ambas bandas) = optimista
  - evidencia bayesiana relativa (para ver que sigma prefieren los datos)
Ademas estima el sigma_xy minimo para alcanzar R2 objetivo. Sirve para juzgar si
hace falta un sigma "grande" (poco fisico) o si un error de posicion modesto ya
explica el piso de desajuste.
"""
import os
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from attack_infer import load_sweep, zenith_tan, _importance_weights, S_DISC, LN10
from meas_parser import load_measurements

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
_OUT = os.path.join(_HERE, "out")
USE_BANDS = ["blue", "green"]
OUTLIER_PT = (10.0, 10.0, 8.0)
SIG_Z = 1.0
O_GRID = np.linspace(-3.5, 0.5, 21)


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
    tan_th = zenith_tan(pts)

    both = use[:, 0] & use[:, 1]
    P = np.where(both)[0]; n_pt = len(P)
    Ypt = Yflat[:, P, :, :]; lm_pt = logmeas[P, :]
    dz2_pt = dz2_cand[P, :]
    s2 = np.full(n_pt, S_DISC**2)          # sin inclinacion
    s2b = s2[None, :, None, None]

    def compute(sxy, sz):
        wh = np.exp(-0.5 * dh2 / sxy**2)
        wpos = np.exp(-0.5 * dz2_pt / sz**2) * np.tile(wh, nz)[None, :]
        wpos = wpos / wpos.sum(axis=1, keepdims=True)
        best_ll = np.full(nd, -np.inf); best_O = np.zeros(nd)
        for O in O_GRID:
            diff = lm_pt[None, :, :, None] - (Ypt + O)
            logg = -0.5 * diff**2 / s2b - 0.5*np.log(2*np.pi*s2b)
            gb = np.exp(logg.sum(axis=2))
            mix = np.sum(wpos[None, :, :] * gb, axis=2)
            ll = np.sum(np.log(mix + 1e-300), axis=1)
            upd = ll > best_ll; best_ll[upd] = ll[upd]; best_O[upd] = O
        ll = best_ll + log_iw
        w = np.exp(ll - ll.max()); w /= w.sum()
        logZ = ll.max() + np.log(np.mean(np.exp(ll - ll.max())))
        # cross-val azul->verde
        diffB = lm_pt[None, :, 0, None]-(Ypt[:, :, 0, :]+best_O[:, None, None])
        gB = np.exp(-0.5*diffB**2/s2[None, :, None])
        postB = wpos[None, :, :]*gB; postB /= (postB.sum(2, keepdims=True)+1e-300)
        predG = np.sum(postB*(Ypt[:, :, 1, :]+best_O[:, None, None]), axis=2)
        residG = lm_pt[None, :, 1]-predG
        r2x = 1 - np.sum((np.sum(w[:, None]*residG, axis=0))**2)/np.sum((lm_pt[:, 1]-lm_pt[:, 1].mean())**2)
        return r2x, logZ

    SIG = np.round(np.arange(0.1, 3.01, 0.2), 2)
    TINY = 0.05
    # Tres cortes: solo horizontal, solo profundidad, ambos acoplados
    curves = {"horizontal (σ_z→0)": [], "profundidad (σ_xy→0)": [], "ambos": []}
    for s in SIG:
        curves["horizontal (σ_z→0)"].append(compute(s, TINY))
        curves["profundidad (σ_xy→0)"].append(compute(TINY, s))
        curves["ambos"].append(compute(s, s))
    for k in curves:
        curves[k] = np.array(curves[k])   # [nS, (r2x,logZ)]

    r2_nominal, _ = compute(TINY, TINY)
    print(f"R2 posicion ~nominal (σ_xy=σ_z=0.05): {r2_nominal:.3f}")
    print(f"\n{'sigma[m]':>8}{'horiz':>9}{'prof':>9}{'ambos':>9}  (R2 validado cruzado)")
    for i, s in enumerate(SIG):
        print(f"{s:>8.1f}{curves['horizontal (σ_z→0)'][i,0]:>9.3f}"
              f"{curves['profundidad (σ_xy→0)'][i,0]:>9.3f}{curves['ambos'][i,0]:>9.3f}")

    fig, ax = plt.subplots(figsize=(9.2, 5.4))
    cols = {"horizontal (σ_z→0)": "#C55A11", "profundidad (σ_xy→0)": "#2E75B6", "ambos": "#548235"}
    mk = {"horizontal (σ_z→0)": "o-", "profundidad (σ_xy→0)": "s-", "ambos": "^-"}
    for k in curves:
        ax.plot(SIG, curves[k][:, 0], mk[k], color=cols[k], lw=2.2, ms=4, label=k)
    ax.axhline(r2_nominal, color="#C00000", ls="--", lw=1.4,
               label=f"posición ~nominal (R²={r2_nominal:.2f})")
    ax.set_xlabel("σ incertidumbre de posición del sensor [m]")
    ax.set_ylabel("R² validación cruzada (azul→verde)"); ax.set_ylim(0.3, 1.0)
    ax.grid(ls=":", alpha=0.5); ax.legend(fontsize=9, loc="lower right")
    ax.set_title("¿Qué eje de la posición recupera el ajuste? Horizontal vs profundidad")
    fig.tight_layout(); fig.savefig(os.path.join(_OUT, "position_curve.png"), dpi=135)
    print("Figura: position_curve.png")
    np.savez(os.path.join(_OUT, "position_curve.npz"), sig=SIG,
             horiz=curves["horizontal (σ_z→0)"], prof=curves["profundidad (σ_xy→0)"],
             ambos=curves["ambos"], r2_nominal=r2_nominal)


if __name__ == "__main__":
    main()
