"""
Inferencia alternativa: pendientes espectrales INDEPENDIENTES (a550,b550,eta_a,eta_b,dz),
con marginalizacion de posicion del sensor (igual marco que attack_infer) y validacion
cruzada azul->verde. Reporta el posterior y compara identificabilidad/ajuste con el modelo
de pendiente compartida.
"""
import os
import glob
import numpy as np

from meas_parser import load_measurements
from attack_infer import zenith_tan, S_DISC

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
_OUT = os.path.join(_HERE, "out")
_ATK = os.path.join(_OUT, "attack_ab")
USE_BANDS = ["blue", "green"]
OUTLIER_PT = (10.0, 10.0, 8.0)
O_GRID = np.linspace(-3.5, 0.5, 41)
SIG_XY = 1.0        # valor fisico plausible (segun analisis de la curva)
SIG_Z = 1.0
CAL_NAMES = ["a550", "b550", "eta_a", "eta_b", "dz"]


def load_sweep():
    cand = np.load(os.path.join(_ATK, "candidates.npz"), allow_pickle=True)
    files = sorted(glob.glob(os.path.join(_ATK, "chunk_*.npz")))
    params, Ys = [], []
    for f in files:
        d = np.load(f); params.append(d["params"]); Ys.append(d["Y"])
    return (np.array(params), np.stack(Ys).astype(np.float32),
            cand["offsets"], cand["z_planes"], cand["pts"])


def _wq(x, w, qs):
    o = np.argsort(x); x, w = x[o], w[o]
    cw = np.cumsum(w) - 0.5 * w; cw /= w.sum()
    return np.interp(qs, cw, x)


def main():
    params, Y, offsets, z_planes, pts = load_sweep()
    nd, npts, nband, nz, noff = Y.shape
    print(f"cargadas {nd} corridas (5 params) | Y{Y.shape}")

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
    Ypt = Yflat[:, P, :, :]; lm_pt = logmeas[P, :]; dz2_pt = dz2_cand[P, :]
    s2 = np.full(n_pt, S_DISC**2); s2b = s2[None, :, None, None]

    wh = np.exp(-0.5 * dh2 / SIG_XY**2)
    wpos = np.exp(-0.5 * dz2_pt / SIG_Z**2) * np.tile(wh, nz)[None, :]
    wpos = wpos / wpos.sum(axis=1, keepdims=True)

    best_ll = np.full(nd, -np.inf); best_O = np.zeros(nd)
    for O in O_GRID:
        diff = lm_pt[None, :, :, None] - (Ypt + O)
        gb = np.exp((-0.5*diff**2/s2b - 0.5*np.log(2*np.pi*s2b)).sum(axis=2))
        mix = np.sum(wpos[None, :, :]*gb, axis=2)
        ll = np.sum(np.log(mix+1e-300), axis=1)
        upd = ll > best_ll; best_ll[upd] = ll[upd]; best_O[upd] = O
    ll = best_ll
    w = np.exp(ll - ll.max()); w /= w.sum()

    # in-sample y cross-val (azul->verde)
    diff = lm_pt[None, :, :, None] - (Ypt + best_O[:, None, None, None])
    gb = np.exp((-0.5*diff**2/s2b).sum(axis=2))
    postp = wpos[None, :, :]*gb; postp /= (postp.sum(2, keepdims=True)+1e-300)
    pred = np.sum(postp[:, :, None, :]*(Ypt+best_O[:, None, None, None]), axis=3)
    rpm = np.sum(w[:, None, None]*(lm_pt[None]-pred), axis=0).reshape(-1)
    lmf = lm_pt.reshape(-1)
    r2in = 1 - np.sum(rpm**2)/np.sum((lmf-lmf.mean())**2)
    diffB = lm_pt[None, :, 0, None]-(Ypt[:, :, 0, :]+best_O[:, None, None])
    gB = np.exp(-0.5*diffB**2/s2[None, :, None])
    postB = wpos[None, :, :]*gB; postB /= (postB.sum(2, keepdims=True)+1e-300)
    predG = np.sum(postB*(Ypt[:, :, 1, :]+best_O[:, None, None]), axis=2)
    rpmG = np.sum(w[:, None]*(lm_pt[None, :, 1]-predG), axis=0)
    r2x = 1 - np.sum(rpmG**2)/np.sum((lm_pt[:, 1]-lm_pt[:, 1].mean())**2)

    ess = w.sum()**2/np.sum(w**2)
    print(f"\nR2 in-sample={r2in:.3f}  R2 cross-val(azul->verde)={r2x:.3f}  ESS={ess:.0f}")
    print(f"\n=== Posterior modelo de PENDIENTES INDEPENDIENTES (sigma_xy={SIG_XY} m) ===")
    d = {n: params[:, i] for i, n in enumerate(CAL_NAMES)}
    summ = {}
    for k, v in d.items():
        lo, med, hi = _wq(v, w, [0.05, 0.5, 0.95])
        summ[k] = (med, lo, hi)
        print(f"  {k:<6} med={med:7.3f}  90%CI=[{lo:7.3f}, {hi:7.3f}]")
    # derivados espectrales en azul(450) y verde(550-ish -> uso 550 y 500)
    a550 = np.sum(w*d["a550"]); b550 = np.sum(w*d["b550"])
    ea = np.sum(w*d["eta_a"]); eb = np.sum(w*d["eta_b"])
    print(f"\n  a(450)/a(550) = {(450/550)**(-ea):.3f}   b(450)/b(550) = {(450/550)**(-eb):.3f}")
    print(f"  omega(450)={b550*(450/550)**(-eb)/(a550*(450/550)**(-ea)+b550*(450/550)**(-eb)):.3f}"
          f"  omega(550)={b550/(a550+b550):.3f}")

    np.savez(os.path.join(_OUT, "attack_ab_posterior.npz"),
             params=params, w=w, cal_names=CAL_NAMES, r2x=r2x, r2in=r2in)
    _spectral_figure(summ, w, params)
    return summ, w


def _spectral_figure(summ, w, params):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    wl = np.linspace(430, 660, 60)

    # Modelo independiente (posterior medio)
    a550 = np.sum(w*params[:, 0]); b550 = np.sum(w*params[:, 1])
    ea = np.sum(w*params[:, 2]); eb = np.sum(w*params[:, 3])
    a_ind = a550*(wl/550)**(-ea); b_ind = b550*(wl/550)**(-eb); c_ind = a_ind+b_ind

    # Modelo de pendiente compartida (Fase 3): c550, omega, eta
    try:
        sh = np.load(os.path.join(_OUT, "attack_posterior.npz"))
        ps, ws = sh["params"], sh["w"]
        c550 = np.sum(ws*ps[:, 0]); om = np.sum(ws*ps[:, 1]); et = np.sum(ws*ps[:, 2])
        c_sh = c550*(wl/550)**(-et); a_sh = (1-om)*c_sh; b_sh = om*c_sh
        have_shared = True
    except Exception:
        have_shared = False

    fig, axes = plt.subplots(1, 2, figsize=(12, 4.8), sharey=True)
    ax = axes[0]
    ax.plot(wl, c_ind, color="#C00000", lw=2.4, label="c = a+b")
    ax.plot(wl, a_ind, color="#2E75B6", lw=2, label="a (absorción)")
    ax.plot(wl, b_ind, color="#548235", lw=2, label="b (dispersión)")
    ax.set_title("Pendientes independientes"); ax.set_xlabel("λ [nm]")
    ax.set_ylabel("coeficiente [1/m]"); ax.grid(ls=":", alpha=0.5); ax.legend(fontsize=9)
    ax.axvspan(400, 500, color="#2E75B6", alpha=0.06); ax.axvspan(500, 600, color="#548235", alpha=0.06)
    ax = axes[1]
    if have_shared:
        ax.plot(wl, c_sh, color="#C00000", lw=2.4, label="c = a+b")
        ax.plot(wl, a_sh, color="#2E75B6", lw=2, label="a (absorción)")
        ax.plot(wl, b_sh, color="#548235", lw=2, label="b (dispersión)")
    ax.set_title("Pendiente compartida (η único, ω constante)"); ax.set_xlabel("λ [nm]")
    ax.grid(ls=":", alpha=0.5); ax.legend(fontsize=9)
    ax.axvspan(400, 500, color="#2E75B6", alpha=0.06); ax.axvspan(500, 600, color="#548235", alpha=0.06)
    fig.suptitle("Atenuación espectral estimada — Punta Iglesia", color="#1F3864", weight="bold")
    fig.tight_layout(rect=[0, 0, 1, 0.95])
    fig.savefig(os.path.join(_OUT, "spectral_attenuation.png"), dpi=135)
    print("Figura: spectral_attenuation.png")


if __name__ == "__main__":
    main()
